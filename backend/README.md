## Backend

FastAPI service for PDF field detection, schema-only OpenAI mapping, and saved-form storage. Runtime entrypoint remains `backend/main.py`, while app construction and routing now live under `backend/api/`:

- `backend/api/app.py`: app factory + middleware + router registration
- `backend/api/routes/`: endpoint modules grouped by domain
- `backend/api/schemas/`: request model definitions
- `backend/services/`: shared business/helpers used by routes

Detection is executed by the dedicated detector service (`backend/detection/detector_app.py`) which runs CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) under `backend/fieldDetecting/commonforms/`. The legacy OpenCV pipeline lives in `legacy/fieldDetecting/` and is not part of the main pipeline.

### Core flows

- Detection: `POST /detect-fields` queues CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection and returns a `sessionId`.
- Detection status: `GET /detect-fields/{sessionId}` returns status + fields when ready.
- CommonForms-only (by [jbarrow](https://github.com/jbarrow/commonforms)): `POST /api/process-pdf` (legacy upload helper; dev-only; auth required; no rename/mapping).
- Register fillable: `POST /api/register-fillable` (dev-only; auth required; store PDF bytes without running detection).
- OpenAI rename (overlay tags + PDF pages; schema headers included for combined rename+map): `POST /api/renames/ai`.
- OpenAI rename job status (task mode): `GET /api/renames/ai/{jobId}`.
- Schema metadata: `POST /api/schemas`, `GET /api/schemas`.
- Schema mapping (OpenAI): `POST /api/schema-mappings/ai` (returns mappings plus fill-time rule payloads; updates session mapping state).
- Schema mapping job status (task mode): `GET /api/schema-mappings/ai/{jobId}`.
- Saved forms: `GET /api/saved-forms`, `POST /api/saved-forms` (supports `overwriteFormId` to replace an existing saved form), `GET /api/saved-forms/{id}`, `GET /api/saved-forms/{id}/download`, `POST /api/saved-forms/{id}/session`, `PATCH /api/saved-forms/{id}/editor-snapshot`, `DELETE /api/saved-forms/{id}`.
- API Fill owner endpoints: `GET /api/template-api-endpoints`, `POST /api/template-api-endpoints`, `POST /api/template-api-endpoints/{id}/rotate`, `POST /api/template-api-endpoints/{id}/revoke`, and `GET /api/template-api-endpoints/{id}/schema` (publishes a frozen saved-form snapshot plus a template-scoped secret, surfaces current plan limits, returns recent endpoint audit activity, now tracks runtime generation failures alongside auth/validation failures in the endpoint summary, rejects unknown top-level publish fields instead of silently ignoring them, and marks owner JSON responses `private, no-store`. Publish/rotate/revoke now assemble their success response from the already-committed endpoint record so a follow-up owner-detail read cannot strand a freshly issued one-time secret, while auxiliary limits/activity reads degrade best-effort instead of turning the lifecycle action into a `500`. Owner recent-activity reads prefer the indexed `endpoint_id + created_at` query but now fall back to endpoint-scoped in-memory ordering if that Firestore composite index is missing, so partially provisioned environments do not turn the detail route into a `500`.)
- API Fill public endpoints: `GET /api/v1/fill/{endpointId}/schema` and `POST /api/v1/fill/{endpointId}.pdf` (Basic auth with the endpoint-scoped key on both public routes, auth/rate-limit admission before JSON parsing, exact `Basic base64(API_KEY:)` parsing so malformed credentials are rejected before endpoint lookup, metadata-first secret verification so wrong-key traffic does not load the full published snapshot, `application/json` required on the public fill `POST`, a required top-level `data` object plus strict top-level request-envelope validation, deterministic JSON-to-PDF fill, `private, no-store` responses for both schema and PDF downloads, fail-closed rate limiting, browser-origin allowlist enforcement on public fill `POST`s, endpoint-scoped throttling for repeated auth failures on known endpoints, owner-plan page/month limits, and usage/audit logging without storing raw field values by default. Monthly quota is now checked and incremented inside the same committed success transaction as the endpoint usage counters and audit event, so only completed fills count and a finalization failure cannot burn quota on its own. Endpoint success summaries stay pinned to the request's reserved usage month even if a fill crosses a UTC month boundary before completion, request-envelope validation failures are summarized before they are persisted so owner audit trails do not store raw caller input, blank strings now remain valid scalar values so callers can intentionally clear text/date-like fields, plan-limit blocks are now logged separately from monthly-quota blocks, field-defined checkbox groups without explicit `checkboxRules` are surfaced as list-style schema keys instead of being dropped, conflicting normalized public keys now fail closed at publish/runtime instead of silently shadowing one another, and signature widgets are intentionally excluded from the public API schema because signature capture stays on the dedicated signing workflow instead of the generic fill API.)
- Template groups: `GET /api/groups`, `POST /api/groups`, `GET /api/groups/{id}`, `DELETE /api/groups/{id}` (named containers for existing saved forms; deleting a saved form automatically removes it from every group).
- Fill By Link: `GET /api/fill-links`, `POST /api/fill-links`, `PATCH /api/fill-links/{id}`, `POST /api/fill-links/{id}/close`, and public `/api/fill-links/public/*` routes (supports one link per saved template or one merged link per open group). Published links now persist a normalized `web_form_config` plus a published question schema so owners can control global defaults, per-question requiredness, per-question text limits, and template-only custom web-form questions. Template links can optionally freeze a publish snapshot so accepted respondents can download a PDF copy of their own submission later via a public response download route. Respondent downloads default to a flattened `flat` artifact, while template owners can opt into an `editable` respondent download mode that preserves widgets for that public response download without affecting signing artifacts. If post-submit signing is enabled, the publish/update routes force respondent downloads back to `flat` so the public response artifact never stays editable. Template links can also enable a post-submit signing handoff: the owner maps signer name/email questions at publish time, the publish flow requires a visible email question for the signer-email mapping, requires an explicit U.S. e-sign eligibility attestation for the selected document category, and consumer-mode post-submit signing now also requires request-specific paper-copy, fee, withdrawal, and contact-update disclosures before publish succeeds. The public submit route validates that signer name/email before it stores the response. Once validated, the backend materializes the immutable filled PDF from the stored response snapshot, creates a signing request, and sends the signer a continue-signing email for that exact record instead of returning a live `/sign/:token` URL to the submitting browser. Public `/api/fill-links/public/{token}/retry-signing` now resends that signing email against the stored response record with delivery-state feedback and cooldowns, and transient post-submit failures still return a retryable signing payload so respondents are not stranded after their response was already stored. If the signing category policy tightens later, the response-to-signing handoff revalidates the stored category before creating or reusing a request, so stale published configs cannot bypass newly blocked document classes. Owner response listings now embed linked signing invite state plus signed-PDF / audit-receipt download paths when a response has completed signing.
- Signing workflow: `GET /api/signing/options`, `GET /api/signing/requests`, `POST /api/signing/requests`, `GET /api/signing/requests/{id}`, `GET /api/signing/requests/{id}/artifacts`, `GET /api/signing/requests/{id}/artifacts/{artifactKey}`, `POST /api/signing/requests/{id}/send`, `POST /api/signing/requests/{id}/revoke`, `POST /api/signing/requests/{id}/reissue`, `GET /api/signing/public/validation/{token}`, and public `/api/signing/public/*` routes. The owner workflow remains one-request-per-signer, but the frontend can now create and send recipient batches by saving multiple drafts from pasted/uploaded TXT or CSV data, then tracking them through the owner `Responses` view. Draft creation now requires an explicit U.S. e-sign eligibility attestation for the selected document category, and consumer-mode drafts also require request-specific paper-copy, fee, withdrawal, and contact-update disclosures before the draft can be saved. Send/reissue revalidate the current blocked-category policy so stale drafts cannot bypass later compliance-policy changes. Signing requests are also capped per immutable document version by plan: the free tier defaults to 10 signer requests for one document version, while Pro defaults to 1,000, revoked unsent drafts release their reserved slot, and already-sent requests continue to count against that document. Sent requests now receive a request-level expiry window, the owner can revoke any unsatisfied draft/link from the workspace, and reissue rotates a versioned public signer URL so previous tokens stop resolving after replacement. Signing records now persist explicit signer transport metadata (`signer_contact_method`, `signer_auth_method`) so invite delivery policy, ceremony gating, and downstream webhook payloads do not need to infer channel/auth behavior from legacy source-type heuristics. Consumer-mode source previews stay locked until e-consent is recorded, and public ceremony sessions are bound to the bootstrap client fingerprint instead of behaving like replayable bearer tokens. Email OTP verification now protects every emailed signing request source in the default config, so `/sign/:token` must pass `/verification/send` and `/verification/verify` before the immutable PDF, review, consent, manual fallback, signature adoption, or completion routes are available. The signature-adoption step now persists four signer-controlled render modes for the visible signature mark: typed name, default legal name, drawn signature, and uploaded signature image. The same bound session gate now protects `/document` and public artifact downloads too, including already-completed requests, but the completion payload no longer exposes live artifact URLs. Public pages must first mint a short-lived artifact link through `POST /api/signing/public/{token}/artifacts/{artifactKey}/issue`, then redeem it through `GET /api/signing/public/artifacts/{artifactToken}` with the bound signing session header, so completed links no longer act like long-lived bearer URLs for signed PDFs or audit receipts. Missing source/artifact blobs on those public download/completion paths now fail with deterministic client errors instead of surfacing generic `500`s. Consumer requests still expose a separate `/consumer-access-pdf` access-check route, require the signer to enter the access code from that PDF before `/consent` succeeds, and allow explicit `/withdraw-consent` before completion so the audit trail retains stronger E-SIGN-style consumer evidence. The signer-facing public payload now also exposes sender name/contact and removes on-page manual-fallback language when that button is disabled, so the disclosure package matches the actual ceremony options. Phase 4 now persists the exact server-defined consumer disclosure payload, its SHA-256 digest, the first presented timestamp, the consent scope, and the recorded access-demonstration method/result on the request itself, then seals that evidence into the audit manifest and summarizes it in the audit receipt. Milestone 4 extends `Sign` mode so the final signer action now materializes a flattened signed PDF, stores an audit-manifest JSON envelope plus a human-readable audit receipt PDF, and exposes signed-PDF / audit-receipt downloads to the public completion page while owners can retrieve the full artifact set later. Completed requests also mint a stable `/verify-signing/:token` validation path, the audit receipt now embeds that validation URL in both text and QR form, and the public validation route verifies the retained audit envelope plus signed-PDF hashes without requiring a separate signing session. When a PDF signing identity is configured, completion also embeds a cryptographic PDF signature directly into the finalized PDF, can attach an RFC 3161 timestamp via `SIGNING_PDF_TSA_URL`, and surfaces that embedded-signature verification result through the same public validation route. Best-effort outbound signing webhooks can now fan out lifecycle events such as request creation, invite delivery, review/consent, completion, revoke, and reissue to server-configured URLs without making the core signing state transition fail if delivery is unavailable. The public receipt intentionally redacts signer email/IP/user-agent fields; the owner-only audit manifest retains the full evidence set. Phase 5 adds a storage-tier split for signing: source/completion uploads stage under short-lived storage first, finalized artifacts live under the dedicated `SIGNING_BUCKET`, and deploy preflight now validates that the final bucket exposes a retention-capable policy before prod deploys continue. Milestone 5 also brings `Fill and Sign` onto the same immutable boundary: the frontend freezes reviewed workspace values through `/api/forms/materialize`, owner drafts can persist Fill By Link response provenance (`source_type=fill_link_response`, `source_id`, `source_link_id`, `source_record_label`), and the send route now requires an explicit owner-review confirmation before a reviewed fill can be frozen and sent. Invite delivery is best-effort per request, and provenance/audit event persistence is best-effort too, so successful create/send/retry transitions do not fail only because telemetry storage is temporarily unavailable. When Gmail delivery is unavailable outside production the backend marks the request for manual follow-up instead of failing the send. The signing stack is engineered for ordinary U.S. business records plus the repo-defined consumer-consent ceremony, but it is not a blanket legal determination for every document class or jurisdiction. Excluded categories, regulated workflows, notarial acts, and document-type-specific consumer rules still require separate policy/legal review before enabling them in production.
- Outside production, request-derived signing invite origins are only trusted when they match the configured CORS allowlist. Any other `Origin` / `Referer` value falls back to `SIGNING_APP_ORIGIN` (or the local default) so emailed signing links cannot be pointed at an arbitrary host by request-header spoofing.
- The request-security middleware now defaults API responses to `Cache-Control: private, no-store` unless a route already set a stricter/specific cache policy. That keeps authenticated JSON, public signing ceremony payloads, and other sensitive API responses from being cached by browsers or intermediaries just because a route forgot to add the header manually.
- Post-submit Fill By Link signing reuses the same signing subsystem instead of inventing a second signer flow. The response submit handler creates signing requests with `source_type=fill_link_response`, links them back to the originating Fill By Link response, and derives signing anchors from the response snapshot/template geometry. When signing is enabled for a template link, signature-ceremony-managed questions are excluded from the public Fill By Link question schema so respondents only sign inside `/sign/:token`, not in the HTML intake form itself. Those response-backed requests stay inside the same email-OTP gate as owner-created signing requests so possession of the public signing link alone is not enough to open or sign the frozen PDF.
- Template session (fillable upload): `POST /api/templates/session` (stores PDF bytes + fields so rename/mapping can run).
- Materialize fillable: `POST /api/forms/materialize` (auth required; injects fields into a PDF upload and enforces fillable page limits).
- Profile summary: `GET /api/profile` (tier info, credits, limits, billing metadata, and downgrade-retention state when applicable).
- Downgrade retention controls: `PATCH /api/profile/downgrade-retention` (swap the kept saved forms during grace) and `POST /api/profile/downgrade-retention/delete-now` (purge queued saved forms + dependent Fill By Link records immediately).
- Billing webhook health: `GET /api/billing/webhook-health` (auth required; reports whether Stripe webhook delivery prerequisites are healthy. Full endpoint diagnostics are restricted to `ROLE_GOD`; other users receive a redacted status summary).
- Billing reconciliation: `POST /api/billing/reconcile` (auth required; regular users reconcile a specific checkout session they started, while `ROLE_GOD` can audit recent `checkout.session.completed` events across users).
- Contact form: `POST /api/contact` (public; reCAPTCHA required; sends email via Gmail API).
- reCAPTCHA verify: `POST /api/recaptcha/assess` (public; used for account creation checks).

### Production API routing (Firebase Hosting rewrites)

In production, the SPA is served from Firebase Hosting and a subset of backend endpoints are proxied
through Hosting rewrites so the browser can call them as same-origin `/api/...` requests. This is
primarily to remove CORS preflights (OPTIONS) from fast JSON endpoints (notably reCAPTCHA verification
and profile fetches) so Cloud Run scale-to-zero cold starts feel less blocking.

Production redeploys no longer force a warm backend by default. Leave
`BACKEND_MIN_INSTANCES` unset in `env/backend.prod.env` to preserve the current Cloud Run min
instance count across deploys, or set it explicitly when you want the deploy script to manage warm
capacity.

Be careful with ad hoc `gcloud run services update` or `gcloud run services update-traffic`
commands in prod: if they pin traffic to an older revision or override scaling unexpectedly, Cloud
Run can serve stale code or revert to a different warm/cold posture than the current service config.

Some endpoints are intentionally not proxied (OpenAI routes, detection routes, and large upload/stream
routes) to avoid Firebase Hosting's Cloud Run rewrite timeout (approximately 60 seconds) and to keep
large transfers direct-to-Cloud-Run.

See `frontend/docs/api-routing.md` for the current rewrite list and frontend call rules.

Firestore composite indexes are now tracked in-repo via `firestore.indexes.json`. The API Fill
owner recent-activity query requires the `template_api_endpoint_events(endpoint_id ASC,
created_at DESC)` index for the normal fast path. Deploy it with
`bash scripts/deploy-firestore-indexes.sh` (or `DULLYPDF_ALLOW_NON_PROD=1 PROJECT_ID=dullypdf-dev bash scripts/deploy-firestore-indexes.sh`
for the dev project) so environments do not rely on the slower in-memory fallback. The same file
also tracks the Firestore TTL field overrides for `expires_at` on `detection_requests`,
`openai_rename_requests`, `openai_requests`, `rate_limits`, `schema_metadata`,
`signing_sessions`, and `session_cache`, so fresh environments keep automatic expiry cleanup
aligned with live prod/dev.
After deploying indexes, verify TTL enablement with `gcloud firestore fields ttls list --database='(default)'`.

### Runtime requirements

- Main API: Cloud Tasks client + Firebase Admin + OpenAI (optional).
- Detector service: CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) + PyTorch for detection.
- Rename worker service: OpenAI rename execution (`backend/ai/rename_worker_app.py`).
- Remap worker service: OpenAI schema mapping execution (`backend/ai/remap_worker_app.py`).
- OpenAI API key for rename + schema mapping (schema metadata only).
- Firebase Admin for auth and role claims.
- GCS buckets for saved forms and templates.

### Minimum env (dev)

- `FIREBASE_PROJECT_ID`
- `BACKEND_RUNTIME_SERVICE_ACCOUNT` for production deploys so Cloud Run attaches the
  intended runtime identity before ADC-backed Firebase Admin starts.
- `FIREBASE_CREDENTIALS` (JSON string) or `GOOGLE_APPLICATION_CREDENTIALS` (path) for local/dev,
  or `FIREBASE_USE_ADC=true` on GCP. Production Cloud Run deploys now require ADC-only and reject
  Firebase JSON credential env/path overrides.
- `FIREBASE_CREDENTIALS_SECRET` (local/dev helper Secret Manager name loaded by `scripts/*backend*.sh`)
- `FIREBASE_CREDENTIALS_PROJECT` (local/dev helper Secret Manager project, if different from `FIREBASE_PROJECT_ID`)
- `FORMS_BUCKET`, `TEMPLATES_BUCKET`
- `SIGNING_BUCKET` (required dedicated finalized-artifact bucket for signing; must stay separate from forms/templates/session storage. Outside production the backend can derive a conventional fallback of `<FIREBASE_PROJECT_ID>-signing` when this is omitted, but local env files should still set it explicitly.)
- `SIGNING_STAGING_BUCKET` (optional; short-lived staging bucket for pre-finalization signing uploads. Defaults to the session bucket, then `FORMS_BUCKET` when unset.)
- `SIGNING_LINK_TOKEN_SECRET` (required in production; public signing links and public signing sessions are HMAC-signed)
- `SIGNING_AUDIT_KMS_KEY` (required in production for audit-manifest signing; may point at a CryptoKey or a specific CryptoKeyVersion)
- `SIGNING_PDF_P12_BASE64` / `SIGNING_PDF_P12_PATH` + `SIGNING_PDF_P12_PASSWORD` (optional PKCS#12 identity for embedding a digital signature into finalized PDFs)
- `SIGNING_PDF_KMS_KEY` + `SIGNING_PDF_CERT_PEM` / `SIGNING_PDF_CERT_PEM_BASE64` / `SIGNING_PDF_CERT_PATH` (optional Cloud KMS + X.509 certificate identity for embedded PDF signatures)
- `SIGNING_PDF_CERT_CHAIN_PEM` / `SIGNING_PDF_CERT_CHAIN_PEM_BASE64` / `SIGNING_PDF_CERT_CHAIN_PATH` (optional certificate chain bundled into the embedded PDF signature)
- `SIGNING_PDF_TSA_URL` (optional RFC 3161 timestamp authority URL for embedded PDF signatures)
- `SIGNING_PDF_USE_BUNDLED_DEV_CERT` (dev/test-only override for the repo's local test certificate; outside production the bundled certificate is used by default when no PKCS#12 or KMS identity is configured, and this flag can be set to `false` to disable that fallback explicitly)
- `SIGNING_RETENTION_DAYS` (default 2555 and minimum 2555; prod deploy preflight enforces the full seven-year floor before completed signing artifacts are written)
- `SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_BASE` / `SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_PRO` / `SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_GOD` (per-document signing request caps; defaults 10 / 1000 / 100000)
- `SIGNING_SESSION_TTL_SECONDS` (default 3600; public signer session lifetime after bootstrap)
- `SIGNING_ARTIFACT_TOKEN_TTL_SECONDS` (default 300; short-lived public artifact download token lifetime after the completion page requests a download)
- `SIGNING_REQUEST_TTL_DAYS` (default 30; request-level lifetime for sent signer links before the public ceremony becomes inactive)
- `FILL_LINK_SIGNING_RESEND_COOLDOWN_SECONDS` (default 300; minimum delay before a Fill By Link respondent can request another signing email for the same stored response)
- `SIGNING_VIEW_RATE_WINDOW_SECONDS`, `SIGNING_VIEW_RATE_PER_IP`
- `SIGNING_VIEW_RATE_GLOBAL` (optional; global cap for anonymous signing page loads)
- `SIGNING_ACTION_RATE_WINDOW_SECONDS`, `SIGNING_ACTION_RATE_PER_IP`
- `SIGNING_ACTION_RATE_GLOBAL` (optional; global cap for anonymous signing session bootstrap and ceremony actions)
- `SIGNING_DOCUMENT_RATE_WINDOW_SECONDS`, `SIGNING_DOCUMENT_RATE_PER_IP`
- `SIGNING_DOCUMENT_RATE_GLOBAL` (optional; global cap for anonymous immutable-PDF preview loads)
- `SIGNING_VERIFICATION_SEND_RATE_WINDOW_SECONDS`, `SIGNING_VERIFICATION_SEND_RATE_PER_IP`
- `SIGNING_VERIFICATION_SEND_RATE_GLOBAL` (optional; global cap for anonymous signing verification email sends)
- `SIGNING_VERIFICATION_VERIFY_RATE_WINDOW_SECONDS`, `SIGNING_VERIFICATION_VERIFY_RATE_PER_IP`
- `SIGNING_VERIFICATION_VERIFY_RATE_GLOBAL` (optional; global cap for anonymous signing verification attempts)
- `SIGNING_VERIFICATION_SOURCE_TYPES` (default `workspace,fill_link_response,uploaded_pdf`; comma-separated signing source types that must pass email OTP before the public ceremony continues. Supports `none` to disable or `all` / `all_email_signing_requests` to enable every supported source type.)
- `SIGNING_VERIFICATION_CODE_TTL_SECONDS` (default 600; email OTP lifetime after a send)
- `SIGNING_VERIFICATION_RESEND_COOLDOWN_SECONDS` (default 60; minimum delay before the same signing session can request another OTP)
- `SIGNING_VERIFICATION_MAX_ATTEMPTS` (default 5; maximum failed OTP attempts before the signer must request a new code)
- `SIGNING_CONSUMER_ACCESS_RATE_WINDOW_SECONDS`, `SIGNING_CONSUMER_ACCESS_RATE_PER_IP`
- `SIGNING_CONSUMER_ACCESS_RATE_GLOBAL` (optional; global cap for failed consumer access-code demonstrations before consent)
- `SIGNING_CONSUMER_ACCESS_MAX_ATTEMPTS` (default 5; maximum failed consumer access-code attempts per signing session before the signer must reload and bootstrap a fresh session)
- `OPENAI_API_KEY` (only if schema mapping enabled)
- `CONTACT_TO_EMAIL`, `CONTACT_FROM_EMAIL`
- `SIGNING_FROM_EMAIL` (optional; defaults to `CONTACT_FROM_EMAIL` for signing invites)
- `SIGNING_APP_ORIGIN` (optional in dev; when set in prod it must stay the canonical `https://dullypdf.com` origin with no path/query/fragment. In local dev keep this aligned to the actual frontend origin, typically `http://localhost:5173`, so emailed `/sign/:token` links open on the live Vite server.)
- `SIGNING_WEBHOOK_URL` / `SIGNING_WEBHOOK_URLS` (optional best-effort signing lifecycle webhook destinations; `SIGNING_WEBHOOK_URLS` accepts a comma-separated fanout list)
- `SIGNING_WEBHOOK_SECRET` (optional HMAC secret for `X-Dully-Signature` delivery headers)
- `SIGNING_WEBHOOK_TIMEOUT_SECONDS` (default 8; outbound webhook timeout per request)
- `SIGNING_WEBHOOK_EVENT_TYPES` (optional comma-separated allowlist for emitted signing events; defaults to the core lifecycle set such as `request_created`, `request_sent`, `invite_sent`, `opened`, `review_confirmed`, `consent_accepted`, `completed`, `link_revoked`, and `link_reissued`)
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
- `GMAIL_CLIENT_SECRET_SECRET`, `GMAIL_REFRESH_TOKEN_SECRET` (optional local/dev Secret Manager bindings for the Gmail secret/refresh token)
- `GMAIL_SECRETS_PROJECT` (optional; overrides the Secret Manager project for local/dev Gmail secret loading)
- `GMAIL_USER_ID` (optional; defaults to `me`)
- `RECAPTCHA_SITE_KEY`
- `RECAPTCHA_PROJECT_ID` (or `FIREBASE_PROJECT_ID` / `GCP_PROJECT_ID`)
- `RECAPTCHA_CONTACT_ACTION` (default `contact`; overrides legacy `RECAPTCHA_EXPECTED_ACTION`)
- `RECAPTCHA_SIGNUP_ACTION` (default `signup`; overrides legacy `RECAPTCHA_EXPECTED_ACTION`)
- `RECAPTCHA_ALLOWED_HOSTNAMES` (comma-separated allowlist; supports `*.example.com`; required in prod when reCAPTCHA is enabled)
- `RECAPTCHA_MIN_SCORE` (default 0.5)
- `CONTACT_REQUIRE_RECAPTCHA` (default true)
- `CONTACT_RATE_LIMIT_WINDOW_SECONDS`, `CONTACT_RATE_LIMIT_PER_IP`
- `CONTACT_RATE_LIMIT_GLOBAL` (optional; global cap for `/api/contact` regardless of caller IP)
- `SIGNUP_REQUIRE_RECAPTCHA` (default true)
- `SIGNUP_RATE_LIMIT_WINDOW_SECONDS`, `SIGNUP_RATE_LIMIT_PER_IP`
- `SIGNUP_RATE_LIMIT_GLOBAL` (optional; global cap for `/api/recaptcha/assess` regardless of caller IP)
- `FILL_LINK_REQUIRE_RECAPTCHA` (default true; must remain true in production)
- `FILL_LINK_TOKEN_SECRET` (required in production at runtime; public Fill By Link URLs are signed from the link id instead of storing new plaintext bearer tokens)
- `FILL_LINK_TOKEN_SECRET_SECRET` (recommended prod deploy setting; `scripts/deploy-backend.sh` binds this Secret Manager secret to the `FILL_LINK_TOKEN_SECRET` runtime env var and rejects literal prod values)
- `FILL_LINK_VIEW_RATE_WINDOW_SECONDS`, `FILL_LINK_VIEW_RATE_PER_IP`
- `FILL_LINK_VIEW_RATE_GLOBAL` (optional; global cap for anonymous Fill By Link page loads)
- `FILL_LINK_SUBMIT_RATE_WINDOW_SECONDS`, `FILL_LINK_SUBMIT_RATE_PER_IP`
- `FILL_LINK_SUBMIT_RATE_GLOBAL` (optional; global cap for anonymous Fill By Link submissions)
- `FILL_LINK_DOWNLOAD_RATE_WINDOW_SECONDS`, `FILL_LINK_DOWNLOAD_RATE_PER_IP`
- `FILL_LINK_DOWNLOAD_RATE_GLOBAL` (optional; global cap for anonymous respondent PDF downloads)
- `FILL_LINK_MAX_ANSWER_VALUE_CHARS`, `FILL_LINK_MAX_TOTAL_ANSWER_CHARS`, `FILL_LINK_MAX_MULTI_SELECT_VALUES`
- `FILL_LINK_ALLOW_LEGACY_PUBLIC_TOKENS` (default false; temporary fallback for previously issued plaintext Fill By Link URLs only)
- `SANDBOX_TRUST_PROXY_HEADERS` (required `true` in prod; keep `false` only outside prod. Production startup rejects `false` because the Cloud Run deployment path relies on trusted proxy headers.)
- `SANDBOX_CORS_ORIGINS` (comma-separated list)
- `SANDBOX_TRUSTED_HOSTS` (comma-separated host allowlist for `Host` header validation; required in prod and should include every Firebase Hosting domain that serves the API plus any temporary Cloud Run `run.app` hosts you still need during migration)
- `SANDBOX_ENABLE_LEGACY_ENDPOINTS` (dev-only; defaults to true; ignored in prod)
- `ADMIN_TOKEN` (dev-only override; ignored when `ENV=prod` or `SANDBOX_ALLOW_ADMIN_OVERRIDE=false`)
- `SANDBOX_DETECT_MAX_PAGES_BASE`, `SANDBOX_DETECT_MAX_PAGES_GOD`
- `SANDBOX_FILLABLE_MAX_PAGES_BASE`, `SANDBOX_FILLABLE_MAX_PAGES_GOD`
- `SANDBOX_SAVED_FORMS_MAX_BASE`, `SANDBOX_SAVED_FORMS_MAX_GOD`
- `SANDBOX_SCHEMA_TTL_SECONDS`
- `SANDBOX_OPENAI_LOG_TTL_SECONDS`
- `SANDBOX_ENABLE_DOCS` (optional; defaults to enabled outside prod; set to `false` to disable OpenAPI/docs in dev/test; ignored in prod)
- `DETECTOR_MODE` (`tasks` for production)
- `DETECTOR_TASKS_PROJECT`, `DETECTOR_TASKS_LOCATION`
- `DETECTOR_TASKS_QUEUE` or `DETECTOR_TASKS_QUEUE_LIGHT`
- `DETECTOR_SERVICE_URL` or `DETECTOR_SERVICE_URL_LIGHT`
- `DETECTOR_TASKS_QUEUE_HEAVY`, `DETECTOR_SERVICE_URL_HEAVY` (optional; for 10+ page PDFs)
- `DETECTOR_ROUTING_MODE` (optional; `cpu`, `split`, or `gpu` when backend env files keep both CPU and GPU detector URLs)
- `DETECTOR_SERVICE_URL_LIGHT_GPU`, `DETECTOR_SERVICE_URL_HEAVY_GPU` (optional; used by `split`/`gpu` routing)
- `DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD` (default 10)
- `DETECTOR_SERIALIZE_GPU_TASKS` (optional; when `true` and routing mode is `gpu`, heavy detector jobs reuse the light/default queue and the light GPU service so one shared deployment can enforce a single-GPU ceiling)
- `DETECTOR_GPU_BUSY_FALLBACK_TO_CPU` (optional; when `true` in `gpu` routing, light PDFs can spill to CPU when the GPU lane already has queued/running work)
- `DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD` (default 5; only PDFs with fewer pages than this threshold are eligible for CPU spillover)
- `DETECTOR_GPU_BUSY_ACTIVE_WINDOW_SECONDS` (default 1800; ignore stale queued/running GPU request records older than this window)
- `DETECTOR_TASKS_QUEUE_LIGHT_CPU`, `DETECTOR_SERVICE_URL_LIGHT_CPU`, `DETECTOR_TASKS_AUDIENCE_LIGHT_CPU` (optional explicit CPU spillover queue/service for gpu-first routing)
- `DETECTOR_TASKS_SERVICE_ACCOUNT`
- `DETECTOR_TASKS_AUDIENCE`, `DETECTOR_TASKS_AUDIENCE_LIGHT`, `DETECTOR_TASKS_AUDIENCE_HEAVY` (optional)
- `DETECTOR_TASKS_AUDIENCE_LIGHT_GPU`, `DETECTOR_TASKS_AUDIENCE_HEAVY_GPU` (optional)
- `DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT`, `DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY` (optional)
- `DETECTOR_TASKS_FORCE_IMMEDIATE` (optional; schedule tasks in the past to bypass host clock skew)
- `OPENAI_RENAME_MODE` (`tasks` for production async rename workers)
- `OPENAI_RENAME_TASKS_PROJECT`, `OPENAI_RENAME_TASKS_LOCATION`
- `OPENAI_RENAME_TASKS_QUEUE` or `OPENAI_RENAME_TASKS_QUEUE_LIGHT`
- `OPENAI_RENAME_SERVICE_URL` or `OPENAI_RENAME_SERVICE_URL_LIGHT`
- `OPENAI_RENAME_TASKS_QUEUE_HEAVY`, `OPENAI_RENAME_SERVICE_URL_HEAVY` (optional; for larger PDFs)
- `OPENAI_RENAME_TASKS_HEAVY_PAGE_THRESHOLD` (default 10)
- `OPENAI_RENAME_TASKS_SERVICE_ACCOUNT`
- `OPENAI_RENAME_TASKS_AUDIENCE`, `OPENAI_RENAME_TASKS_AUDIENCE_LIGHT`, `OPENAI_RENAME_TASKS_AUDIENCE_HEAVY` (optional)
- `OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT`, `OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY` (optional)
- `OPENAI_REMAP_MODE` (`tasks` for production async remap workers)
- `OPENAI_REMAP_TASKS_PROJECT`, `OPENAI_REMAP_TASKS_LOCATION`
- `OPENAI_REMAP_TASKS_QUEUE` or `OPENAI_REMAP_TASKS_QUEUE_LIGHT`
- `OPENAI_REMAP_SERVICE_URL` or `OPENAI_REMAP_SERVICE_URL_LIGHT`
- `OPENAI_REMAP_TASKS_QUEUE_HEAVY`, `OPENAI_REMAP_SERVICE_URL_HEAVY` (optional; for large template tag sets)
- `OPENAI_REMAP_TASKS_HEAVY_TAG_THRESHOLD` (default 120)
- `OPENAI_REMAP_TASKS_SERVICE_ACCOUNT`
- `OPENAI_REMAP_TASKS_AUDIENCE`, `OPENAI_REMAP_TASKS_AUDIENCE_LIGHT`, `OPENAI_REMAP_TASKS_AUDIENCE_HEAVY` (optional)
- `OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT`, `OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY` (optional)
- `OPENAI_REQUEST_TIMEOUT_SECONDS` (default 75; bounds each OpenAI request to avoid long UI stalls)
- `OPENAI_MAX_RETRIES` (default 1; OpenAI SDK retry count for rename/remap calls)
- `OPENAI_WORKER_MAX_RETRIES` (default 0; worker-only OpenAI SDK retries to avoid multiplying Cloud Tasks retries)
- `OPENAI_CREDITS_PAGE_BUCKET_SIZE` (default 5; credits scale per `ceil(page_count / bucket_size)`)
- `OPENAI_CREDITS_RENAME_BASE_COST` (default 1)
- `OPENAI_CREDITS_REMAP_BASE_COST` (default 1)
- `OPENAI_CREDITS_RENAME_REMAP_BASE_COST` (default 2)
- `OPENAI_PRICE_INPUT_PER_1M_USD`, `OPENAI_PRICE_OUTPUT_PER_1M_USD` (optional; enables per-job USD estimates)
- `OPENAI_PRICE_CACHED_INPUT_PER_1M_USD`, `OPENAI_PRICE_REASONING_OUTPUT_PER_1M_USD` (optional; refine USD estimates when token subclasses are available)
- `OPENAI_PREWARM_ENABLED` (default false; best-effort worker warmup during detection)
- `OPENAI_PREWARM_REMAINING_PAGES` (default 3; trigger point for prewarm)
- `OPENAI_PREWARM_TIMEOUT_SECONDS` (default 2; health check timeout)

Local operators who start the backend with `scripts/run-backend-dev.sh` also need IAM access that matches the helper flow:

- `roles/secretmanager.secretAccessor` on the Firebase credentials secret used by `scripts/_load_firebase_secret.sh`
- `roles/storage.objectViewer` on the bucket that stores the CommonForms model referenced by `COMMONFORMS_MODEL_GCS_URI`

Use `scripts/grant-dev-gcp-access.sh you@example.com` to grant the current dev defaults (`dullypdf-dev-firebase-admin` and `gs://dullypdf-dev-models`) to a specific email.

Detector env examples:
- `config/detector.dev.env.example`
- `config/detector.prod.env.example`

### Notes

- Session entries are cached in-process (L1) and persisted in Firestore + GCS (L2) for multi-instance access.
- L1 uses TTL/LRU via `SANDBOX_SESSION_TTL_SECONDS`, `SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS`, and `SANDBOX_SESSION_MAX_ENTRIES`.
- L2 expiry should be aligned to `SANDBOX_SESSION_TTL_SECONDS` with Firestore TTL plus a scheduled cleanup job for GCS session artifacts (`scripts/cleanup_sessions.py`, deployed in prod through `scripts/deploy-session-cleanup-job.sh`, which now also reconciles the paired scheduler configuration).
- Prod currently runs the session cleanup job every 6 hours. Hourly runs are usually unnecessary unless you need tighter orphan cleanup for session artifacts.
- L2 touch throttling uses `SANDBOX_SESSION_L2_TOUCH_SECONDS` (default 300 seconds).
- Editor clients should call `/api/sessions/{sessionId}/touch` about once per minute to keep active sessions from expiring.
- `SANDBOX_SESSION_BUCKET` can override the default session bucket (falls back to `FORMS_BUCKET`).
- Dedicated session buckets should not use GCS soft delete when the bucket only stores ephemeral session artifacts; soft delete retains deleted bytes beyond the intended TTL window.
- Signing storage now uses two logical tiers: short-lived staging uploads under `SIGNING_STAGING_BUCKET` (or the session/forms fallback) and finalized artifacts under the dedicated `SIGNING_BUCKET`. Prod deploys now run `python3 scripts/validate-signing-storage.py` so missing retention-capable bucket policy is caught before Cloud Run deploys. Completion now fails closed if signed-PDF / audit artifact promotion into finalized signing storage fails, instead of leaving a request marked `completed` with missing retained evidence. Public validation still attempts a staged-artifact read fallback for older records whose final promotion never landed, but that path should be treated as recovery only, not the steady-state storage tier. If ops decides to make the bucket retention immutable, use `bash scripts/lock-signing-storage-retention.sh --yes-lock-retention`; that step is intentionally manual and irreversible.
- Schema metadata TTL uses `SANDBOX_SCHEMA_TTL_SECONDS` (default 3600) with Firestore TTL on `schema_metadata.expires_at`.
- Detector jobs are queued via Cloud Tasks; the detector service writes fields/results to GCS + Firestore.
- Detector routing picks the heavy queue when `page_count >= DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD` and the heavy service URLs are configured.
- When `DETECTOR_ROUTING_MODE=gpu` but only one GPU is available for the whole detector fleet, set
  `DETECTOR_SERIALIZE_GPU_TASKS=true` so heavy jobs reuse the light/default queue plus the light GPU service and run
  `bash scripts/sync-detector-task-queues.sh <env-file>` after backend/detector deploys.
- If you want gpu-first routing but do not want short PDFs waiting behind that shared GPU lane, also set
  `DETECTOR_GPU_BUSY_FALLBACK_TO_CPU=true` plus explicit `DETECTOR_TASKS_QUEUE_LIGHT_CPU` /
  `DETECTOR_SERVICE_URL_LIGHT_CPU` values so `page_count < DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD`
  requests can spill to CPU whenever Firestore already shows queued/running GPU detector work.
- Rename/remap jobs can run in `tasks` mode and are persisted in Firestore (`openai_jobs`) with pollable status.
- Async rename/remap jobs store OpenAI usage summaries (`openai_usage_summary`, `openai_usage_events`) so status polling can report token usage (and optional USD estimates when pricing env vars are set).
- Rename/remap task workers refund consumed credits on terminal failures.
- Credit refunds now retry automatically (`OPENAI_CREDIT_REFUND_MAX_ATTEMPTS`, `OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS`) and unresolved failures are recorded in Firestore (`credit_refund_failures`) for reconciliation.
- Detection can emit best-effort OpenAI worker prewarm requests when `OPENAI_PREWARM_ENABLED=true` and remaining pages are below `OPENAI_PREWARM_REMAINING_PAGES`.
- Encrypted PDFs are rejected before detection to avoid repeated task retries.
- `DETECTOR_TASKS_MAX_ATTEMPTS` on the detector service should match the Cloud Tasks queue max attempts to finalize failures on the last retry.
- Session ownership guards can be sanity-checked with `python -m backend.scripts.verify_session_owner`.
- One-off Gmail sends can be run with `python -m backend.scripts.send_gmail_once <recipient> "<subject>" "<body>"`.
  The script uses the existing Gmail prod env vars, appends successful recipients to `tmp/sent-email-recipients.txt`,
  and exits with failure when the recipient already exists in that sent log (override path via `--sent-log-path`).
  Follow-ups are blocked by default and require explicit flags:
  `--mode followup --followup-flag FOLLOWUP_OK` (follow-up log path defaults to `tmp/sent-email-followups.txt`).
- Outbound research + personalization + sending guidance for Codex terminals is documented in
  `backend/scripts/outbound_email_playbook.md`.
- Generated outbound lead artifacts under `backend/scripts/leads/` are local-only and can be
  removed with `python3 clean.py --outbound-leads` (also included in the default `npm run clean`).
- Base users start with 10 lifetime OpenAI credits. Credits are billed per page bucket using server-side page counts:
  `total_credits = operation_base_cost * ceil(page_count / OPENAI_CREDITS_PAGE_BUCKET_SIZE)`.
  Defaults: Rename base cost `1`, Remap base cost `1`, Rename+Remap base cost `2`; with default bucket size `5`, a 10-page Rename+Remap costs `4`. God role bypasses credits.
- `GET /api/profile` now includes `creditPricing` (server bucket/base-cost settings), `billing` metadata (`enabled`, plan catalog, subscription linkage/status, and cancellation schedule fields), and `retention` metadata when a downgraded free account is inside the saved-form grace window.
- Downgrade retention keeps the default oldest saved forms up to the free limit, stores the rest in a 30-day delete queue, and closes dependent Fill By Link records immediately. The queue can be purged manually with `POST /api/profile/downgrade-retention/delete-now` or automatically through `backend/scripts/purge_downgrade_retention.py`.
- Email/password logins must be email-verified; OAuth providers are treated as verified.
- Schema metadata (headers/types) is stored in Firestore; CSV/Excel/JSON rows and field values never reach the server.
- Schema mapping may emit deterministic fill rules (`fillRules`), including `checkboxRules`, `radioGroupSuggestions`, and `textTransformRules` (for split/join text fill cases).
- Session and saved-form metadata persist `textTransformRules` alongside checkbox rule metadata so Search & Fill can replay deterministic transforms.
- Template Fill By Link can persist an owner-controlled respondent-download snapshot that freezes the published PDF storage path, normalized field payload, fill rules, and download mode at publish time. Public respondent downloads materialize from that snapshot plus the stored respondent answer record; group links never expose PDF downloads.
- Fill By Link response validation is schema-driven: published questions can carry per-question `required`, `maxLength`, placeholders, help text, and option metadata, while the existing environment-level answer caps remain the hard safety ceiling on stored submissions.
- Saved-form metadata can reference a versioned editor snapshot JSON artifact in storage so reopen/group-switch flows can hydrate page sizes and extracted fields without repeating PDF extraction on every open. Snapshot upload is best-effort during save and can be backfilled later through `PATCH /api/saved-forms/{id}/editor-snapshot`.
- Postgres/SQL integrations are not part of the runtime path (moved to `legacy/`).
- OpenAI rate limiting uses Firestore (`SANDBOX_RATE_LIMIT_BACKEND=firestore`) with the `rate_limits` collection by default.
- Detection rate limiting uses `SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS` and `SANDBOX_DETECT_RATE_LIMIT_PER_USER`.
- Detection and OpenAI rename/remap rate limits now fail closed when the Firestore limiter is unavailable.
- Public `/api/contact` and `/api/recaptcha/assess` rate limits fail closed when the Firestore limiter is unavailable.
- Enable Firestore TTL on `rate_limits.expires_at` to auto-expire rate limit counters.
- OpenAI and detection request logs use `SANDBOX_OPENAI_LOG_TTL_SECONDS` with Firestore TTL on `openai_requests.expires_at`,
  `openai_rename_requests.expires_at`, `credit_refund_failures.expires_at`, and `detection_requests.expires_at`.
- Public signing sessions carry device-binding and OTP challenge metadata, so `signing_sessions.expires_at`
  should also stay on Firestore TTL to enforce the short-retention design from the signing remediation plan.
- One-time cleanup tasks (schema TTL backfill, template mapping purge) live in `scripts/cleanup_firestore_artifacts.py`.
- OpenAPI/Docs routes are always disabled in prod. Outside prod they default to enabled and can be disabled with `SANDBOX_ENABLE_DOCS=false`.

### Local test files

- Small, tracked fixtures live in `quickTestFiles/` for quick manual testing.
- Large datasets remain in `samples/` and are ignored by git.

### More docs

- `backend/fieldDetecting/README.md`
- `backend/fieldDetecting/docs/README.md`
- `backend/fieldDetecting/docs/commonforms.md`
- `backend/fieldDetecting/docs/rename-flow.md`
- `backend/fieldDetecting/docs/security.md`

### Running locally

Prefer the repo scripts so the backend uses `backend/.venv` (CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) requires
NumPy 1.x and will fail under NumPy 2.x if you run with a system Python). For local dev, prefer Python 3.11+
to match Docker and avoid future dependency support warnings (Google libs warn on Python 3.10):

```bash
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Then run:

```
./scripts/run-backend-dev.sh env/backend.dev.env
```

For the fast local path (frontend + backend together), run:

```
npm run dev
```

If you keep `DETECTOR_MODE=local`, install `backend/requirements-detector.txt` so
CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) is available. For the production-style flow, use the dev stack:

```
npm run dev:stack
```

The dev stack expects `env/backend.dev.stack.env` (created from
`config/backend.dev.stack.env.example`) and uses Cloud Tasks + the Cloud Run
detector in `dullypdf-dev`. The stack forces prod-mode backend behavior
(`ENV=prod`, revocation checks on, legacy endpoints disabled) while still using
dev resources. It only reads the stack env file, so export `OPENAI_API_KEY`
separately if you want rename/mapping enabled. In task mode, it also resolves
OpenAI rename/remap worker URLs (`dullypdf-openai-rename-*`, `dullypdf-openai-remap-*`).
Set `DETECTOR_ROUTING_MODE=cpu|split|gpu` in the stack env to switch detector
traffic between CPU-only, CPU-light/GPU-heavy, and GPU-only routing. The CPU
services keep the existing names (`dullypdf-detector-light`, `...-heavy`); GPU
services default to `dullypdf-detector-light-gpu` / `...-heavy-gpu`. The legacy
`DEV_STACK_DETECTOR_GPU=true` flag still maps to `DETECTOR_ROUTING_MODE=gpu`
when the new routing mode is unset. If GPU quota is only available in a
different Cloud Run region than the Cloud Tasks queues, set `DETECTOR_GPU_REGION`
in the stack env. In `dullypdf-dev`, the current working example is
`DETECTOR_GPU_REGION=us-east4`.
If that GPU region only has one accelerator available, also set
`DETECTOR_SERIALIZE_GPU_TASKS=true` and run
`bash scripts/sync-detector-task-queues.sh env/backend.dev.stack.env`
so light and heavy detection share one serialized queue.
If you still want GPU to be the first choice, add
`DETECTOR_GPU_BUSY_FALLBACK_TO_CPU=true` plus
`DETECTOR_TASKS_QUEUE_LIGHT_CPU` / `DETECTOR_SERVICE_URL_LIGHT_CPU`
so PDFs under five pages can spill to the CPU detector whenever the GPU lane is already occupied.
When `DEV_STACK_BUILD=1` is set, `npm run dev:stack` now rebuilds the local
backend image and redeploys detector + OpenAI worker Cloud Run services using
`scripts/deploy-detector-services.sh` and `scripts/deploy-openai-workers.sh`
before starting the local stack.
To clean up lingering processes,
run:

```
npm run dev:stack:stop
```

To run a CPU vs GPU detector benchmark (same PDF set, detection duration, Cloud
Run request latency, billable-second cost estimate), use:

```
scripts/benchmark-detector-cpu-gpu.sh env/backend.dev.stack.env
```

The benchmark script deploys CPU and GPU detector services in separate regions
when `BENCH_GPU_REGION` or `DETECTOR_GPU_REGION` is set. That lets the local
backend keep using the existing Cloud Tasks queues while GPU detector services
live in the region that actually has L4 quota.
Benchmark deploys now stay private by default and refuse to target the
`dullypdf` prod project unless `BENCH_ALLOW_PROD_PROJECT=true` is set.
Public detector benchmarks require an explicit `BENCH_ALLOW_UNAUTHENTICATED=true`.

Detector service entrypoint (for Cloud Run or local dev):

```
uvicorn backend.detection.detector_app:app --host 0.0.0.0 --port 8000
```

Rename worker service entrypoint:

```
uvicorn backend.ai.rename_worker_app:app --host 0.0.0.0 --port 8000
```

Remap worker service entrypoint:

```
uvicorn backend.ai.remap_worker_app:app --host 0.0.0.0 --port 8000
```

### Billing testing (dev)

`npm run dev` now auto-starts Stripe CLI forwarding for local billing when `STRIPE_SECRET_KEY` is present in `env/backend.dev.env`, forwarding to `http://localhost:${PORT}/api/billing/webhook` and injecting the listener session webhook secret into the backend process.

`npm run dev:stack` now does the same for the prod-like stack when `STRIPE_SECRET_KEY` is present in `env/backend.dev.stack.env`, forwarding to `http://localhost:${DEV_STACK_BACKEND_PORT:-8010}/api/billing/webhook` and injecting the listener session webhook secret into the backend container.

Local Stripe forwarding notes:
- Local forwarding is tunnel-based and does not create a Stripe dashboard webhook endpoint.
- Because of that, local `npm run dev` and `npm run dev:stack` force `STRIPE_ENFORCE_WEBHOOK_HEALTH=false` for the backend process/container so checkout is not blocked by endpoint-health enforcement.
- Set `STRIPE_DEV_LISTEN_ENABLED=false` to run local dev or dev stack without Stripe forwarding.

Use these commands when validating Stripe billing checkout/webhook behavior:

```bash
pytest backend/test/unit/api/test_main_billing_endpoints_blueprint.py
pytest backend/test/unit/core/test_billing_service_blueprint.py
pytest backend/test/integration/test_billing_webhook_integration.py
```

For a live smoke test against a running backend, including signed webhook security checks,
card outcome event coverage (`4242`, `3155`, `0002`, `9995`), duplicate-event handling, and
subscription lifecycle events:

```bash
./scripts/test-billing-webhooks.sh env/backend.dev.env http://localhost:8000
```

For prod deploys, `scripts/deploy-backend.sh` requires Stripe keys to come from
Secret Manager bindings (`STRIPE_SECRET_KEY_SECRET`, `STRIPE_WEBHOOK_SECRET_SECRET`)
and rejects literal `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` values. The deploy
script also hard-fails unless `backend/test/integration/test_billing_webhook_integration.py`
passes. Signing prod preflight now runs in the same script: it rejects placeholder/short
`SIGNING_LINK_TOKEN_SECRET` values, requires `SIGNING_AUDIT_KMS_KEY` and `SIGNING_BUCKET`,
and enforces integer retention/session/rate-limit settings for the public signing ceremony.
The same deploy step also resolves the active detector URLs/audiences from
`DETECTOR_ROUTING_MODE`, so switching detector traffic between CPU, split, and GPU
is an env-file change plus backend redeploy.

Webhook fulfillment and checkout guardrails:
- Refill checkout fulfillment (`checkout.session.completed` for `refill_500`) is applied only when the user is currently Pro at fulfillment time.
- Refill checkout credits are validated against the configured Stripe refill price mapping before credits are granted; mismatched or unresolvable refill metadata now returns a retriable non-2xx webhook response so fulfillment is not silently acknowledged.
- Pro checkout session creation (`pro_monthly` / `pro_yearly`) is blocked when the user already has an active subscription.
- Pro checkout now binds to a stable Stripe customer, reuses an existing open Pro checkout session for that customer when present, blocks checkout when that customer already has an active Pro subscription in Stripe, and uses deterministic per-plan idempotency keys so concurrent duplicate session creates collapse without monthly/yearly key collisions.
- Refill checkout session creation is blocked unless the user is currently eligible for refill fulfillment (active Pro state).
- Refill checkout now also binds to a stable Stripe customer and reuses an existing open refill session for that customer when present, which prevents accidental duplicate session creation during quick retries.
- Checkout session creation can be hard-blocked by Stripe webhook health (`STRIPE_ENFORCE_WEBHOOK_HEALTH=true`) so new purchases are disabled when delivery prerequisites are unhealthy.
- Set `STRIPE_WEBHOOK_ENDPOINT_URL` to the exact webhook URL your backend receives. Webhook health checks match this specific URL and fail closed when enforcement is enabled but the URL is missing/misconfigured.
- `POST /api/billing/reconcile` lets authenticated users recover missed paid checkout fulfillment for a specific checkout session they started; `ROLE_GOD` can still reconcile across users from recent Stripe events.
- Subscription lifecycle role changes (`customer.subscription.updated` / `customer.subscription.deleted`) are applied only for configured Pro price ids; unrelated subscription products are ignored.
- Subscription cancel requests are allowed when the user has a stored Stripe subscription id, even if role state drifted from `pro`, so users can always stop billing.
- Fresh in-progress webhook locks now return a retriable non-2xx response instead of a duplicate `200` so Stripe retries rather than dropping fulfillment.
- `BILLING_EVENT_LOCK_TIMEOUT_SECONDS` defaults to `120` seconds to reduce stale-lock retry delays after worker crashes.
- When lock clearing fails after a webhook error, the handler now attempts a lock-document delete fallback to shorten retry stalls caused by transient Firestore write failures.
- Pro checkout and invoice fulfillment now promote membership and persist Stripe subscription linkage in one Firestore transaction.
- `STRIPE_MAX_PROCESSED_EVENTS` defaults to `256` and should stay bounded in production so Stripe dedupe history cannot bloat long-lived user documents. The separate `billing_events` collection remains the primary idempotency record.
- `STRIPE_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS` defaults to `300`; this windowed idempotency applies to Pro plan checkout creation. Refill checkouts use attempt-scoped idempotency keys so consecutive refill purchases do not redirect to a previously completed session.
- Checkout redirect URLs always include a `billing` query parameter (`success`/`cancel`) even when custom URLs are configured.
- In `ENV=prod`, startup fails fast if Stripe billing vars are missing or if checkout redirect URLs are not `https://`.

### Billing webhook troubleshooting (prod)

When Stripe webhooks misbehave in production, use this sequence:

1. Find the event in Cloud Logging by Stripe id and route:
   - Filter example:
     ```text
     resource.type="cloud_run_revision"
     resource.labels.service_name="dullypdf-backend-east4"
     jsonPayload.stripeEventId="evt_..."
     ```
   - The billing route logs `stripeEventId`, `eventType`, duplicate detection, completion, and retryable failures.

2. Inspect Firestore lock/event state:
   - Collection: `billing_events`
   - Document id: Stripe `event.id`
   - Key fields: `status` (`processing|processed|failed`), `attempts`, `updated_at`.
   - A stuck `processing` status older than `BILLING_EVENT_LOCK_TIMEOUT_SECONDS` can be reclaimed automatically; use `status=failed` (or clear the doc) only as an incident action.

3. Resend from Stripe after fixing root cause:
   - Stripe CLI:
     ```bash
     stripe events resend evt_... --webhook-endpoint=we_...
     ```
   - Or replay from Stripe Dashboard event timeline.

4. Re-run local smoke checks against the target backend:
   - `./scripts/test-billing-webhooks.sh env/backend.dev.env http://localhost:8000`

Docker images:
- `Dockerfile` (main API)
- `Dockerfile.detector` (detector service)
- `Dockerfile.ai-rename` (rename worker service)
- `Dockerfile.ai-remap` (remap worker service)
- `backend/requirements.txt` is main API deps; `backend/requirements-detector.txt` adds CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)).

Worker deploy script (Cloud Run):

```
npm run deploy:openai-workers
```

`scripts/deploy-openai-workers.sh` deploys rename/remap light+heavy services with `--no-allow-unauthenticated`, enforces caller service-account invoker IAM, and refreshes per-service worker audience/service URL env vars from each deployed Cloud Run URL.

Detector deploy script (Cloud Run):

```
npm run deploy:detector-services
```

`scripts/deploy-detector-services.sh` now supports `DETECTOR_ROUTING_MODE=cpu|split|gpu`
plus `DETECTOR_DEPLOY_VARIANTS=active|cpu|gpu|both`. `active` deploys the services
used by the selected routing mode, while `both` predeploys CPU and GPU detector
stacks so later backend flips only require changing `DETECTOR_ROUTING_MODE` and
redeploying the backend.

Full prod deploy (backend + detector + OpenAI workers + frontend):

```
npm run deploy:all-services
```

`scripts/deploy-all-services.sh` orchestrates all service deploy steps in prod order and requires `ENV=prod` in the backend env file before proceeding. The prod path now deploys detector/OpenAI workers before the backend so the backend env is rebuilt from the current worker Cloud Run URLs, and it finishes with `scripts/prune-stale-cloud-resources.sh` to delete duplicate regional workers, retired detector services, and stale detector queues left behind by older routing layouts. The prod backend deploy step defaults to `dullypdf-backend-east4` in `us-east4`, the prod task queues plus worker services should stay aligned in `us-east4` to avoid cross-region dispatch, and the default build target now follows `ARTIFACT_REGISTRY_LOCATION=us-east4` so newly built images land in the same region family. Prod deploy scripts now also reject alternate Artifact Registry locations, alternate repo names, and explicit image overrides outside `us-east4-docker.pkg.dev/dullypdf/dullypdf-backend/...` so a manual deploy cannot silently repopulate the retired central registry.
