# Phase 0: Scope Lock And Safe Positioning

Status: [ ] Planned

## Why this phase exists

The current signing implementation is a reasonable baseline for ordinary business documents, but `consumer` mode does not yet store enough evidence to support a full E-SIGN consumer-consent workflow. The product should not overstate what the current system proves.

This phase reduces legal and positioning risk before deeper feature work begins.

## Goals

- Decide whether `consumer` mode remains available during remediation.
- Narrow customer-facing claims so they match the actual evidence the system stores today.
- Document the intended signing scope clearly inside the repo.

## Recommended project decision

Preferred path:
- Disable `consumer` mode in production until Phase 4 is complete.

Fallback path:
- Keep `consumer` mode behind an internal flag and label it as incomplete / non-default.

## Scope

Backend:
- Add an env flag or hard gate that disables `consumer` mode for production request creation.
- Return a clear validation error when `consumer` mode is unavailable.

Frontend:
- Remove or hide `consumer` mode from owner workflows unless the feature flag is enabled.
- Remove copy that implies broad E-SIGN consumer readiness.

Docs and marketing:
- Narrow claims to ordinary business e-sign workflows.
- Explicitly state that excluded categories and consumer-disclosure-heavy workflows are out of scope until the consumer consent rebuild is complete.

## Non-goals

- Do not implement new signer verification in this phase.
- Do not redesign the audit manifest in this phase.
- Do not attempt storage retention enforcement in this phase.

## Likely files

- `backend/services/signing_service.py`
- `backend/api/routes/signing.py`
- `backend/api/schemas/models.py`
- `frontend/components/features/SignatureRequestDialog*`
- `frontend/src/config/intentPages.ts`
- `frontend/docs/running.md`
- `backend/README.md`
- `frontend/README.md`

## Acceptance criteria

- Production can no longer create a `consumer` request unless an explicit enable flag is on.
- Owner UI does not present `consumer` mode by default.
- Public marketing/docs no longer imply that the current implementation already satisfies the full consumer-consent workflow.
- Repo docs clearly state the current supported signing scope.

## Verification

- Backend unit test for request creation rejecting `consumer` mode when disabled.
- Frontend unit test confirming `consumer` mode is hidden or marked unavailable.
- Manual grep review of public copy for over-broad consumer-compliance language.

## Open questions

- Should `consumer` mode be completely removed from the UI, or left visible with a locked explanation?
- Is there any customer already depending on `consumer` mode in dev or prod?
