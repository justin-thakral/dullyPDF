# Field Editing Guide

Field editing happens in two modes:
- **Overlay mode** (Fields toggle): drag/resize boxes on the PDF.
- **Input mode** (Info toggle): enter values aligned to each field.

## Creating fields

Use the "Add" buttons in the Fields panel to create text, date, signature, or checkbox fields. New fields are centered on the current page with a sensible default size.

## Loading existing fields

When a PDF contains AcroForm widgets, the editor automatically imports them on upload. Imported fields can be moved, resized, and renamed like any other field.

## Selecting fields

- Click a field in the overlay to select it.
- Click a field in the Fields list to focus it in the inspector.
- The list can show **All** pages or just the current page.

## Moving and resizing

- Drag a field box to move it.
- Drag the bottom-right handle to resize it.
- The overlay clamps fields to the page bounds.

## Inspector inputs

The inspector lets you edit:

- Name
- Type
- Page assignment
- X / Y position
- Width / Height

Coordinates are in PDF points and measured from the top-left of the page.

## Confidence labels

Detection and renaming confidence are shown in the list:
- Field confidence comes from CommonForms detection.
- Name confidence comes from OpenAI rename or schema mapping.

## OpenAI guardrails

OpenAI rename and mapping require explicit confirmation before sending data to OpenAI.
Rename sends PDF pages + overlay tags; mapping sends schema headers + field tags. When
rename+map is selected, both are sent in one request. No CSV row data or field values
are sent. The UI warns users before sending PDF pages or schema headers.

## Input mode

When **Info** is enabled:
- Text/date fields render as aligned inputs.
- Checkbox fields render as checkboxes.
- Use **Clear** to reset all values on the current session.
