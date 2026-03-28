# Phase 3: Sender And Invite Provenance Audit Events

Status: [x] Implemented

## Why this phase exists

The current audit package is strong on signer-side ceremony evidence but weak on sender-side provenance. For dispute handling, the owner should be able to show who created the request, who sent it, how it was delivered, and when those actions occurred.

## Goals

- Capture sender-side provenance as first-class audit events.
- Persist invite delivery metadata in a stable format.
- Include sender-side provenance inside the sealed audit manifest.

## Scope

Backend:
- Record signed events for request creation, send, invite delivery result, manual link sharing, and later revoke/reissue actions.
- Add provider delivery identifiers where available.
- Add sender identity details to the audit manifest.

Frontend:
- Surface invite provenance in the owner responses panel where helpful.
- Show whether the request was emailed automatically or handled manually.

Audit receipt:
- Include sender and delivery summary lines in the human-readable receipt.

## Recommended event model

Add events such as:
- `request_created`
- `request_sent`
- `invite_sent`
- `invite_failed`
- `invite_skipped`
- `manual_link_shared`
- `link_revoked`
- `link_reissued`

Each event should capture only necessary details. Avoid putting secrets into event payloads.

## Suggested data additions

Request-level:
- `owner_user_id`
- `sender_email`
- `invite_method`
- `last_invite_provider_message_id`

Event-level details:
- `provider`
- `provider_message_id`
- `delivery_status`
- `delivery_error_code`
- `delivery_error_summary`

## Non-goals

- Do not implement new provider integrations in this phase.
- Do not store raw email bodies in the audit manifest.

## Likely files

- `backend/api/routes/signing.py`
- `backend/services/signing_invite_service.py`
- `backend/firebaseDB/signing_database.py`
- `backend/services/signing_audit_service.py`
- `frontend/src/components/features/SigningResponsesPanel.tsx`

## Acceptance criteria

- The system records sender-side events from request creation through invite delivery.
- The sealed audit manifest includes owner/sender provenance and invite metadata.
- The audit receipt includes a concise sender and delivery summary.
- Manual link sharing is distinguishable from automatic email delivery.

## Verification

- Backend unit tests for new event creation and manifest serialization.
- Integration test that sends a request and confirms the final manifest contains sender-side provenance.
- Frontend test for owner response UI showing invite status and method.

## Implementation notes

- Signing requests now persist sender email, invite method, invite provider, delivery error code, and manual-link share timestamp.
- Owner request creation, send, reissue, and manual-share actions record sender-side provenance events.
- Fill By Link post-submit signing records sender-side request creation, send, and invite-delivery events for the auto-send path.
- The sealed audit manifest now includes a dedicated `sender` section, and the human-readable receipt includes sender and delivery summary lines.

## Open questions

- Does the Gmail send path expose a stable provider message id today, or will this require lower-level email service changes?
- Should sender display name be recorded in addition to sender email?
