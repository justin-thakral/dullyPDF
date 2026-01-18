# Styling Notes

The UI mirrors the main app color direction: deep navy foundations with bright blue accents, set against neutral light surfaces.

## Theme tokens

Defined in `frontend/src/index.css`:

- `--ink-*`: Base text colors.
- `--blue-*` and `--sky-*`: Accent colors.
- `--surface-*`: Panel and canvas surfaces.
- `--shadow-*`: Shadow presets.

## Typography

- Body: IBM Plex Sans.
- Headings: Space Grotesk.

Both fonts are loaded from Google Fonts in `frontend/src/index.css`.

## Alerts and dialogs

- Shared alert + dialog UI lives in `frontend/src/components/ui`.
- Alert tones and backgrounds are controlled via `--alert-*` tokens in `frontend/src/index.css` and should stay aligned with the navy/blue palette.
- Dialogs reuse `ui-button` styles and the same surface/ink tokens for consistent presentation.
