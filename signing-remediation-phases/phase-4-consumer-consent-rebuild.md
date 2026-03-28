# Phase 4: Consumer Consent Rebuild

Status: [x] Implemented

## Why this phase exists

This is the heavy phase that closes the largest compliance gap. If DullyPDF wants to support consumer-facing e-signature workflows, it needs a full disclosure-and-consent artifact rather than the current lightweight acknowledgment step.

## Goals

- Build a versioned consumer-consent workflow aligned with the evidence needed for 15 U.S.C. § 7001(c).
- Persist the exact disclosure package shown to the signer.
- Demonstrate and record that the signer could access the electronic form being used.
- Seal the resulting consent evidence in the audit manifest.

## Scope

Disclosure package:
- Render a server-defined, versioned consumer disclosure artifact.
- Include:
  - paper-copy option and any fees
  - withdrawal right and procedure
  - whether consent applies to one transaction or a category of records
  - contact-update procedure
  - hardware and software requirements

Access demonstration:
- Add an explicit electronic confirmation step that reasonably demonstrates access to the electronic format being used.
- Persist the method and result of that demonstration.

Persistence:
- Store the exact disclosure payload, not just a short version string.
- Store disclosure hash, render timestamp, and acceptance timestamp.

Audit:
- Include the full consent evidence in the audit manifest.
- Include a summarized version in the audit receipt.

## Recommended design

Backend-owned disclosure definitions:
- Create a versioned disclosure registry in code or config.
- Serve the exact disclosure payload to the frontend from the backend so the signed record can reference the exact text rendered.

Access demonstration options:
- Require the signer to open the PDF preview and complete the consent electronically in that same ceremony.
- Optionally require the signer to acknowledge a short access statement tied to the PDF view.

## Non-goals

- Do not treat this as a copy refresh.
- Do not implement state-by-state legal variance in this phase.
- Do not expand to excluded document categories in this phase.

## Likely files

- `backend/services/signing_service.py`
- `backend/api/routes/signing_public.py`
- `backend/api/schemas/models.py`
- `backend/firebaseDB/signing_database.py`
- `backend/services/signing_audit_service.py`
- `frontend/src/components/pages/PublicSigningPage.tsx`
- `frontend/src/services/api.ts`

## Suggested data additions

Request-level:
- `consumer_disclosure_version`
- `consumer_disclosure_payload`
- `consumer_disclosure_sha256`
- `consumer_disclosure_presented_at`
- `consumer_consent_scope`
- `consumer_access_demonstrated_at`
- `consumer_access_demonstration_method`

## Acceptance criteria

- The consumer disclosure content is server-defined, versioned, and persisted exactly as shown.
- The signer cannot continue until the disclosure flow is completed.
- The request stores more than `consentedAt`; it stores a complete disclosure artifact and access-demonstration evidence.
- The sealed audit manifest contains the consent evidence needed to reconstruct what the signer saw and accepted.

## Verification

- Backend unit tests for disclosure registry, serialization, and audit inclusion.
- Integration tests for consumer flow happy path and withdrawal / incomplete disclosure path.
- Frontend tests verifying the consent UI renders backend-defined content.
- Manual review of the final audit receipt and manifest payload.

## Open questions

- Should the disclosure package vary by document category, or stay fixed for all supported consumer requests?
- Should there be a signed downloadable copy of the disclosure package itself in addition to manifest inclusion?
