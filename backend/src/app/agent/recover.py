"""The mess between the planner and a clean page.

Two jobs:
  1. auto_dismiss(): kill cookie/consent banners and obvious upsell modals so the
     planner doesn't waste steps on them.
  2. detect_block(): spot the deliberate human-in-the-loop gates (CAPTCHA, 3-D
     Secure / OTP) that no purchasing agent should push through -> signal handoff.
"""

import contextlib

# Only unambiguous cookie/consent phrases. Generic words like "ok"/"continue"/
# "agree" are deliberately excluded — they collide with real checkout buttons
# (e.g. saucedemo's "Continue"), and clicking those would derail the flow.
_CONSENT_TEXT = [
    # English
    "accept all cookies",
    "accept all",
    "accept cookies",
    "i accept",
    "allow all cookies",
    "allow all",
    "accept & close",
    "agree and close",
    # Polish (RODO) — most specific first so we hit "accept" not "settings"/"reject"
    "akceptuję i przechodzę do serwisu",
    "akceptuję wszystkie",
    "zaakceptuj wszystkie",
    "akceptuję wszystko",
    "zaakceptuj i zamknij",
    "zgadzam się",
    "przejdź do serwisu",
    "akceptuję",
    "zaakceptuj",
    "akceptuj",
    "reject all",
]

# Selectors for *active* CAPTCHA / challenge widgets. detect_block only trips when
# one of these is actually visible — many sites (DataDome, reCAPTCHA v3, Cloudflare)
# load anti-bot JS on every page without ever challenging, so matching the HTML
# substring would falsely hand off on normal pages.
_CAPTCHA_SELECTORS = (
    'iframe[src*="captcha-delivery"]',
    'iframe[src*="geo.captcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[title*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    'iframe[title*="challenge"]',
    "#px-captcha",
    ".g-recaptcha",
    "#challenge-running",
)

_CAPTCHA_JS = r"""
(sels) => {
  for (const s of sels) {
    const el = document.querySelector(s);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width > 10 && r.height > 10 && st.visibility !== 'hidden' && st.display !== 'none')
      return s;
  }
  return '';
}
"""
# Real OTP / 3-D Secure CHALLENGE = a code input or a bank/3DS iframe. We do NOT
# match the phrase "3-D Secure" in body text — it appears in payment-method
# descriptions (e.g. Media Expert's card blurb) and caused false handoffs. The
# planner is the backstop: it still calls handoff when it SEES a real challenge.
_OTP_JS = r"""
() => {
  const inp = document.querySelector('input[autocomplete="one-time-code"], input[name*="otp" i], input[id*="otp" i], input[name*="sms" i], input[name*="2fa" i]');
  if (inp) {
    const r = inp.getBoundingClientRect(); const s = getComputedStyle(inp);
    if (r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none') return 'one-time-code input';
  }
  const ifr = [...document.querySelectorAll('iframe')].find(f =>
    /3ds|threeds|\/acs|3-d.?secure|paygateway/i.test((f.getAttribute('src') || '') + ' ' + (f.getAttribute('title') || '')));
  if (ifr) { const r = ifr.getBoundingClientRect(); if (r.width > 50 && r.height > 50) return '3-D Secure iframe'; }
  return '';
}
"""


def auto_dismiss(page):
    """Best-effort dismiss of consent/upsell overlays. Never raises."""
    for label in _CONSENT_TEXT:
        with contextlib.suppress(Exception):
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(200)
                return True
    # generic close (X) buttons on modals
    for sel in ['[aria-label="Close"]', '[aria-label="close"]', "button.close", ".modal .close"]:
        with contextlib.suppress(Exception):
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(timeout=2000)
                page.wait_for_timeout(200)
                return True
    return False


def detect_block(page):
    """Return (blocked: bool, reason: str). Blocked = a human is required.

    CAPTCHA is detected by a *visible* challenge widget (see _CAPTCHA_SELECTORS),
    not by an HTML substring, so we don't hand off just because a site loads
    anti-bot JS on every page.
    """
    with contextlib.suppress(Exception):
        hit = page.evaluate(_CAPTCHA_JS, list(_CAPTCHA_SELECTORS))
        if hit:
            return True, f"visible captcha challenge ({hit})"
    # OTP / 3-D Secure: only a real challenge (code input or 3DS iframe), never a
    # mere mention of "3-D Secure" in a payment-method description.
    with contextlib.suppress(Exception):
        otp = page.evaluate(_OTP_JS)
        if otp:
            return True, f"otp/3ds challenge ({otp})"
    return False, ""
