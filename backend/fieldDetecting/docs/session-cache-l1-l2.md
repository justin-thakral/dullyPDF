# L1/L2 Session Cache Guide

This guide explains how the backend session cache is structured with an in-process cache
(L1) and a shared store (L2). It covers what data belongs in each layer, why the split
matters, and which files implement the design.

## Goals

- Keep the server as the source of truth for session data.
- Survive instance restarts, autoscaling, and traffic shifting.
- Avoid re-running detection or re-uploading PDFs for follow-on requests.
- Bound retention of sensitive PDFs and derived data.

Non-goals:
- Long-term persistence of session data (sessions are short-lived by design).
- Client-side storage as an authoritative data source.

## Current Behavior (L1 + L2)

The backend uses an in-memory LRU cache (L1) with a Firestore/GCS-backed store (L2)
implemented in `backend/sessions/session_store.py`:

- L1 stores PDF bytes, detected fields, and related session data.
- L1 entries expire by TTL (`SANDBOX_SESSION_TTL_SECONDS`) and LRU eviction.
- L2 persists session metadata in Firestore and artifacts in GCS so sessions survive
  instance restarts or autoscaling.

## Design Summary

Use two layers:

- L1: In-process memory cache for speed and reduced latency.
- L2: Shared store for resilience and multi-instance access.
  - Firestore for session metadata and pointers.
  - GCS for large artifacts (PDF bytes, large JSON payloads).

The backend continues to accept only a `sessionId` from the client. The client does not
send session contents back to the server.

Long-lived editor sessions should call `POST /api/sessions/{sessionId}/touch` roughly
once per minute to refresh `last_access_at` and `expires_at`, so scheduled cleanup does
not delete active sessions.

## What Lives in L1 (In-Process Cache)

L1 is optimized for speed and should contain everything needed to satisfy a request
without hitting external services.

L1 fields:

- `pdf_bytes`: raw PDF bytes for rename, download, and page counting.
- `fields`: detected or renamed fields for UI and downstream calls.
- `result`: full detection result payload.
- `source_pdf`: original filename (safe for download headers).
- `user_id`: owner of the session (from Firebase auth).
- `renames`: OpenAI rename report.
- `checkboxRules`: rename checkbox hints.
- `openai_credit_consumed`: prevents double charging on rename + mapping.
- `openai_credit_pages`: page count used for credits.
- `page_count`: page count derived from the source PDF.
- `openai_credit_mapping_used`: ensures mapping does not charge twice.
- `created_at`, `last_access`: for TTL sweeps and LRU.
- `detection_status`, `detection_error`: detector job status metadata (when present).

Rationale:
- L1 is the only place where raw PDF bytes should live in memory for fast access.
- Derived data is used across multiple endpoints and should be readily available.

## What Lives in L2 (Shared Store)

L2 is the authoritative store when L1 is empty.

### Firestore session document

Keep the Firestore document small and stable. Store metadata and pointers.

Stored fields:

- `session_id`: stable identifier (document id or explicit field).
- `user_id`: required for ownership checks.
- `created_at`: timestamp.
- `last_access_at`: timestamp (optional, use sparingly to reduce writes).
- `expires_at`: timestamp used by Firestore TTL.
- `source_pdf`: original filename.
- `page_count`: page count for credits.
- `pdf_path`: GCS path for the PDF bytes.
- `fields_path`: GCS path for detected or renamed fields JSON.
- `result_path`: GCS path for the full detection result JSON.
- `renames_path`: GCS path for rename report JSON (if present).
- `checkbox_rules_path`: GCS path for checkbox rules JSON (if present).
- `openai_credit_consumed`, `openai_credit_pages`, `openai_credit_mapping_used`.
- `version`: schema version for future migrations.
- `detection_status`, `detection_error`, `detection_queued_at`, `detection_started_at`,
  `detection_completed_at`, `detection_task_name`.

Firestore limit note:
- A Firestore document has a 1 MiB size limit. Large PDFs and large field lists
  should never be embedded directly in Firestore.

### GCS objects

Store large artifacts in GCS with a short retention policy.

Suggested object layout:

- `sessions/<session_id>/source.pdf`
- `sessions/<session_id>/fields.json`
- `sessions/<session_id>/result.json`
- `sessions/<session_id>/renames.json`
- `sessions/<session_id>/checkbox-rules.json`

GCS retention:
- Use a scheduled cleanup job to delete objects after the session TTL.
- Keep buckets private; use the Admin SDK only.

## Read and Write Flows

### Detect fields

1) Main API writes PDF bytes to GCS and creates a Firestore session doc with
   `detection_status=queued`.
