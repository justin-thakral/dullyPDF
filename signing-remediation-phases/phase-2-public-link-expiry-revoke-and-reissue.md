# Phase 2: Public Link Expiry, Revoke, And Reissue

Status: [x] Completed

## Why this phase exists

Public signing links are currently bearer URLs without request-level expiry or owner-driven revocation. That is workable for low-risk links but too loose for a signature workflow that may carry sensitive records and long-lived signed artifacts.

## Goals

- Add request-level public link expiry.
- Allow owners to revoke a sent link immediately.
- Allow owners to reissue a fresh link without recreating the entire signing request.
- Separate ceremony access from long-lived artifact access where useful.

## Scope

Backend:
- Extend the signing request model with link status and expiry metadata.
- Reject bootstrap and artifact access when a public link is expired or revoked.
- Add owner routes for revoke and reissue.
- Change token generation so reissued links invalidate previous tokens.

Frontend:
- Add owner controls in the signing responses UI for revoke and reissue.
- Show clear status labels such as `active`, `expired`, `revoked`, and `reissued`.
- Surface a copyable replacement link after reissue.

Audit:
- Record `link_revoked` and `link_reissued` events.
- Include the active token version or public link nonce in the audit manifest for completed requests.

## Recommended design

- Keep the existing HMAC token shape, but include a token version or nonce stored on the request.
- Add `public_link_expires_at`.
- Add `public_link_revoked_at`.
- Add `public_link_version`.
- Default expiry should be finite, for example 7 to 30 days depending on product policy.

Optional extension:
- Use short-lived artifact download tokens after completion instead of the same public request token.

## Non-goals

- Do not replace the public ceremony with authenticated signer accounts in this phase.
- Do not redesign the signed artifact format in this phase.

## Likely files

- `backend/services/signing_service.py`
- `backend/firebaseDB/signing_database.py`
- `backend/api/routes/signing.py`
- `backend/api/routes/signing_public.py`
- `frontend/src/services/api.ts`
- `frontend/src/components/features/SigningResponsesPanel.tsx`

## Acceptance criteria

- An owner can revoke a sent signing link.
- A revoked link can no longer bootstrap a public signing session.
- An owner can reissue a new link without rebuilding the request.
- The previous token stops working after reissue.
- Expired links fail closed with a clear status message.

## Verification

- Unit tests for token parsing with versioned or nonce-based tokens.
- Integration tests for revoke and reissue behavior.
- Frontend tests for response-panel actions and updated status display.
- Manual artifact access checks after revoke/reissue.

## Open questions

- Should completion artifact downloads share the same expiry policy as the signing ceremony?
- Should reissue preserve the old invite history or append a new delivery history entry?
