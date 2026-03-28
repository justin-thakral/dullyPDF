# Phase 1: Email OTP Signer Verification

Status: [x] Implemented

## Why this phase exists

Today the signer ceremony proves possession of the signing link, not strong control of the intended signer identity. Email OTP is the lowest-friction improvement that materially raises assurance without forcing a full account system on recipients.

## Goals

- Require a one-time email verification step before signer actions continue.
- Preserve the no-account public signing experience.
- Record verification evidence in the audit trail.

## Scope

Backend:
- Create OTP challenge issuance and verification endpoints for public signing.
- Bind the verified challenge to the active signing session.
- Enforce verification before review or completion.
- Rate limit challenge creation and verification attempts separately from general action limits.

Frontend:
- Add a verification step to `/sign/:token`.
- Show challenge send, code entry, resend cooldown, and expiry states.
- Make verification state visible to the signer before the ceremony proceeds.

Persistence and audit:
- Store challenge metadata with minimal retention.
- Record audit events for `verification_started`, `verification_passed`, `verification_failed`, and `verification_resent`.
- Include verification method and verification timestamp in the sealed audit manifest.

## Recommended design

- Verification method: email OTP only.
- Challenge target: `signer_email` already stored on the request.
- Challenge lifetime: short, for example 10 to 15 minutes.
- Attempt limits: low per session and per IP.
- Challenge secret storage: store only a hash of the OTP, never the raw code.

## Non-goals

- Do not add SMS OTP in this phase.
- Do not add external identity proofing.
- Do not force the signer to create a DullyPDF account.

## Likely files

- `backend/api/routes/signing_public.py`
- `backend/firebaseDB/signing_database.py`
- `backend/services/signing_service.py`
- `backend/services/signing_invite_service.py`
- `backend/services/signing_audit_service.py`
- `frontend/src/components/pages/PublicSigningPage.tsx`
- `frontend/src/services/api.ts`

## Suggested data additions

Request-level:
- `verification_required`
- `verification_method`
- `verification_completed_at`

Session-level or challenge-level:
- `challenge_id`
- `challenge_hash`
- `challenge_sent_at`
- `challenge_expires_at`
- `verified_at`
- `attempt_count`

## Acceptance criteria

- A signer cannot review or sign until the OTP challenge is completed.
- OTP challenges expire and cannot be replayed after use.
- Excess challenge or verification attempts are rate limited.
- The final audit manifest records that email OTP verification occurred.

## Verification

- Backend unit tests for challenge issuance, expiry, replay rejection, and failed-attempt throttling.
- Integration test covering `bootstrap -> verify -> review -> adopt -> complete`.
- Frontend unit tests for OTP step states.
- Playwright smoke covering the happy path and expired-code path.

## Open questions

- OTP scope is now configurable through `SIGNING_VERIFICATION_SOURCE_TYPES`, with the default covering every current emailed signing source (`workspace`, `fill_link_response`, and `uploaded_pdf`). Revisit only if product needs category- or tenant-level exceptions.
- Should session IP or user-agent drift after verification force re-verification?
