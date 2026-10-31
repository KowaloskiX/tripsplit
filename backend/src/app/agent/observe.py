"""Turn the live page into a compact, model-friendly state.

We inject JS that finds every *visible, interactive* element, tags it with a stable
`data-agent-ref`, and returns a small list. The planner reasons over this list — it
never sees raw HTML — which is what makes the agent work on layouts it has never seen.
"""

_JS = r"""
() => {
  const out = [];
  let ref = 0;
  const sel = 'a,button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[onclick],[data-testid],[data-test],[data-cy]';
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
    const label =
      (el.getAttribute('aria-label') || '').trim() ||
      (el.innerText || el.value || el.placeholder || el.getAttribute('name') || el.getAttribute('title') || '').trim();
    out.push({
      ref: ref,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      name: (el.getAttribute('name') || '').slice(0, 40),
      testid: (el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy') || '').slice(0, 40),
      text: (label || '').replace(/\s+/g, ' ').slice(0, 80),
      placeholder: (el.placeholder || '').slice(0, 60),
      href: (el.getAttribute('href') || '').slice(0, 80),
      value: (el.value || '').slice(0, 40),
      options: el.tagName.toLowerCase() === 'select'
        ? Array.from(el.options).map(function (o) { return (o.textContent || '').trim(); }).filter(Boolean).slice(0, 25)
        : null,
    });
    if (out.length >= 120) break;
  }
  return {
    url: location.href,
    title: document.title,
    text_preview: ((document.body && document.body.innerText) || '').replace(/\s+/g, ' ').slice(0, 1200),
    elements: out,
  };
}
"""


def observe(page):
    state = page.evaluate(_JS)
    return state


def render_for_planner(state):
    """Compact text the planner sees. Keep it small — it's every-step context."""
    lines = [f"URL: {state['url']}", f"TITLE: {state['title']}", "", "INTERACTIVE ELEMENTS:"]
    for e in state["elements"]:
        bits = [f"#{e['ref']}", e["tag"] + (f"[{e['type']}]" if e["type"] else "")]
        desc = e["text"] or e["placeholder"] or e["name"] or e["testid"] or e["href"]
        if desc:
            bits.append(repr(desc))
        if e["testid"]:
            bits.append(f"testid={e['testid']}")
        if e.get("options"):
            bits.append("options=" + repr(e["options"]))
        lines.append("  " + " ".join(bits))
    lines.append("")
    lines.append("PAGE TEXT (truncated):")
    lines.append(state["text_preview"])
    return "\n".join(lines)
