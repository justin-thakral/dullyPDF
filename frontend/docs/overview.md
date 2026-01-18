# Overview

The frontend is a React + TypeScript workspace for visualizing PDFs, editing detected field geometry, and running Search & Fill against local CSV/Excel data. It connects to the FastAPI backend for detection, OpenAI rename + schema-only mapping, and saved-form storage. CSV/Excel/TXT schema headers are uploaded, but CSV/Excel rows stay local (TXT is schema-only).

## What it does

- Loads local PDFs via PDF.js and renders pages to canvas.
- Imports existing AcroForm widgets when present.
- Calls `/detect-fields` (CommonForms detection only).
- Calls `/api/renames/ai` for OpenAI field rename (PDF page images + overlay tags; schema headers are included for rename+map).
- Lets you drag, resize, rename, and retype fields.
- Maps schema columns to PDF fields using OpenAI mapping of schema headers + template tags; the UI warns users before sending headers.
- Consumes OpenAI credits per PDF page for rename or mapping (combined counts once per page).
- Runs Search & Fill to populate values from a selected local record.
- Saves filled forms to your profile via the backend.

## What it does not do

- No full PDF editing (only form fields/overlays).
- No Search & Fill from TXT-only schema uploads (CSV/Excel rows are required).
- No offline persistence; state is tied to the active session unless saved.

## Local fixtures

- Use `quickTestFiles/` for small, tracked demo inputs.
- Use `samples/` for large, local-only datasets.
