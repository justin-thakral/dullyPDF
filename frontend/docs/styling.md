# Styling Notes

The frontend styling uses shared design tokens in `index.css`, layered module imports in `App.css`, and component-scoped CSS files for feature/page-specific UI.

## Stylesheet layout

- `frontend/src/index.css`: global reset, theme tokens, base typography, global background, scrollbar styling.
- `frontend/src/App.css`: app style entrypoint that imports shared style modules in order.
- `frontend/src/styles/` modules:
  - `app-shell.css`: editor shell and shared container layout.
  - `ui-buttons.css`: shared button variants.
  - `header-bar.css`: top header controls.
  - `editor-panels.css`: field list + inspector panels.
  - `pdf-viewer.css` and `field-overlays.css`: viewer frame and field overlay visuals.
  - `motion-and-media.css`: motion helpers and responsive breakpoints.
  - `recaptcha.css`: reCAPTCHA badge positioning.
- `frontend/src/components/**/*.css`: component-scoped styling (homepage, auth pages, upload/search-fill, dialogs, demo tour).

Keep `App.css` import order unchanged unless you intentionally update cascade priority.

## Theme tokens

Defined in `frontend/src/index.css`:

- `--font-body`, `--font-display`: typography families.
- `--ink-*`, `--blue-*`, `--sky-*`: core text/accent palette.
- `--surface-*`, `--border`: background and boundary colors.
- `--shadow-*`, `--radius-*`: elevation and corner radius presets.
- `--alert-*`: alert/banner tones used by `Alert` and dialog flows.

## Typography

- Body font: IBM Plex Sans.
- Display/headings: Space Grotesk.

Fonts are loaded from Google Fonts in `frontend/index.html` to avoid render-blocking
CSS imports. Keep `display=swap` so text paints immediately.

## Alerts and dialogs

- Shared alert/dialog components live in `frontend/src/components/ui`.
- Alert colors come from `--alert-*` tokens in `frontend/src/index.css`.
- Dialogs reuse shared button tokens/styles for visual consistency.
- The shared `DialogFrame` shell portals every modal/backdrop pair to `document.body`, applies the blur/opaque backdrop from `Dialog.css`, and toggles body scroll lock while any dialog is open. Feature dialogs should attach their root styles to `.ui-dialog...` selectors so they inherit the shared layering behavior instead of creating local stacking contexts.
