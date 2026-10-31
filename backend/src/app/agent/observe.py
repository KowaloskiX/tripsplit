"""Turn the live page into a compact, typed state.

We inject JS that finds every *visible, interactive* element, tags it with a stable
`data-agent-ref`, and returns a small list. Each element carries its ACCESSIBLE identity —
role, accessible name (the associated `<label>`, `aria-label` or `aria-labelledby`), the
form `name`/`id` and the surrounding group (fieldset legend or table row). Those survive CSS
and layout churn, so they are what flows and the rule layer match on; the planner reasons
over the same list and never sees raw HTML.

The accessibility tree (`aria_snapshot`) is attached for the planner only — it is a compact,
semantic view of the page that replaces most of the need for a screenshot.
"""

from typing import Any

_JS = r"""
() => {
  const out = [];
  let ref = 0;
  const sel = 'a,button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[onclick],[data-testid],[data-test],[data-cy]';
  const clean = (s, n) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (el.getAttribute('role')) return el.getAttribute('role');
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      if (['submit', 'button', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      return 'textbox';
    }
    return '';
  };
  const labelOf = (el) => {
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean)
        .map((n) => n.innerText).join(' ');
      if (t.trim()) return t;
    }
    if (el.labels && el.labels.length) return Array.from(el.labels).map((l) => l.innerText).join(' ');
    return '';
  };
  const contextOf = (el) => {
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return clean(lg.innerText, 80); }
    const row = el.closest('tr,li,article,[role=row]');
    if (row) return clean(row.innerText, 120);
    return '';
  };
  const els = document.querySelectorAll(sel);
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const visible = r.width > 1 && r.height > 1 &&
        style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0' &&
        r.bottom > 0 && r.top < (window.innerHeight + 1200) &&
        r.right > 0 && r.left < window.innerWidth;
    if (!visible) continue;
    if (el.type === 'hidden' || el.disabled) continue;
    ref += 1;
    el.setAttribute('data-agent-ref', String(ref));
    const label = clean(labelOf(el), 80);
    const text =
      (el.getAttribute('aria-label') || '').trim() ||
      (el.innerText || el.value || el.placeholder || el.getAttribute('name') || el.getAttribute('title') || '').trim();
    out.push({
      ref: ref,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      role: implicitRole(el),
      name: (el.getAttribute('name') || '').slice(0, 40),
      id: (el.id || '').slice(0, 40),
      testid: (el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy') || '').slice(0, 40),
      text: clean(text, 80),
      label: label,
      placeholder: (el.placeholder || '').slice(0, 60),
      href: (el.getAttribute('href') || '').slice(0, 80),
      value: (el.value || '').slice(0, 40),
      required: !!el.required,
      checked: !!el.checked,
      context: contextOf(el),
      options: el.tagName.toLowerCase() === 'select'
        ? Array.from(el.options).map(function (o) { return (o.textContent || '').trim(); }).filter(Boolean).slice(0, 25)
        : null,
    });
    if (out.length >= 120) break;
  }
  const bodyText = ((document.body && document.body.innerText) || '').replace(/\s+/g, ' ');
  // Labelled rows (table th/td, dl dt/dd): the raw material for summary extraction.
  const rows = [];
  for (const tr of document.querySelectorAll('tr')) {
    const th = tr.querySelector('th'); const td = tr.querySelector('td');
    if (!th || !td) continue;
    rows.push({ label: clean(th.innerText, 60), value: clean(td.innerText, 400),
      items: Array.from(td.querySelectorAll('li')).map((li) => clean(li.innerText, 80)).slice(0, 12) });
    if (rows.length >= 40) break;
  }
  for (const dt of document.querySelectorAll('dt')) {
    const dd = dt.nextElementSibling;
    if (!dd || dd.tagName.toLowerCase() !== 'dd') continue;
    rows.push({ label: clean(dt.innerText, 60), value: clean(dd.innerText, 400),
      items: Array.from(dd.querySelectorAll('li')).map((li) => clean(li.innerText, 80)).slice(0, 12) });
    if (rows.length >= 40) break;
  }
  return {
    rows: rows,
    url: location.href,
    title: document.title,
    headings: Array.from(document.querySelectorAll('h1,h2')).map((h) => clean(h.innerText, 100)).filter(Boolean).slice(0, 8),
    text_preview: bodyText.slice(0, 1200),
    text: bodyText.slice(0, 8000),
    elements: out,
  };
}
"""


def observe(page: Any, with_aria: bool = False) -> dict[str, Any]:
    state: dict[str, Any] = page.evaluate(_JS)
    state["aria"] = ""
    if with_aria:
        try:
            state["aria"] = str(page.locator("body").aria_snapshot(timeout=3000))[:4000]
        except Exception:
            state["aria"] = ""
    return state


def render_for_planner(state: dict[str, Any]) -> str:
    """Compact text the planner sees. Keep it small — it's every-step context."""
    lines = [f"URL: {state['url']}", f"TITLE: {state['title']}", "", "INTERACTIVE ELEMENTS:"]
    for e in state["elements"]:
        bits = [f"#{e['ref']}", e["tag"] + (f"[{e['type']}]" if e["type"] else "")]
        desc = e.get("label") or e["text"] or e["placeholder"] or e["name"] or e["testid"]
        desc = desc or e["href"]
        if desc:
            bits.append(repr(desc))
        if e["testid"]:
            bits.append(f"testid={e['testid']}")
        if e.get("context") and e.get("role") == "button":
            bits.append(f"in={e['context'][:60]!r}")
        if e.get("required"):
            bits.append("required")
        if e.get("value") and e.get("role") in ("textbox", "combobox"):
            bits.append("filled")
        if e.get("options"):
            bits.append("options=" + repr(e["options"]))
        lines.append("  " + " ".join(bits))
    lines.append("")
    if state.get("aria"):
        lines.append("ACCESSIBILITY TREE (truncated):")
        lines.append(state["aria"])
    else:
        lines.append("PAGE TEXT (truncated):")
        lines.append(state["text_preview"])
    return "\n".join(lines)