2) Cloud Tasks dispatches the job to the detector service.
3) Detector downloads the PDF, runs CommonForms, and writes fields/result JSON to GCS.
4) Detector updates the Firestore session doc with `detection_status=complete`.
5) L1 is populated lazily when clients request the session after completion.

### Rename fields

1) Read session from L1. If missing, read Firestore + GCS.
2) Use PDF bytes and fields for OpenAI rename.
3) Update L1 with `renames`, `checkboxRules`, and credit flags.
4) Update Firestore metadata and GCS JSON artifacts.

### Schema mapping

1) Read session (L1 then L2) only if `sessionId` is provided.
2) Use credit flags to prevent double charging.
3) Update credit flags in L1 and Firestore if needed.

### Download session PDF

1) Read session (L1 then L2).
2) If L1 has `pdf_bytes`, stream from memory.
3) Otherwise stream from GCS using `pdf_path`.

## TTL and Eviction Strategy

- L1: TTL + LRU eviction already exists.
- L2: Firestore TTL based on `expires_at` (deletes metadata) plus a scheduled
  cleanup job to delete session artifacts in GCS after the same TTL.

Notes:
- Firestore TTL deletion is not immediate; expect a delay.
- Do not update `last_access_at` on every request unless needed. Consider a
  throttle (for example, update at most once every 5 to 10 minutes) to reduce
  write costs.
- L2 access updates are throttled via `SANDBOX_SESSION_L2_TOUCH_SECONDS`.
- The scheduled job should run `scripts/cleanup_sessions.py --execute` with the
  same env used by the backend (access to Firestore + GCS).

## Why This Split Is Necessary

- Reliability: L2 survives instance restarts and autoscaling.
- Security: The server remains the source of truth; the client does not send
  session contents back to the server.
- Performance: L1 avoids GCS and Firestore round trips on hot sessions.
- Cost control: Large payloads live in GCS, not Firestore.

## Implementation Files (Responsibilities)

- `backend/sessions/session_store.py`
  - Owns L1 cache (LRU + TTL) and L2 integration.
  - Exposes `get_session_entry`, `store_session_entry`, and `update_session_entry`.

- `backend/firebaseDB/session_database.py`
  - Firestore CRUD for session metadata.
  - Stores session metadata in the `session_cache` collection.

- `backend/firebaseDB/storage_service.py`
  - Add helpers for session artifacts:
    - `upload_session_pdf_bytes`, `download_pdf_bytes`
    - `upload_session_json`, `download_session_json`

- `backend/main.py`
  - Uses the session store API for session reads/writes.
  - Keep request handlers unchanged from the client perspective.

- `config/backend.*.env.example`
  - Optional `SANDBOX_SESSION_BUCKET` (or `SESSION_BUCKET`) for a dedicated bucket.
  - Keep existing `SANDBOX_SESSION_TTL_SECONDS` for TTL coordination.
  - `SANDBOX_SESSION_L2_TOUCH_SECONDS` throttles L2 access updates.

Bucket choice:
- Option A: reuse `FORMS_BUCKET` with a `sessions/` prefix and a scheduled cleanup job.
- Option B: add a dedicated session bucket for stricter retention control.

## Minimal Session Payload Contract

Clients should only send:

- `sessionId`

All other session data must be resolved server-side from L1 or L2.

## Failure Modes and Recovery

- If a session is missing in L1 and L2, return `404` and require re-upload.
- If the PDF object is missing in GCS, return `404` and require re-upload.
- If ownership does not match, return `403`.

## Testing Checklist

- Detect -> rename -> mapping works after restarting the backend.
- Detect -> rename works after scaling to multiple instances.
- Downloads stream from GCS when L1 is empty.
- Firestore TTL and scheduled cleanup remove session data on schedule.

## Appendix: L1 OrderedDict Layout (Mock Example)

The L1 cache is keyed by `sessionId`, not `userId`. Ownership is enforced by checking
the `user_id` stored inside each session entry.

LRU order is left (oldest) to right (most recent):

```
_API_SESSION_CACHE (OrderedDict)
LRU -> MRU

[sessionId: "s-101"] -> { user_id: "user_a", pdf_bytes: ..., fields: ... }
[sessionId: "s-502"] -> { user_id: "user_b", pdf_bytes: ..., fields: ... }
[sessionId: "s-309"] -> { user_id: "user_c", pdf_bytes: ..., fields: ... }
```

Notes:
- If `user_b` requests `sessionId="s-309"`, access is denied because the `user_id`
  stored in the entry does not match.
- When an entry is accessed, it is moved to the MRU position.
