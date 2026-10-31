# Design system

`tokens.json` is the source of truth for how the web app looks. `frontend/src/styles/app.css`
implements it as CSS variables; components use the variables, never raw hex values.

## Rules

- **Light, calm, low energy.** Warm off-white background `#F5F3EC`, near-black text `#1C1A18`,
  one accent: olive green `#4F6814` (buttons, links, active states). Sand `#E3D2B4` for
  secondary surfaces, chips and dividers. No other saturated colours except status (success /
  warning / danger), kept muted.
- **Type:** headings in Nohemi, everything else in Satoshi, system-ui fallback. Scale: h1 72px,
  h2 40px, body 24px on marketing pages; the app UI uses a smaller body (16–18px) with the same
  families. Few sizes; no mono except booking references.
- **Shape:** 4px spacing grid, 16px radius on cards, inputs and buttons, no shadows on buttons,
  at most a soft shadow on floating surfaces.
- **Primary button:** `#4F6814` background, `#F5F3EC` text, 16px radius, no shadow.
- **Density:** one primary action per screen, details behind disclosure, generous whitespace.

## Fonts

- Satoshi: Indian Type Foundry via Fontshare (free for commercial use under the ITF Free Font
  License). Self-host the woff2 files in `frontend/public/fonts/`.
- Nohemi: check the licence before shipping; until a licensed file is in the repo, the heading
  stack falls back to system-ui.

The palette and type pairing were taken from a reference site's design tokens. No logo, images
or copy from that site are used.
