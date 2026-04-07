openAI_overlays_exmaple
OpenAI Rename Payload Dump
Source PDF: new_patient_forms_1915ccb015.pdf
DPI: 500
Confidence profile: commonforms

For each page, OpenAI receives:
  1. system_prompt.txt - system message (same for all pages)
  2. page_N_user_prompt.txt - user message with field list
  3. page_N_clean.jpg - clean page image (detail=low)
  4. page_N_overlay.png - overlay with field IDs (detail=high)
  5. page_N_prev_crop.jpg - previous page bottom crop (if applicable, detail=low)

Supporting data:
  - page_N_overlay_fields.json - field objects with labelHintText
  - page_N_candidates.json - OCR labels, line/box/checkbox candidates
  - page_N_payload_meta.json - image profiles, sizes, overlay ID map
