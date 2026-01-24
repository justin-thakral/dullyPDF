# Production Usage Guide (MCP Debugger + Security)

This guide explains how to use the MCP Chrome DevTools workflow in production while
honoring the backend security controls. It is meant to be used alongside:
- `mcp/debugger.md`
- `backend/fieldDetecting/docs/security.md`

## Goals

- Validate the deployed workflow end-to-end in the real environment.
- Confirm auth, CORS, rate limits, and session handling behave correctly.
- Capture evidence for any issues without exposing sensitive data.

## Safety Rules (Prod)

- Treat prod as read-only by default.
- Only enable mutations when explicitly approved (`DULLY_MCP_ALLOW_WRITE=1`).
- Use synthetic data and non-sensitive PDFs/CSVs.
- Never paste or log secrets, admin tokens, or user tokens.
- Stop immediately if sensitive data exposure is suspected.

## Preconditions

- Cloud Run service is deployed for `dullypdf` and reachable.
- Firebase Hosting is configured and the domain is added to Auth allowed domains.
- A test Firebase user is available for prod (least privilege).
- Session TTL is enabled in Firestore (`session_cache.expires_at`).
- GCS lifecycle rule is active for `sessions/` objects in the session bucket.

## How to Use MCP in Prod

### 1) UI Smoke Flow (Read-Only)

Follow `mcp/debugger.md` but keep the flow as non-destructive:

- Sign in with a test user.
- Upload a small synthetic PDF for detection.
- Verify detected fields render.
- If schema mapping is needed, use synthetic CSV headers only.
- Do not save templates or forms unless explicitly approved.

Evidence capture:
- Screenshots in `mcp/debugging/mcp-screenshots/`.
- Record network results for `/detect-fields`, `/api/renames/ai`, `/api/schema-mappings/ai`.

### 2) API Sanity Checks (Read-Only)

- Without auth: protected endpoints return 401/403.
- With auth: endpoints return 200 for the test user.
- Confirm CORS blocks disallowed origins.

### 3) Session Resilience Check

- Run detect -> rename -> mapping.
- Restart the backend instance (or wait for scale down).
- Re-run a read call with the same `sessionId` and confirm it still works.

## Production Security Verification

Check the following in prod:

- `SANDBOX_CORS_ORIGINS` is locked to the Hosting domain.
- `SANDBOX_LOG_OPENAI_RESPONSE=false`.
- `ADMIN_TOKEN` exists only in Secret Manager; not in frontend env.
- Buckets are private and accessed only by the backend runtime SA.
- Firestore TTL is enabled for `session_cache.expires_at`.
- GCS lifecycle deletes `sessions/` objects after the chosen TTL.
- Rate limit backend is Firestore and returns 429 when exceeded.

## When to Stop

Stop and ask for guidance if:

- Any sensitive data is exposed.
- Auth/role checks fail in a way that grants extra access.
- Backend returns repeated 5xx errors.

## Reporting

Use the bug report template in `mcp/debugger.md` and write a master session log
in `mcp/codexBugs/logs/` even if no bugs are found.
