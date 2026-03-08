# Field Editing Guide

Field editing is centered around three coordinated areas: overlay (PDF), field list, and inspector.

## Display modes and toggles

- `Display mode` presets:
  - `Review`: overlays + names
  - `Edit`: overlays + transform resize controls (default when a form opens)
  - `Fill`: interactive input controls
- `Transform`: enables resize handles for geometry editing.
- `Fields`: show/hide overlay boxes.
- `Names`: show/hide overlay labels.
- `Info`: show/hide input controls on the PDF for entering values.
- `Transform` and `Info` are mutually exclusive to avoid drag/edit conflicts (enabling one disables the other).
- `All`: list fields from all pages in the left panel.
- `Clear`: clear current field values in the session.

## Creating and selecting fields

- Use inspector create tools (`Text`, `Date`, `Signature`, `Checkbox`) to draw fields directly on the PDF.
- New fields are added to the current page.
- Press `Esc` to exit an active create tool.
- Select fields from the overlay or the left field list.
- Selecting a field in the list can jump pages when needed.
- If the selected field is outside active list filters, the panel shows a `Reveal selected` action.

## Moving, resizing, and geometry

- Move is enabled whenever `Info` is off.
- Transform mode controls resize handles.
- Drag a field to move it.
- Drag corner or edge handles to resize standard fields.
- Corner resizing defaults to standard freeform behavior (width and height change independently).
- Hold `Shift` while corner-resizing to preserve aspect ratio for that drag.
- Standard fields expose four corners (`TL`, `TR`, `BL`, `BR`) plus edge handles (`left`, `right`, `top`, `bottom`).
- Small fields (for example tiny checkboxes) use a single bottom-right handle and a larger move hit area.
- Geometry is clamped to page bounds with a minimum size.
- Inspector geometry inputs edit `x`, `y`, `width`, and `height` directly.
- Coordinates are PDF points measured from the page top-left.

## Inspector editing

- Rename fields and change type/page assignment.
- Delete the selected field.
- Undo/redo field edits with keyboard shortcuts (history depth: 10 snapshots).

## Confidence labels

- The field list supports high/medium/low confidence filtering.
- Tier thresholds are:
  - high: `>= 0.60`
  - medium: `>= 0.30` and `< 0.60`
  - low: `< 0.30`
- Field confidence (`fieldConfidence`) comes from detection, or from OpenAI rename `isItAfieldConfidence` when available.
- Name confidence comes from OpenAI rename (`renameConfidence`) and/or schema alignment (`mappingConfidence`).
- Filtering primarily uses field confidence tiers.
- The list header shows `visible / in-scope` counts and overall total for faster filter-state checks.

## OpenAI guardrails

- Rename, Map, and Rename+Map require explicit confirmation dialogs.
- The dialogs warn users before sending PDF/schema content to OpenAI.
- Row data and field input values are not included in OpenAI rename/map requests.
- Header action buttons now expose inline prerequisite hints when disabled (for example missing schema source for mapping).

## Search & Fill transform rules

- Search & Fill prefers direct mapped column values first.
- When a direct value is not available, it can apply deterministic `textTransformRules` emitted by schema mapping.
- Supported transform operations are:
  - `copy`
  - `concat`
  - `split_name_first_rest`
  - `split_delimiter`
- Transform rules are persisted with saved forms so the same split/join behavior replays on reload.

## Keyboard shortcuts

- `Ctrl/Cmd+Z`: undo
- `Ctrl/Cmd+Shift+Z` or `Ctrl/Cmd+Y`: redo
- `Ctrl/Cmd+X`, `Delete`, or `Backspace`: delete selected field
- `T` / `D` / `S` / `C`: set active create tool (`Text` / `Date` / `Signature` / `Checkbox`)
- `Esc`: clear active create tool
- `Ctrl/Cmd+F` or `/`: focus field search
- `[` and `]`: previous/next page
- `Alt+Arrow`: nudge selected field by 1 point
- `Shift+Alt+Arrow`: nudge selected field by 10 points
- `Ctrl/Cmd+0`: reset zoom to 100%
- `Shift` (while corner-dragging): temporary aspect-ratio lock
