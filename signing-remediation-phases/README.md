# DullyPDF Signing Remediation Phases

This directory breaks the signing audit follow-up work into discrete implementation phases.

The phases are ordered so the project can quickly reduce risk for ordinary business use cases before taking on the heavier consumer-compliance rebuild.

Recommended execution order:

1. [Phase 0: Scope Lock And Safe Positioning](./phase-0-scope-lock-and-safe-positioning.md)
2. [Phase 1: Email OTP Signer Verification](./phase-1-email-otp-signer-verification.md)
3. [Phase 2: Public Link Expiry, Revoke, And Reissue](./phase-2-public-link-expiry-revoke-and-reissue.md)
4. [Phase 3: Sender And Invite Provenance Audit Events](./phase-3-sender-and-invite-provenance-audit-events.md)
5. [Phase 4: Consumer Consent Rebuild](./phase-4-consumer-consent-rebuild.md)
6. [Phase 5: Storage Retention Enforcement And Artifact Isolation](./phase-5-storage-retention-enforcement-and-artifact-isolation.md)

Cross-reference:
- Signing audit report: [`signing_security_audit_report.md`](../signing_security_audit_report.md)
- Existing signing milestone tracker: [`signaturetask.md`](../signaturetask.md)

Execution guidance:
- Phase 0 should land first because it reduces positioning risk immediately.
- Phases 1 through 3 materially improve practical security for the existing business workflow.
- Phase 4 should not be treated as copy-only work. It requires schema, persistence, UI, and audit-envelope changes.
- Phase 5 should be coordinated with production infrastructure because the current code intentionally deletes stale completion uploads before the request is finalized.
