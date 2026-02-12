# Debugger Guide (Codex + MCP)

This document teaches a Codex terminal how to act as a disciplined debugger for DullyPDF.
It focuses on reproducible UI/API workflows, evidence capture, and safe handling of accounts.

## Scope

- Use the dev environment by default.
- Use MCP tools for UI automation and API validation.
- Capture proof (screenshots, logs, network evidence) for every issue.

## Prerequisites

- Backend and frontend are running locally.
- MCP server is configured as described in `mcp/README.md`.
- Chrome remote debugging is available per `mcp/devtools.md`.
- Test credentials live in `mcp/.env.local` (git-ignored).

## Safety rails

- Keep prod read-only by default.
- Only enable mutating calls if explicitly approved (`DULLY_MCP_ALLOW_WRITE=1`).
- Use synthetic data and local PDFs unless asked otherwise.
- Never log secrets or access tokens.

## Baseline test data

- PDF: `quickTestFiles/new_patient_forms_1915ccb015.pdf`
- CSV: `quickTestFiles/healthdb_vw_form_fields.csv`

Always note which PDF/CSV you used in the final report.

## Standard UI smoke flow

Run this end-to-end to validate the primary workflow.

1. Open the UI and sign in with the configured user.
2. Upload the baseline PDF for detection.
3. Wait for field detection to complete (fields list populates).
4. Connect the baseline CSV from the Database menu.
5. Click "Map Schema" and wait for a success toast.
6. Open "Search, Fill & Clear", search a known record (e.g., `MRN100001`), and fill.
7. Confirm field inputs are populated and the overlay reflects values.

Expected signals:
- Network: `/detect-fields`, `/api/schemas`, and `/api/schema-mappings/ai` return 200.
- UI: "Mapped" state appears and search results render.

## API checks (non-UI)

Use the MCP API tool to sanity-check endpoints:

- With auth: verify key endpoints return 200.
- Without auth: verify protected endpoints return 401/403.
- Record status codes and response messages for any mismatch.

Keep calls read-only unless explicitly approved.

## Evidence capture

Always capture proof when an issue occurs.

- Screenshots: `mcp/debugging/mcp-screenshots/`
- Console errors: capture message text and time.
- Network details: record endpoint, status, and response body when possible.

If you trigger dialogs, handle them so the page does not block.

## Bug classification and logging

Every bug found must be recorded as a markdown report. Choose one of these classifications:

1. Easy fix and obvious solution. Implement the fix and record it.
2. Hard fix or unclear solution. Record the bug and list ideas.
3. Easy fix but needs feedback. Record the bug and ask for guidance before changing.

Bug scope includes UI mutations, visual/UI issues, and pipeline flow regressions. Examples:

- Unexpected UI state changes (fields overwritten, toggles flip, data clears).
- Layout or interaction bugs (overlays misaligned, inputs unusable, buttons stuck).
- Pipeline flow errors (detect -> map -> search/fill breaks, wrong step ordering).
- Data issues (mapping mismatch, bad field names, incorrect confidence labels).

Where to write reports:

- Type 1: `mcp/codexBugs/fixed/`
- Types 2 and 3: `mcp/codexBugs/notfixedSuggestions/`

After fixing a Type 1 bug, continue the debug flow.
For Types 2 and 3, continue unless the bug blocks the core workflow.

## Bug report template

Use this template for every bug report:

```
# Bug: <short title>

## Classification
- Type: <1|2|3>
- Category: <ui-mutation|ui-issue|pipeline-flow|data|auth|other>

## Context
- Environment: dev/prod
- User: <email or role>
- PDF: <path or name>
- CSV: <path or name>
- Time: <ISO 8601>

## Steps to reproduce
1. ...
2. ...

## Expected
...

## Actual
...

## Evidence
- Screenshot: <path>
- Console: <message>
- Network: <method> <url> <status>

## Suggested fix
- ...

## Status
- Fixed: yes/no
- Notes: <summary or follow-up needed>
```

## Session master report

At the end of each session, write a master report that lists every bug report created.
Save it to `mcp/codexBugs/logs/` and include links to each bug markdown.
If no bugs were found, create a log that states "No bugs found" and note the run context.

Suggested filename: `session-YYYYMMDD-HHMM.md`.

Cleanup:

```
python3 mcp/codexBugs/logs/cleanOutput.py --sessions
```

Or run `python3 clean.py --mcp-bug-logs` from the repo root. Add `--dry-run` to preview.

## Reporting template

- Context: environment, PDF/CSV used, user account, time.
- Steps: exact reproduction steps.
- Expected vs actual: concise mismatch summary.
- Evidence: screenshots/logs/network snippets.
- Notes: any suspected root cause or related files.

## Long-running runs (recommended pattern)

Do not keep a single browser context open for 24 hours.
Instead, run short sessions on a schedule and restart the page each time.
This avoids drift, stale auth, and memory leaks.

## Stop conditions

Stop and ask for guidance if:

- You discover sensitive data exposure.
- A change would require destructive actions in prod.
- The backend is down or returns repeated 5xx errors.

# file cleanup
If a bug from type 2 or 3 is found and then fixed, move it into fixed dir
