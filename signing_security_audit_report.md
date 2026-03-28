# DullyPDF Signing Security Audit

Date: 2026-03-27

Scope:
- Backend signing routes, services, storage, audit generation, and persistence
- Frontend public signing ceremony and owner signing flows
- Current U.S. E-SIGN alignment at a practical product level

Tested:
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/unit/services/test_signing_pdf_service.py backend/test/unit/services/test_signing_audit_service.py backend/test/unit/services/test_cloud_kms_service.py backend/test/unit/services/test_signing_invite_service.py backend/test/unit/services/test_fill_link_signing_service.py backend/test/integration/test_signing_foundation_integration.py`
- `npm --prefix frontend run test -- test/unit/api/test_api_service.test.ts test/unit/components/pages/test_public_signing_page.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/hooks/test_use_workspace_signing.test.tsx`

## Executive Summary

The signing feature is materially stronger than a typical “typed name in a box” implementation. It freezes an immutable source PDF before signature collection, records explicit signer actions, stores source and signed hashes, produces a signed audit manifest in production via Cloud KMS, and keeps signer session/IP/user-agent/timestamp evidence. For ordinary low-risk business documents, that is a reasonable baseline.

It is not yet strong enough to be represented as a full U.S. e-sign compliance platform for consumer or higher-assurance workflows. The largest gaps are:

1. `consumer` mode does not currently satisfy the full E-SIGN consumer-consent workflow in 15 U.S.C. § 7001(c) if you intend to rely on DullyPDF itself for that legal consent.
2. Signer authentication is still fundamentally “whoever possesses the emailed link,” with no OTP, identity proofing, or step-up verification.
3. Public signing links are long-lived bearer URLs with no built-in owner revoke/reissue flow.
4. The stored audit package is missing sender and delivery provenance.
5. Retention is tracked in app metadata, but storage-level immutability/retention enforcement is not visible in repo code.

Bottom line:
- Secure enough for basic internal/business e-sign workflows if you position it honestly.
- Not strong enough yet for high-dispute, consumer-disclosure-heavy, or identity-sensitive signature use cases.

This is not legal advice. The legal comparison below is limited to the federal E-SIGN Act plus general UETA alignment and is not a 50-state legal review.

## High Severity Findings

### SIG-001: Consumer consent flow is incomplete for E-SIGN consumer-disclosure compliance

Severity: High

Locations:
- `frontend/src/components/pages/PublicSigningPage.tsx:16`
- `frontend/src/components/pages/PublicSigningPage.tsx:355`
- `backend/api/schemas/models.py:293`
- `backend/api/routes/signing_public.py:468`
- `backend/services/signing_service.py:41`
- `backend/firebaseDB/signing_database.py:56`

Evidence:
- Consumer mode is a first-class option and maps to a version string only:
  - `backend/services/signing_service.py:41`
  - `backend/services/signing_service.py:556`
- The consumer consent request stores only a boolean acceptance and timestamp:
  - `backend/api/schemas/models.py:293`
  - `backend/api/routes/signing_public.py:475`
  - `backend/firebaseDB/signing_database.py:56`
  - `backend/firebaseDB/signing_database.py:63`
- The frontend disclosure content is only four short bullets:
  - `frontend/src/components/pages/PublicSigningPage.tsx:16`
  - `frontend/src/components/pages/PublicSigningPage.tsx:355`

Why this matters:
- 15 U.S.C. § 7001(c)(1)(B)-(C) requires materially more than “I consent.”
- The statute requires a clear statement about paper copies, withdrawal procedures, scope of consent, contact-update procedure, paper-copy fees, hardware/software requirements, and an electronic consent flow that reasonably demonstrates the consumer can access the form that will be used.
- DullyPDF currently stores only `disclosureVersion` plus `consentedAt`; it does not store the rendered disclosure text, the hardware/software statement, consent scope, contact-update procedure, or any access-demonstration evidence.

Impact:
- If DullyPDF `consumer` mode is intended to satisfy the E-SIGN consumer-consent requirement itself, the implementation is incomplete.
- In a dispute, you would have weak evidence that the user received the full required disclosures before consenting.

Important nuance:
- 15 U.S.C. § 7001(c)(3) says a contract is not automatically invalid solely because the system failed to obtain the specific electronic-consent demonstration in § 7001(c)(1)(C)(ii).
- That means this gap is mainly about consumer-disclosure compliance and proof, not automatic signature invalidity in every case.

Recommended fix:
- Treat `consumer` mode as incomplete until the full disclosure workflow exists.
- Version and persist the exact disclosure text shown to the signer.
- Capture and store:
  - consent scope
  - withdrawal instructions
  - contact-update instructions
  - paper-copy availability and fees
  - hardware/software requirements
  - the access demonstration result and method
- Add the full consent artifact to the final audit manifest and receipt.

### SIG-002: Signer identity assurance is only bearer-link possession

Severity: High

Locations:
- `backend/api/routes/signing_public.py:287`
- `backend/api/routes/signing_public.py:239`
- `backend/api/routes/signing_public.py:548`
- `backend/services/signing_audit_service.py:116`

Evidence:
- Public session bootstrap requires only the public signing token:
  - `backend/api/routes/signing_public.py:287`
- Subsequent signer actions require only the session token issued from that bootstrap:
  - `backend/api/routes/signing_public.py:239`
- The adopted signature name is free-form text, not tied to an authenticated identity factor:
  - `backend/api/routes/signing_public.py:548`
- The final audit bundle records target signer name/email, but not a verified identity method:
  - `backend/services/signing_audit_service.py:116`

Why this matters:
- Anyone who gets the link can complete the ceremony.
- Forwarded email, inbox compromise, misdelivery, shared mailbox access, browser-history leakage, or a copied link from a helpdesk thread can all let the wrong person sign.

Impact:
- For low-risk workflows this may be commercially acceptable.
- For disputed, regulated, or high-value workflows, it is weak signer authentication.

Recommended fix:
- Add optional or policy-driven step-up verification before review or completion:
  - one-time code to signer email
  - passwordless magic-link re-challenge
  - customer SSO/IdP login
  - knowledge-based or document-based proofing only if truly needed
- Store the verification method, evidence, and outcome in the audit manifest.

## Medium Severity Findings

### SIG-003: Public signing links do not expire and cannot be revoked or reissued by the owner

Severity: Medium

Locations:
- `backend/services/signing_service.py:180`
- `backend/services/signing_service.py:193`
- `backend/api/routes/signing.py:346`
- `backend/api/routes/signing_public.py:398`

Evidence:
- Public request tokens are HMAC-protected but have no expiry:
  - `backend/services/signing_service.py:180`
  - `backend/services/signing_service.py:193`
- The owner API exposes create/send flows but no revoke/reissue route:
  - `backend/api/routes/signing.py:346`
- Completed artifacts remain downloadable with the same bearer token:
  - `backend/api/routes/signing_public.py:398`

Why this matters:
- A leaked link can remain useful for a long time.
- This increases exposure for source PDFs before signing and signed artifacts after completion.

Recommended fix:
- Add owner-controlled expiration, revoke, and reissue.
- Consider short-lived artifact download tokens after completion.
- Consider separate “ceremony token” and “completion artifact token” lifetimes.

### SIG-004: The audit package omits sender and invite-delivery provenance

Severity: Medium

Locations:
- `backend/api/routes/signing.py:429`
- `backend/firebaseDB/signing_database.py:50`
- `backend/firebaseDB/signing_database.py:560`
- `backend/services/signing_invite_service.py:31`
- `backend/services/signing_audit_service.py:99`

Evidence:
- The send route updates invite delivery status but does not append a signing event for request send or invite delivery:
  - `backend/api/routes/signing.py:429`
- Request metadata stores invite status/error/timestamps:
  - `backend/firebaseDB/signing_database.py:50`
  - `backend/firebaseDB/signing_database.py:560`
- Invite delivery results do not preserve a provider message ID or equivalent trace handle:
  - `backend/services/signing_invite_service.py:31`
- The final audit manifest omits owner/sender identity and invite metadata:
  - `backend/services/signing_audit_service.py:99`

Why this matters:
- The final audit receipt shows signer-side ceremony evidence, but not who initiated the request or how the signing invitation was sent.
- That weakens provenance when investigating repudiation or delivery disputes.

Recommended fix:
- Record signed events for:
  - request created
  - request sent
  - invite sent / failed / skipped / manual link
- Include:
  - owner user id
  - sender email
  - invite method
  - provider message id or send trace id
  - invite timestamp
- Carry those fields into the sealed audit manifest.

### SIG-005: Retention is represented in metadata, but storage-level immutability is not visible in repo code

Severity: Medium

Locations:
- `backend/services/signing_service.py:645`
- `backend/services/signing_audit_service.py:74`
- `backend/firebaseDB/storage_service.py:145`
- `backend/firebaseDB/storage_service.py:199`

Evidence:
- Retention is computed and stored as metadata:
  - `backend/services/signing_service.py:645`
  - `backend/services/signing_audit_service.py:74`
- Uploads are ordinary GCS writes with `private, no-store`, but no retention hold, versioning, or WORM behavior is set in code:
  - `backend/firebaseDB/storage_service.py:145`
- The same module includes unrestricted deletion helpers for allowlisted objects:
  - `backend/firebaseDB/storage_service.py:199`

Why this matters:
- The app tracks `retentionUntil`, but the code shown here does not itself prevent artifact deletion or replacement before that date.
- This may already be handled externally with bucket retention lock and IAM, but that enforcement is not visible in the repo.

Recommended fix:
- Verify runtime GCS configuration:
  - bucket retention policy
  - bucket lock / WORM where appropriate
  - least-privilege service accounts
  - optional object versioning / legal holds
- Prefer checked-in infra definitions or startup validation so this is not dependent on out-of-band operator memory.

False-positive note:
- If production buckets already have enforced retention lock and restricted IAM, the runtime risk is lower than what the app code alone suggests.

## Low Severity Findings

### SIG-006: Runtime bucket fallback weakens artifact isolation under misconfiguration

Severity: Low

Location:
- `backend/firebaseDB/storage_service.py:41`

Evidence:
- If `SIGNING_BUCKET` is unset, the runtime falls back to `SESSION_BUCKET` or `FORMS_BUCKET`.

Why this matters:
- Signing artifacts should stay isolated from generic form/session storage to keep retention, access review, and incident response simpler.

Recommended fix:
- Fail closed at runtime whenever signing is enabled and `SIGNING_BUCKET` is unset.

### SIG-007: Product copy is slightly ahead of the implementation for consumer-mode compliance

Severity: Low

Locations:
- `frontend/src/config/intentPages.ts:421`
- `frontend/src/config/intentPages.ts:445`
- `frontend/docs/running.md:84`

Evidence:
- Marketing/docs describe the workflow as aligned to core U.S. E-SIGN requirements and call out consumer e-consent.
- The actual implementation does not yet capture the full E-SIGN consumer-consent evidence discussed in SIG-001.

Why this matters:
- The main risk is product/legal positioning, not a code exploit.

Recommended fix:
- Soften public claims until the consumer flow is fully implemented, or narrow them to “basic business e-sign workflow” rather than broader consumer-compliance language.

## What Looks Strong

- Immutable source snapshot at send time with SHA-256 comparison:
  - `backend/api/routes/signing.py:387`
  - `backend/api/routes/signing.py:395`
- Explicit signer ceremony with review, adopt-signature, and final sign action:
  - `backend/api/routes/signing_public.py:424`
  - `backend/api/routes/signing_public.py:548`
  - `backend/api/routes/signing_public.py:592`
- KMS-backed audit-manifest sealing in production:
  - `backend/services/cloud_kms_service.py:95`
  - `backend/services/signing_audit_service.py:158`
- Stored source/signed/audit hashes and artifact separation:
  - `backend/firebaseDB/signing_database.py:72`
  - `backend/api/routes/signing.py:95`
- Public rate limiting and session TTL:
  - `backend/api/routes/signing_public.py:104`
  - `backend/services/signing_service.py:278`
- No-store handling for token-bearing routes and stored objects:
  - `firebase.json:88`
  - `backend/firebaseDB/storage_service.py:145`
- Session token is kept in frontend memory, not persisted in localStorage/sessionStorage:
  - `frontend/src/components/pages/PublicSigningPage.tsx:63`
- Blocked categories are explicitly excluded:
  - `backend/services/signing_service.py:65`

## U.S. E-Signature Comparison Notes

Primary sources reviewed:
- E-SIGN Act, 15 U.S.C. § 7001: https://www.law.cornell.edu/uscode/text/15/7001
- E-SIGN Act definitions, 15 U.S.C. § 7006: https://www.law.cornell.edu/uscode/text/15/7006
- E-SIGN Act exceptions, 15 U.S.C. § 7003: https://www.law.cornell.edu/uscode/text/15/7003
- GovInfo U.S. Code PDF for § 7001 retention/consumer consent text: https://www.govinfo.gov/content/pkg/USCODE-2022-title15/pdf/USCODE-2022-title15-chap96.pdf
- Uniform Law Commission overview noting UETA validates electronic records/signatures in almost every state: https://www.uniformlaws.org/acts/overview
- NIST digital identity guidance for stronger identity proofing/authentication baselines: https://csrc.nist.gov/pubs/sp/800/63/4/final

How DullyPDF compares:
- Intent to sign:
  - Present and fairly strong for business mode. The user must review, adopt, and explicitly finish signing.
- Logical association with the record:
  - Strong. The app freezes the PDF, stores hashes, and binds the ceremony to that exact source.
- Retention/reproducibility:
  - Good at the application layer; stronger if storage-level retention lock is confirmed in infrastructure.
- Consumer consent:
  - Incomplete for any workflow that relies on DullyPDF itself to satisfy E-SIGN consumer-disclosure rules.
- Identity verification:
  - Weak for higher-assurance use cases. The system proves link possession more than person identity.

## Recommended Next Steps

1. Decide product scope explicitly:
   - If DullyPDF is for ordinary business e-sign only, say that clearly.
   - If you want consumer-mode compliance, implement the full E-SIGN § 7001(c) flow.
2. Add signer step-up verification:
   - Email OTP is the minimum practical improvement.
3. Add owner revoke/reissue and link expiry.
4. Add sender/delivery evidence into the sealed audit manifest.
5. Verify and codify GCS retention lock / IAM restrictions.
6. Tighten the public claims until consumer mode is truly complete.
