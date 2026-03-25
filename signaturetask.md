# DullyPDF Signing Milestones

This file tracks the implementation milestones for the DullyPDF signing feature.
Only mark a milestone complete after the code, tests, and docs for that milestone are finished.

## Milestone 1: Signing Foundation

Status: [x] Done

Goals:
- Add the core signing policy model for ordinary U.S. business e-sign use cases.
- Add authenticated owner API scaffolding for signing requests.
- Add a public signing route scaffold for `/sign/:token`.
- Add a workspace entry point for `Send PDF for Signature`.
- Add tests for request validation, persistence, route wiring, and public route rendering.

Acceptance criteria:
- `signaturetask.md` exists and defines the milestone sequence.
- Backend has signing request schemas, policy validation, Firestore persistence helpers, and route registration.
- Frontend has a visible `Send PDF for Signature` entry point and a draft dialog with `Sign` and `Fill and Sign`.
- Frontend resolves `/sign/:token` to a public signing shell.
- Backend and frontend tests for the signing foundation pass locally.

Verification completed on 2026-03-24:
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/integration/test_signing_foundation_integration.py backend/test/unit/config/test_firebase_hosting_rewrites_blueprint.py`
- `cd frontend && npm run test -- test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/pages/test_public_signing_page.test.tsx test/unit/utils/test_signing.test.ts`
- `cd frontend && npm run build:raw`
- Post-refactor verification:
- `cd frontend && npm run test -- test/unit/hooks/test_use_workspace_signing.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/pages/test_public_signing_page.test.tsx test/unit/utils/test_signing.test.ts`

## Milestone 2: Immutable Snapshot And Send

Status: [x] Done

Goals:
- Create immutable source PDF snapshots for signing requests.
- Tie the signing request to an exact document hash and source version.
- Add sender-side `Review and Send` behavior for single-signer requests.
- Store source PDF artifacts in the signing bucket.

Acceptance criteria:
- A signing request can transition from `draft` to `sent`.
- Every sent request stores an immutable PDF artifact path and SHA-256 hash.
- Requests become invalidated if the source document changes before send.
- Sender-side integration tests cover the full `draft -> sent` transition.

Verification completed on 2026-03-24:
- `backend/.venv/bin/python -m py_compile backend/api/routes/signing.py backend/api/routes/signing_public.py backend/firebaseDB/signing_database.py backend/services/signing_service.py backend/firebaseDB/storage_service.py`
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/integration/test_signing_foundation_integration.py backend/test/unit/config/test_firebase_hosting_rewrites_blueprint.py`
- `cd frontend && npm run test -- test/unit/api/test_api_service.test.ts test/unit/hooks/test_use_workspace_signing.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/pages/test_public_signing_page.test.tsx test/unit/utils/test_signing.test.ts`
- `cd frontend && npm run build:raw`

## Milestone 3: Public Signer Ceremony

Status: [x] Done

Goals:
- Add signer review, e-consent, adopt-signature, and complete-signing steps.
- Capture signer evidence: token/session usage, timestamps, IP, user agent, disclosure version.
- Add explicit manual/paper fallback handling.

Acceptance criteria:
- Public signer flow requires document review and an explicit final sign action.
- Consumer mode requires separate e-consent before signing.
- Manual fallback is visible and recorded.
- Integration and Playwright tests cover signer happy path and blocked edge cases.

