## Project Overview

DullyPDF is a FastAPI + React app for detecting PDF form fields, renaming candidates, and editing fields in a PDF viewer. The backend (`backend/main.py` + `backend/fieldDetecting/`) runs the **CommonForms** (by [jbarrow](https://github.com/jbarrow/commonforms)) ML detector, optionally runs OpenAI rename, and supports AI schema mapping. The frontend renders PDFs with overlays and drives Search & Fill.
Main pipeline: CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection -> OpenAI rename -> OpenAI schema mapping -> UI -> Search & Fill.

## Legacy Implementations

The legacy sandbox (native/scanned OpenCV pipeline) lives in `legacy/fieldDetecting/`. It is **not** part of the main pipeline and should only be used for historical reference or debugging older outputs.

## Documentation

Read the relevant docs before changes when they apply. Start with the area README, then drill into the sub-docs as needed. If you update any features ensure that the changes are reflected in documentation.

Backend docs (main pipeline + shared utilities):
- `backend/README.md`
- `backend/fieldDetecting/README.md`
- `samples/fieldDetecting/pdfs/README.md`
- `backend/fieldDetecting/docs/README.md`
- `backend/fieldDetecting/docs/commonforms.md`
- `backend/fieldDetecting/docs/rename-flow.md`
- `backend/fieldDetecting/docs/security.md`

Legacy docs (reference only):
- `legacy/fieldDetecting/docs/README.md`
- `legacy/fieldDetecting/ML_FIELD_DETECTOR_PLAN.md`
- `legacy/fieldDetecting/docs/code-map.md`
- `legacy/fieldDetecting/docs/pipelines.md`
- `legacy/fieldDetecting/docs/running.md`
- `legacy/fieldDetecting/docs/tools.md`
- `legacy/fieldDetecting/docs/checkBoxHintArrowBox.md`
- `legacy/fieldDetecting/docs/images/README.md`

Frontend docs:
- `frontend/README.md`
- `frontend/docs/README.md`
- `frontend/docs/overview.md`
- `frontend/docs/structure.md`
- `frontend/docs/running.md`
- `frontend/docs/field-editing.md`
- `frontend/docs/styling.md`

MCP docs:
- `mcp/README.md`
- `mcp/devtools.md`

If a user wants UI-proof or screen-guided actions, follow `mcp/devtools.md` and capture evidence under `mcp/debugging/mcp-screenshots`.

## Important

Please push back against "bad ideas." If a prompt isn't a good idea or would be a weird way to implement a task, suggest against it and propose a better option. Highlight why it may be a bad idea too, and focus on what is best for the project.

You may be working with other codex terminals. Don't worry if they made changes you didn't make, I have it setup to NOT overlap with code you are using. Just understand the changes.

When you are told to test changes (via an MCP) assume that there is an existing terminal than ran npm run dev. 

You have full access to use gcloud commands with service accounts too. dev is dullypdf-dev and prod is dullypdf.

Mobile version disables the dullyPDF ui and main pipeline. The layout activates at 900px and it meant as a landing page to describe concepts behind dullyPDF only.

## Commenting Structure

Never use emojis. Write descriptive comments that explain approaches or non-obvious logic in English, helping someone quickly analyze the strategy. Call out key data structures and algorithms when they are important to understanding the flow. Anyone with strong programming fundamentals should be able to understand what is going on from these comments even if they are not too familiar with the specific language. Make sure you mention time complexity too, don't mention it if it's obvious and explicit, just for a complex workflow or algorithm where it be helpful to know. 

## Code Cleaning

Sometimes we have unused, unnecessary, or duplicated aspects of code. If you see one of these when you are attempting an unrelated task, point it out at the end and ask if I would like it fixed.

## Code Optimizing

If you see multiple chunks of code that are following the same process, try to condense them by calling the same function or using another structured solution.

Also, sometimes your changes may lead to a file being too large out of place etc. If you believe that your changes let to this, suggest a refactor that can keep the
repo following good repo structure. Furthermore, if you see any existing implementations that should be refactored, including files in the wrong dir, splitting up dirs into multiple,
files being too large, files out of place, files doing too many things, just output that and let me know like hey heres a suggested refactor. You shouldn't do these refactors just let me know.
