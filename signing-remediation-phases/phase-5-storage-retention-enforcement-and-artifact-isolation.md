# Phase 5: Storage Retention Enforcement And Artifact Isolation

Status: [x] Implemented

## Why this phase exists

The application currently computes `retentionUntil`, but the repo code alone does not prove that finalized artifacts are protected by storage-level retention controls. This phase turns retention from advisory metadata into enforceable storage behavior.

## Goals

- Require a dedicated signing bucket for finalized signing artifacts.
- Enforce or validate storage-level retention behavior for completed artifacts.
- Preserve best-effort cleanup for stale in-flight uploads without weakening finalized-record retention.

## Scope

Runtime and config:
- Remove the signing bucket fallback to generic session/forms storage.
- Fail startup or signing-route enablement when the dedicated signing bucket is missing in environments that enable signing.

Storage architecture:
- Separate staging uploads from finalized retained artifacts.
- Ensure finalized source PDF, signed PDF, audit manifest, and audit receipt are written to a retention-controlled location.

Infrastructure validation:
- Add startup or deploy validation that checks required storage expectations.
- Document the required bucket policies and IAM roles.

## Recommended design

Use two logical storage tiers:

Staging tier:
- short-lived
- allows deletion for stale completion races
- used only before final request completion succeeds

Final retention tier:
- dedicated signing bucket or finalized prefix
- retention policy enabled
- least-privilege write access
- deletion blocked until retention period ends

## Implemented design

- Finalized signing artifacts now require the dedicated `SIGNING_BUCKET`; the old fallback to session/forms storage was removed for finalized signing writes.
- Short-lived signing uploads stage under `SIGNING_STAGING_BUCKET` when configured, otherwise the existing session bucket (or `FORMS_BUCKET`) acts as the temporary tier.
- Owner send, Fill By Link auto-send, and public completion now upload into staging first, persist the final `gs://` path on the request, and then promote staged blobs into the finalized signing bucket.
- Public and owner download/read paths can recover from a failed promotion by deriving the deterministic staging object path, retrying promotion, and only then serving the staging object as a temporary fallback.
- Finalized artifact retention is validated via `scripts/validate-signing-storage.py`, which requires either a bucket retention policy covering `SIGNING_RETENTION_DAYS` or object-retention mode on `SIGNING_BUCKET`.
- Signing request retention metadata is now populated when the immutable source PDF is first sent so source PDFs and later completion artifacts share one retention window in the request record and audit bundle.
- The repo now includes `scripts/lock-signing-storage-retention.sh` as a manual ops helper for teams that decide to make the bucket retention policy immutable after separate approval. The lock step is intentionally not part of deploy preflight because it is irreversible.

## Non-goals

- Do not move unrelated form/session storage in this phase.
- Do not redesign the public artifact download API unless required by bucket layout changes.

## Likely files

- `backend/firebaseDB/storage_service.py`
- `backend/services/signing_service.py`
- `backend/api/routes/signing.py`
- `backend/api/routes/signing_public.py`
- `backend/README.md`
- deploy and env validation scripts under `scripts/` and `config/`

## Acceptance criteria

- Signing requires a dedicated finalized signing bucket in the environments where signing is enabled.
- Completed artifacts are written to a retention-controlled location.
- Stale completion cleanup still works against staging artifacts.
- Deploy or startup checks fail when required retention settings are missing.

## Verification

- Unit tests for runtime config validation and bucket selection.
- Integration tests for stale completion cleanup against staging artifacts.
- Infra validation test or script output proving the required bucket policy is present.
- Manual prod-like verification of artifact paths and retention metadata.

## Open questions

- Should final retention use a separate bucket or a separate prefix with bucket-wide retention rules?
- Do you want object versioning or legal holds in addition to the current retention policy?
