# Overview

Sandbox UI is a standalone React + TypeScript app for visualizing PDFs and editing form-field geometry. It connects to the sandbox Python backend for field detection and remains a light-weight workspace for iterating on placement and naming.

## What it does

- Loads a local PDF using PDF.js.
- Renders one page at a time on a canvas.
- Detects existing AcroForm fields when present and displays them as overlays.
- Calls the sandbox `/detect-fields` API to fetch candidate fields and confidence metadata.
- Displays form-field overlays with drag and resize support.
- Lets you edit names, types, page assignment, and sizes in a side panel.

## What it does not do

- No external PDF SDK dependencies.
- No persisted storage (state is in-memory only).
