# Legacy checkbox callout overlay (arrow + box)

This documents the previous checkbox overlay style used by the OpenAI rename flow.
The current default is a centered checkbox tag with no background box.

## Legacy behavior

- Checkbox IDs were rendered inside a small purple callout box with a white fill.
- A purple arrow connected the checkbox center to the callout box edge.
- The callout was placed to the right of the checkbox unless it would overflow,
  then it was placed to the left.
- Text used a fixed font scale (1.6) with padding (9px) for readability.

## Legacy implementation locations

- `backend/fieldDetecting/sandbox/combinedSrc/field_overlay.py`
  - `_draw_checkbox_callout(...)` drew the white box + arrow.
  - `draw_overlay(..., checkbox_callout_arrow_scale=...)` controlled arrow thickness.
  - The callout was used when `field_labels_inside=True` and `type == "checkbox"`.
- `backend/fieldDetecting/sandbox/combinedSrc/rename_resolver.py`
  - `_build_prompt(...)` described the checkbox callout in the system message.
  - `run_openai_rename_pipeline(...)` passed `checkbox_callout_arrow_scale=6.0`.

## How to revert

1) Restore the callout renderer in `backend/fieldDetecting/sandbox/combinedSrc/field_overlay.py`.
   - Reintroduce `_draw_checkbox_callout(...)` (white-filled box + arrow).
   - Replace `_draw_checkbox_tag(...)` usage with `_draw_checkbox_callout(...)`.
   - Rename the draw_overlay parameter back to `checkbox_callout_arrow_scale`.
   - Pass `image_width_px` and `image_height_px` to the callout function for placement.

2) Update the OpenAI prompt in `backend/fieldDetecting/sandbox/combinedSrc/rename_resolver.py`.
   - Restore the line: "Checkbox fields: the ID is shown in a small purple callout connected to the checkbox square."
   - Adjust the checkbox hint docstring in `_attach_checkbox_label_hints(...)` to mention the callout.

3) Restore the pipeline wiring in `backend/fieldDetecting/sandbox/combinedSrc/rename_resolver.py`.
   - Pass `checkbox_callout_arrow_scale=6.0` to `draw_overlay(...)`.

4) Update docs to match.
   - In `backend/fieldDetecting/docs/rename-flow.md`, describe the callout box + arrow.

## Notes

- The callout box intentionally overlays the PDF to keep IDs legible. If you revert,
  consider whether the white fill will obscure nearby content on dense forms.
