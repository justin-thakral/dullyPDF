# Quick Test Files

This folder contains a small, tracked set of de-identified PDFs and schema files for
manual testing of the UI and backend flows. Use these for smoke tests and screenshots.

Contents:
- `new_patient_forms_1915ccb015.pdf`
- `dentalintakeform_d1c394f594.pdf`
- `cms1500_06_03d2696ed5.pdf`
- `new_patient_forms_1915ccb015_mock.csv` (sample rows for Search & Fill)
- `healthdb_vw_form_fields.csv` (schema headers for mapping)

Usage (manual):
1) Upload a PDF in the UI.
2) Connect a schema file (CSV/XLS/TXT).
3) Run rename and/or schema mapping.
4) Use Search & Fill for CSV/Excel rows.

Notes:
- CSV/Excel rows stay client-side; only headers/types are sent to the backend.
- Keep large datasets in `samples/` (ignored by git).
- Do not add PHI/PII to tracked files.
