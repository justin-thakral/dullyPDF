# Overview

The frontend is a React + TypeScript workspace for visualizing PDFs, editing detected field geometry, and running Search & Fill against local CSV/Excel/JSON data. It connects to the FastAPI backend for detection, OpenAI rename + schema-only mapping, and saved-form storage. CSV/Excel/JSON/TXT schema headers are uploaded, but CSV/Excel/JSON rows stay local (TXT is schema-only).

## What it does

- Loads local PDFs via PDF.js and renders pages to canvas.
- Imports existing AcroForm widgets when present.
- Calls `/detect-fields` to enqueue CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection and polls `/detect-fields/{sessionId}` for results.
- Calls `/api/renames/ai` for OpenAI field rename (PDF page images + overlay tags; schema headers are included for rename+map).
- Lets you drag, resize, rename, and retype fields.
- Maps schema columns to PDF fields using OpenAI mapping of schema headers + template tags; the UI warns users before sending headers.
- Consumes OpenAI credits per PDF page for rename or mapping (combined counts once per page).
- Runs Search & Fill to populate values from a selected local record.
- Search & Fill applies checkbox values from explicit checkbox columns (including `i_`/`checkbox_` prefixes), group enums/lists, and AI checkbox rules when available.
- Saves filled forms to your profile via the backend, including checkbox rules/hints for later Search & Fill.
- When the saved forms limit is reached, surfaces a modal that lists saved forms and allows deletions to free space before saving again; overwriting a saved form replaces it in place.
- Uses FirebaseUI for email/password + Google + GitHub login; password logins require email verification before access.
- Shows a profile view with tier limits, credits, and saved forms.
- Includes a homepage Demo flow that loads static demo PDFs/CSV and guides users through the pipeline steps.

## What it does not do

- No full PDF editing (only form fields/overlays).
- No Search & Fill from TXT-only or schema-only JSON uploads (CSV/Excel/JSON rows are required).
- No offline persistence; state is tied to the active session unless saved.

## Local fixtures

- Use `quickTestFiles/` for small, tracked demo inputs.
- Use `samples/` for large, local-only datasets.
- Demo assets served to the frontend live in `frontend/public/demo`.