Verification completed on 2026-03-24:
- `backend/.venv/bin/python -m py_compile backend/api/routes/signing.py backend/api/routes/signing_public.py backend/firebaseDB/signing_database.py backend/services/signing_service.py backend/api/schemas/models.py`
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/integration/test_signing_foundation_integration.py backend/test/unit/config/test_firebase_hosting_rewrites_blueprint.py`
- `cd frontend && npm run test -- test/unit/api/test_api_service.test.ts test/unit/hooks/test_use_workspace_signing.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/pages/test_public_signing_page.test.tsx test/unit/utils/test_signing.test.ts`
- `cd frontend && npm run build:raw`
- `cd frontend && node test/playwright/run_signing_public_smoke.mjs`

## Milestone 4: Signed Artifacts And Audit Trail

Status: [x] Done

Goals:
- Materialize a final signed PDF artifact.
- Produce an append-only audit manifest and a human-readable audit receipt.
- Sign the audit manifest with Cloud KMS.
- Expose signed artifact retrieval to owners and signers where allowed.

Acceptance criteria:
- Completed requests store signed PDF and audit artifacts separately from the source PDF.
- Audit manifests are reproducible and KMS-signed.
- Owners can retrieve signed artifacts later.
- Tests cover artifact creation, retention metadata, and audit integrity checks.

Verification completed on 2026-03-24:
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/unit/services/test_signing_pdf_service.py backend/test/unit/services/test_signing_audit_service.py backend/test/unit/services/test_cloud_kms_service.py backend/test/unit/firebase/test_storage_service_blueprint.py backend/test/integration/test_signing_foundation_integration.py backend/test/unit/config/test_firebase_hosting_rewrites_blueprint.py`
- `cd frontend && npm run test -- test/unit/api/test_api_service.test.ts test/unit/hooks/test_use_workspace_signing.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/pages/test_public_signing_page.test.tsx test/unit/utils/test_signing.test.ts`
- `cd frontend && npm run build:raw`
- PDF render verification:
- `backend/.venv/bin/python - <<'PY' ... generate tmp/pdfs/signing-render-check-signed.pdf and tmp/pdfs/signing-render-check-receipt.pdf ... PY`
- `pdftoppm -png tmp/pdfs/signing-render-check-signed.pdf tmp/pdfs/signing-render-check-signed`
- `pdftoppm -png tmp/pdfs/signing-render-check-receipt.pdf tmp/pdfs/signing-render-check-receipt`
- `pdfinfo tmp/pdfs/signing-render-check-signed.pdf && pdfinfo tmp/pdfs/signing-render-check-receipt.pdf`
- `pdftotext tmp/pdfs/signing-render-check-signed.pdf -`
- `pdftotext tmp/pdfs/signing-render-check-receipt.pdf - | sed -n '1,40p'`

## Milestone 5: Fill And Sign Integration

Status: [x] Done

Goals:
- Connect stored Fill By Link responses and workspace-filled records to the signing pipeline.
- Require owner review before a `Fill and Sign` request is sent.
- Reuse the immutable snapshot boundary for both `Sign` and `Fill and Sign`.

Acceptance criteria:
- Owners can create a signing request from a reviewed fill response.
- The immutable snapshot boundary is shared with the `Sign` mode.
- Tests cover source-type specific validation and owner review gating.

Verification completed on 2026-03-24:
- `backend/.venv/bin/python -m py_compile backend/api/routes/signing.py backend/services/signing_service.py backend/firebaseDB/signing_database.py backend/api/schemas/models.py`
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/integration/test_signing_foundation_integration.py`
- `cd frontend && npm run test -- test/unit/hooks/test_use_workspace_signing.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/features/test_search_fill_modal.test.tsx test/unit/api/test_api_service.test.ts`
- `cd frontend && npm run build:raw`
- `cd frontend && PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 node test/playwright/run_signing_public_smoke.mjs`

## Milestone 6: Production Hardening And Proof

Status: [x] Done

Goals:
- Add production env/config wiring, rate limits, retention settings, and public route rewrites.
- Add Playwright flows, Chrome DevTools proof screenshots, and updated docs.
- Validate prod-like startup and deployment assumptions without deploying automatically.

Acceptance criteria:
- Signing routes/config are documented in backend/frontend docs.
- Firebase Hosting rewrites and same-origin API routing are updated.
- Playwright smoke coverage exists for owner and signer flows.
- Chrome DevTools UI proof is captured under `mcp/debugging/mcp-screenshots`.

Verification completed on 2026-03-24:
- `backend/.venv/bin/pytest backend/test/unit/services/test_signing_service.py backend/test/unit/services/test_signing_pdf_service.py backend/test/unit/services/test_signing_audit_service.py backend/test/unit/services/test_cloud_kms_service.py backend/test/unit/firebase/test_storage_service_blueprint.py backend/test/integration/test_signing_foundation_integration.py backend/test/unit/config/test_firebase_hosting_rewrites_blueprint.py backend/test/unit/scripts/test_deploy_backend_blueprint.py`
- `cd frontend && npm run test -- test/unit/api/test_api_service.test.ts test/unit/hooks/test_use_workspace_signing.test.tsx test/unit/components/features/test_signature_request_dialog.test.tsx test/unit/components/features/test_search_fill_modal.test.tsx test/unit/components/pages/test_public_signing_page.test.tsx test/unit/utils/test_signing.test.ts`
- `cd frontend && npm run build:raw`
- `cd frontend && PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 node test/playwright/run_signing_public_smoke.mjs`
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 node frontend/test/playwright/run_signing_owner_smoke.mjs`
- Chrome DevTools proof screenshots:
- `mcp/debugging/mcp-screenshots/signing-owner-dialog.png`
- `mcp/debugging/mcp-screenshots/signing-public-business.png`
- `mcp/debugging/mcp-screenshots/signing-public-consumer-consent.png`
