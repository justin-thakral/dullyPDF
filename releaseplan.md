# DullyPDF Release Plan (Secure, Limited, Monetized)

## Goals
- Release a secure, hosted product with account-based limits.
- Prevent commercial resale of the code via a restrictive license.
- Keep schema mapping header-only (no database connections in runtime).
- Add ad viewing while renaming/CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) is running.

## Non-goals
- Open-source (OSI) distribution. A non-commercial license is not open source.
- Reintroducing Postgres/DB integrations in v1.

## Decisions Needed (Blockers)
- License choice: non-commercial source-available (e.g., PolyForm Noncommercial) vs. proprietary "all rights reserved".
- Account model: Firebase Auth only or another identity provider.
- Usage limit definition: lifetime credits vs. reset cadence, and whether limits apply to rename + mapping only or all pipelines.
- Ad network choice: AdSense vs. direct sponsor embed vs. custom house ads.
- OpenAI rename: keep enabled or off by default with an opt-in toggle.

## Phase 0 - Legal + Compliance
1) Choose and add license file at repo root (`LICENSE`).
2) Add a short license notice to README:
   - "View/use for evaluation only. No commercial use or redistribution."
3) Add `NOTICE` with third-party attributions if required by dependencies.
4) Verify that any sample PDFs/data are redistributable or remove them.

## Phase 1 - Repo Cleanup (Before Public Hosting)
1) Remove large artifacts from the repo history if present (git-filter-repo if needed).
2) Ensure `backend/fieldDetecting/outputArtifacts/` and datasets stay ignored.
3) Remove any local credentials, service account files, or database dumps.
4) Document required env vars and secrets in a new `README` section.

## Phase 2 - Feature Flags (Optional Disable Schema Mapping)
1) Backend: add `SANDBOX_DISABLE_SCHEMA_MAPPING=true` support.
   - If enabled, reject `/api/schema-mappings/ai` with 403.
2) Frontend: add `VITE_DISABLE_SCHEMA_MAPPING=true`.
   - Hide schema mapping UI and related toggles.
3) Add a UI banner: "Schema mapping temporarily disabled" (optional).
4) Add a small unit test or manual test checklist for this flag.

## Phase 3 - Account Credits (OpenAI Pages)
1) Require Auth for OpenAI rename/mapping operations.
2) Track credits per user in Firestore (already supported via `BASE_OPENAI_CREDITS`).
3) Enforce in backend:
   - Compute page count from the PDF.
   - Consume one page per rename/mapping run (combined counts once per page).
4) Add UI:
   - Show remaining credits and error messaging when exhausted.
5) Add a safe override for admins.

## Phase 4 - Ads During Processing
1) UI only: show an ad view/overlay while detection is running.
2) Placement rules:
   - Show only when `isProcessing` and (pipeline is "commonforms" (CommonForms by [jbarrow](https://github.com/jbarrow/commonforms)) or rename is enabled).
   - Hide immediately on completion or error.
3) Ad integration:
   - Start with a simple banner slot (house ad) and swap for a network later.
4) Policy considerations:
   - Don't obscure consent dialogs or critical UI.
   - Ensure no PII leaks into ad targeting.
5) Include a "Support this tool" message to set expectations.

## Phase 5 - Security Hardening
1) Backend:
   - Lock CORS to your Firebase Hosting domain.
   - Add request size limits and file-type validation for uploads.
   - Rate limit `/detect-fields` and `/api/connections/test`.
2) Secrets:
   - Use Secret Manager for OpenAI keys and Firebase service account.
3) Logging:
   - Avoid logging raw PDFs or tokens.
4) Frontend:
   - Turn off source maps in production builds.
   - Add strict Content Security Policy (CSP) if possible.

## Phase 6 - Hosting (GCP + Firebase)
1) Backend on Cloud Run:
   - Build container, configure env vars, set memory/CPU.
   - Enable Cloud Storage if using GCS for saved PDFs.
2) Database:
   - Firestore + Storage only; no Postgres in v1.
3) Frontend on Firebase Hosting:
   - Set `VITE_API_URL` to Cloud Run URL.
4) Networking:
   - Add CORS origins for Firebase Hosting domains.
5) Domain + SSL:
   - Configure custom domain and HTTPS.

## Phase 7 - Monitoring + Operations
1) Set up Cloud Logging and error alerts.
2) Track OpenAI spend per user and overall.
3) Add a basic status page and incident response checklist.

## Phase 8 - Release Checklist
1) Smoke tests:
   - Upload PDF, detect fields, rename disabled/enabled, quota handling.
2) Security tests:
   - Unauthorized requests fail.
   - Rate limits fire under load.
3) Ads:
   - Show/hide states behave correctly.
4) Rollback:
   - Keep previous Cloud Run revision and Firebase deploy targets.

## Future Enhancements (Post-Release)
- Paid tier for higher limits.
- Replace ads with subscription gating.
- Optional external DB integrations behind a paid plan (requires separate compliance review).
