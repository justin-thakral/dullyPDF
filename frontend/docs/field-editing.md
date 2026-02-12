# Field Editing Guide

Field editing is centered around three coordinated areas: overlay (PDF), field list, and inspector.

## Display modes and toggles

- `Fields`: show/hide overlay boxes.
- `Names`: show/hide overlay labels.
- `Info`: show/hide input controls on the PDF for entering values.
- `All`: list fields from all pages in the left panel.
- `Clear`: clear current field values in the session.

## Creating and selecting fields

- Use inspector "Add" buttons to create `text`, `date`, `signature`, and `checkbox` fields.
- New fields are added to the current page.
- Select fields from the overlay or the left field list.
- Selecting a field in the list can jump pages when needed.

## Moving, resizing, and geometry

- Drag a field to move it.
- Drag edge/corner handles to resize.
- Geometry is clamped to page bounds with a minimum size.
- Inspector geometry inputs edit `x`, `y`, `width`, and `height` directly.
- Coordinates are PDF points measured from the page top-left.

## Inspector editing

- Rename fields and change type/page assignment.
- Delete the selected field.
- Undo/redo field edits (history depth: 10 snapshots).

## Confidence labels

- The field list supports high/medium/low confidence filtering.
- Detection confidence comes from CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)).
- Name confidence comes from OpenAI rename and/or schema mapping output.

## OpenAI guardrails

- Rename, Map, and Rename+Map require explicit confirmation dialogs.
- The dialogs warn users before sending PDF/schema content to OpenAI.
- Row data and field input values are not included in OpenAI rename/map requests.

## Keyboard shortcuts

- `Ctrl/Cmd+Z`: undo
- `Ctrl/Cmd+Shift+Z` or `Ctrl/Cmd+Y`: redo
- `Ctrl/Cmd+X`: delete selected field
