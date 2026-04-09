# Overview

The frontend is a React + TypeScript app for loading PDFs, editing fields, organizing saved forms into named groups, publishing native Fill By Link forms for either one saved template or an open group, and filling records from local data sources or stored respondent submissions. It connects to the FastAPI backend for detection, OpenAI rename/mapping, profile data, saved forms, template groups, and Fill By Link owner/respondent flows.

## Main workflow

1. Load a PDF (detection upload, fillable upload, saved form, or a saved-form group that opens the alphabetically first template first unless a direct group route requests a specific template).
2. Detect fields with CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) via `/detect-fields`, or import embedded AcroForm widgets.
3. Optionally run OpenAI rename and schema mapping.
4. Edit fields in overlay/list/inspector panels.
5. Save the template, optionally add it to a named saved-form group, then either publish a native Fill By Link for the active template or publish one merged Fill By Link for the open group before loading local CSV/Excel/JSON rows.
6. Reopen templates from the upload screen through the saved-form browser, which supports group filtering, an `Open groups` toggle, inline group deletion, and a stable selected-group label while the group list refreshes.
7. When a group is open, switch between member templates from the header and run batch Rename + Map across every saved form in that group.
8. Run Search & Fill from CSV/Excel/JSON rows or stored Fill By Link respondent records.
9. Download either a `Flat PDF` (field values baked into page content) or an `Editable PDF` (widgets preserved for later editing), or save the current state to the signed-in profile.
10. Persist and replay deterministic fill rules (`fillRules`) including text split/join transforms.
11. Persist a versioned saved-form editor snapshot so reopened templates and group switches can hydrate fields/page sizes without re-extracting them on every open.

## Public usage docs

- End-user documentation is available at canonical `/usage-docs/*` URLs.
- Legacy `/docs/*` URLs are compatibility redirects (HTTP 301) to `/usage-docs/*`.
- Canonical style is non-trailing slash for non-root routes; `/path/` should only 301 once to `/path` (never loop).
- The docs include dedicated pages for detection, rename/mapping, editor workflow, Search & Fill, Fill from Images and Documents, Fill By Link, signature workflow, API Fill, Create Group workflows, save/download/Profile behavior, and troubleshooting.
- Workspace action menus and dialogs now expose direct `Usage Docs` shortcuts that open the matching `/usage-docs/*` route in a new browser tab/window so operators can keep the active editor state intact while reading instructions.
- Route handling lives in `frontend/src/main.tsx` alongside legal page route handling.
- Unknown public URLs should resolve to a noindex 404 experience instead of falling back to the app homepage.

## Workspace routing

- `/` is the marketing shell only.
- Firebase Hosting rewrites dynamic app and public-ceremony routes (`/upload`, `/ui*`, `/respond/:token`, `/sign/:token`, `/verify-signing/:token`, `/account-action`) to a neutral `app-shell.html` SPA bootstrap instead of the prerendered homepage `index.html`.
- The prerendered homepage `index.html` is reserved for `/` and SEO/public static-route generation, so homepage-only cover markup does not leak into Fill By Link or signing routes.
- `/upload` mounts the signed-in upload shell.
- `/ui` is the generic editor/runtime route for unsaved uploads and in-flight workspace processing.
- `/ui/profile` opens the signed-in profile view.
- `/ui/forms/:formId` reopens a saved form directly.
- `/ui/groups/:groupId?template=:formId` reopens a saved group directly and prefers the requested template when that query param is present.
- Direct workspace routes are handled in `frontend/src/main.tsx` and forwarded into the runtime/browser-route state instead of being treated as generic homepage visits.

## Public plan pages

- Public plan explainers are available at `/free-features` and `/premium-features`.
- The homepage quick-info card links to those routes through compact `Free Feats` and `Premium Feats` rows.
- The premium page is public and indexable, but it only shows live Stripe purchase actions after auth/profile checks confirm a signed-in account and available billing plans.

## SEO landing routes

- Public intent landing pages cover commercial search intents:
  - `/pdf-to-fillable-form`
  - `/pdf-to-database-template`
  - `/fill-pdf-from-csv`
  - `/fill-pdf-by-link`
  - `/fill-information-in-pdf`
  - `/fillable-form-field-name`
- Industry-specific SEO routes are available for:
  - `/healthcare-pdf-automation`
  - `/acord-form-automation`
  - `/insurance-pdf-automation`
  - `/real-estate-pdf-automation`
  - `/government-form-automation`
  - `/finance-loan-pdf-automation`
  - `/hr-pdf-automation`
  - `/legal-pdf-workflow-automation`
  - `/education-form-automation`
  - `/nonprofit-pdf-form-automation`
  - `/logistics-pdf-automation`
- Each route has unique canonical metadata and FAQ structured data.
- Selected workflow routes and docs pages can also surface embedded YouTube walkthroughs when a focused demo adds search-intent context without bloating the homepage.
- Authority-style intent routes can also render inline legal footnotes and explicit source sections when the page needs statute or policy references instead of summary-only marketing copy.
- Two hub routes aggregate intent pages for cleaner global navigation:
  - `/workflows` lists workflow-intent pages.
  - `/industries` lists industry-intent pages.
- Hub routes are part of the build-time static HTML and sitemap generation, so direct requests should serve route-specific HTML before React loads.

## Data source behavior

- CSV/Excel/JSON imports parse schema headers and rows.
- Fill By Link respondent submissions are stored as structured records and can be re-used through the same Search & Fill flow in the workspace.
- TXT imports are schema-only (headers/types, no rows).
- Schema metadata can be persisted to `/api/schemas` for mapping.
- Search & Fill now fails closed when the selected record does not line up with any PDF field names. The dialog stays open and warns the user instead of silently saving an unchanged document.
- OpenAI confirmations warn before sending PDF/schema content; row values and field values are not included in OpenAI rename/map requests.
- Rename and Map can change the template definition. When they do, the workspace clears current field inputs so stale filled values cannot remain attached to renamed or remapped fields.

## Fill By Link

- Fill By Link is a native DullyPDF workflow that starts from either a saved template or an open saved-form group and publishes a public `/respond/:token` route.
- The question builder derives public questions from respondent-facing PDF fields, but explicit PDF radio widgets stay grouped as one single-choice question and PDF signature widgets are excluded from the public form because signature capture belongs to the signing workflow.
- Template links can now optionally enable `Require signature after submit`. In that mode, the public Fill By Link still collects respondent answers first, but the published form excludes signature-ceremony-managed questions and uses the signer email entered on the form to start the existing public `/sign/:token` ceremony by email after submit. The publish flow now requires a visible signer-email question, and consumer-mode post-submit signing also requires request-specific paper-copy, fee, withdrawal, and contact-update disclosures before publish succeeds. Owners can also mark the post-submit request as company-binding so the final signer step must collect a representative title, company name, and explicit authority attestation. The public submit path rejects the response up front if the mapped signer email is missing or invalid.
- Signing adds a separate public `/sign/:token` route for owner-created signing requests. Owners can save a signing draft, review the source hash/version, and send `Sign`-mode requests after the frontend materializes the current workspace state into a flattened immutable PDF snapshot and the backend stores that exact non-editable source artifact. Milestone 5 extends the same immutable boundary to `Fill and Sign`: reviewed Search & Fill data and stored Fill By Link respondent records now freeze through the existing `/api/forms/materialize` path, `fill_link_response` provenance is stored on the signing request when available, and the owner must explicitly confirm that the current filled PDF is the exact record to freeze before send. The signing dialog now supports one-recipient manual entry, pasted TXT/CSV batches, and uploaded `.txt` / `.csv` recipient files, with invalid rows called out before drafts are saved. Multi-signer envelopes expose three routing modes: `Separate` for isolated per-signer requests, `Parallel` for one shared document sent to all signers immediately, and `Sequential` for one shared document where only the active signer is emailed and later signers stay queued until the prior signer completes.
- The owner signing dialog also has a dedicated `Responses` tab for the active document. It summarizes waiting vs signed requests, highlights manual follow-up cases when invite delivery is unavailable, shows when a signer link has expired, lets the owner revoke/cancel unsatisfied requests, and exposes source-PDF, signed-form, audit-receipt, and full dispute-package downloads directly from the workspace. Sequential envelope recipients that have not been activated yet stay visible as `Waiting for turn`; their copy-link and reissue controls stay hidden until their turn is activated, and the final signed-PDF / audit artifacts remain locked until the whole envelope completes.
- Template Fill By Link `Responses` now surface linked signing state too. When a response completes the post-submit signing path, the owner can download the signed PDF, audit receipt, or the same owner-only full dispute package directly from that response row instead of relying on the respondent completion screen.
- Milestone 3 turned the public route into a real signer ceremony: business requests go through review -> adopt signature -> explicit finish, consumer requests insert a separate e-consent step first, and every action is tied to the immutable PDF hash plus a public signing session. The signer-facing adopt step now supports four signature modalities for the rendered signature mark: typed name, default legal name, drawn signature, and uploaded signature image. Consumer-mode source previews stay locked until e-consent succeeds, consumer consent now requires an access-check PDF plus access code before the signer can proceed, signers can withdraw consent before completion, public sessions are bound to the bootstrap client fingerprint, and sent requests expire after the configured request TTL instead of staying live indefinitely. Every emailed signing request source now adds one more gate before that ceremony begins: the signer must request and verify a 6-digit email OTP from `/sign/:token` before the immutable PDF, manual fallback action, or signing actions are exposed. The verify action now reads the visible OTP input value directly so browser or OS one-time-code autofill still submits even when the controlled React state lags behind the DOM for a moment. The immutable review step also keeps the PDF viewer inside its own fixed-height scroll region and renders numbered ghost `Sign here` placeholders for the current signer on every assigned signature page, so multi-page packets can scroll cleanly without losing later-page signature targets. Phase 4 now stores the exact consumer disclosure package shown to the signer, the disclosure hash, the first-presented timestamp, the sender contact details, and the access-demonstration evidence instead of treating consent as a single timestamp. The signer-facing route now shows sender identity/contact explicitly and only mentions an on-page manual fallback control when that control is actually enabled for the request. Company-binding requests add one more final-step capture: the signer must enter a representative title, company name, and explicit authority attestation, and DullyPDF stores that attestation alongside the rest of the completion evidence without claiming to independently verify corporate authority. Milestone 4 completes the artifact loop so a finished request now stores a signed PDF, a KMS-sealed audit-manifest envelope, and a human-readable audit receipt; the public completion page exposes signer downloads for the signed PDF and audit receipt while owner APIs expose the full artifact set. When a PDF signing identity is configured, DullyPDF also embeds a cryptographic PDF signature directly into that completed PDF so Adobe-style validators can inspect the signed artifact without relying only on the audit receipt. Those completed downloads now stay behind the same bound signing session and verification gate instead of behaving like naked bearer links. Completed records also expose a public `/verify-signing/:token` validation page, and the audit receipt now carries that validation URL as both text and QR so recipients can re-check the retained record outside the live signing flow. The public receipt now redacts signer email/IP/user-agent evidence, leaving the owner-only audit manifest as the detailed audit record. Product scope is still intentionally narrower than "all U.S. e-signatures": excluded categories, regulated signature programs, and jurisdiction-specific consumer/document rules require separate policy review before DullyPDF should claim support.
- The owner audit record is intentionally richer than the public receipt. It preserves request/document identifiers, immutable source and signed hashes, sender/signer identity fields, invite provider and delivery metadata, OTP and access-check state, ceremony timestamps (opened, reviewed, consented, signature adopted, completed), signature-adoption details, retained artifact paths, and digital-signature metadata. Company-binding requests also store the attestation text/version/hash plus the signer-provided representative title, company name, and attested-at timestamp. For consumer-mode requests it also stores the exact disclosure payload/hash, the first-presented timestamp, the consent scope, and the access-demonstration evidence.
- This evidence model is designed to line up with the core E-SIGN hooks in 15 U.S.C. § 7001: intent to sign, logical association of the signature with the exact record, consumer disclosures and affirmative consent where required, and retention in a form that can be accurately reproduced later. That is an alignment statement, not a blanket legal determination for every document class or jurisdiction.
- Signing compliance note: DullyPDF does not auto-classify PDFs into legal document categories. The sender chooses the document category and is responsible for using a supported category instead of sending excluded document classes through the signing flow. Business mode is the ordinary-business path with lighter disclosure copy; consumer mode is the stronger ceremony with disclosure, access-check, and consent evidence. Company-binding mode records only the signer’s authority attestation and representative fields; it does not independently verify that the signer actually had authority to bind the entity. Notarial or acknowledgment workflows remain intentionally out of scope in DullyPDF v1 even if a separate jurisdiction-specific e-notary path could support them elsewhere.
- Development-signature note: local/dev signing often uses DullyPDF's bundled self-signed test certificate when no production PKCS#12 or Cloud KMS signing identity is configured. PDF viewers may therefore show the embedded certificate as untrusted even though the signed PDF still carries a cryptographic tamper-evident seal. In that mode, the intended trust path is DullyPDF's retained audit evidence: the immutable source PDF, signed PDF, audit receipt, and public `/verify-signing/:token` validation page. That combination can still be sufficient for many internal or ordinary-business workflows, but it is not the same thing as a publicly trusted CA-backed certificate.
- Group Fill By Link merges every distinct respondent-facing field across the group into one HTML form while individual template links remain available.
- Editing the membership of a group closes its active group Fill By Link so the owner must reopen it against the updated group schema.
- Respondents fill a DullyPDF-hosted HTML form, not the PDF itself.
- The owner dialog is now a large web-form builder with global settings, searchable question management, live preview, and a separate responses tab.
- The owner Fill By Link dialog ignores outside clicks so in-progress builder work is not lost by accidental backdrop taps; `Escape` and the explicit close control still dismiss it.
- The owner signing dialog ignores outside clicks so draft request progress is not lost by accidental backdrop taps; `Escape` and the explicit close control still dismiss it.
- Owners can set global defaults such as `Require all visible questions`, form intro text, a default text character limit, and template-only respondent PDF behavior. Respondent PDF downloads stay `Flat PDF` by default so submitted values are baked into page content, and template links can opt into `Editable PDF` downloads when preserving form widgets is more important than a receipt-style copy. If post-submit signing is enabled, respondent downloads are forced back to `Flat PDF` so the response snapshot used for signing never exposes an editable public artifact.
- Template links can add custom web-form questions (`text`, `textarea`, `date`, `checkbox`, `radio`, `select`, `email`, `phone`) while group links currently work from the merged PDF-derived field set only.
- When post-submit signing is enabled for a template link, the owner must choose which visible question supplies the signer's full name and which visible email question receives the signing invite. Those mapped signer-identity questions are automatically treated as required while signing stays enabled. The builder now also shows a compact readiness summary for those mappings, the selected category, the e-sign attestation, company-binding mode, consumer disclosures when required, whether the template still contains usable signature anchors before publish, and a small warning that existing saved PDF field values can still carry into the frozen signer copy when the web form does not overwrite them. The backend creates the signing request from the stored response snapshot, materializes the immutable filled PDF server-side, then sends the signing invite to the mapped signer email instead of returning a live signer link to the current browser. Once the signer opens that emailed `/sign/:token` route, the first step is email verification for that session, just like the owner-created email-signing flow.
- If that email delivery fails transiently, the respondent success screen now exposes a resend action that reuses the stored Fill By Link response instead of asking them to refill the form. When the response already has a sent/completed retained signing request, resend can keep using that retained request even after the owner later deletes or loses the source saved form; only draft/new requests become unavailable and those now show a sender-contact message instead of an endless retry prompt.
- Owners review stored respondent submissions inside the workspace and materialize the final PDF only when they select a respondent and run Search & Fill against the target template or group. Template links can also optionally expose a post-submit PDF download for the respondent's own submitted copy, with a publish-time choice between the flat default and an editable-with-fields variant.
- Tier messaging exposed in the marketing/docs surface now covers the full enforced defaults instead of only Fill By Link copy. Free defaults are 5 saved forms, 5 detect pages, 50 fillable pages, unlimited active Fill By Links with 25 accepted responses/month across the account, 1 API Fill endpoint with 250 successful fills/month and 25 pages/request, 25 sent signing requests/month, and a base OpenAI pool that tops back up to 10 each month when the balance is below 10. Premium defaults are 100 saved forms, 100 detect pages, 1,000 fillable pages, unlimited active Fill By Links with 10,000 accepted responses/month across the account, 20 API Fill endpoints with 10,000 successful fills/month and 250 pages/request, 10,000 sent signing requests/month, and a 500-credit monthly pool before refill packs.

## Auth and profile

- Firebase auth supports email/password, Google, and GitHub.
- Password users must verify email before editor access.
- The lightweight homepage shell keeps signed-in users on the marketing shell until they explicitly open workflow/profile, then waits for `/api/health` before mounting the runtime so Cloud Run scale-from-zero shows a startup screen instead of background profile/groups/saved-form failures on page load.
- Saved-form and saved-group workspace routes survive refresh. The runtime stores a small session-scoped resume manifest for the active saved form/group route so it can restore page/zoom and opportunistically reuse existing backend session ids after reload.
- Ad hoc `/ui` workspaces can also survive reload when they already have a live detect/mapping session. The frontend restores the workspace by re-downloading the session PDF from the backend, then rebuilding fields and mapping rules from the server-side session snapshot instead of relying on browser-local PDF persistence.
- The resume manifest is not a full offline cache. It never stores PDF bytes or unsaved field edits locally. Saved forms/groups still rehydrate from backend data plus the saved editor snapshot, and ad hoc `/ui` restores only work while the backing session still exists.
- Detection timeout no longer forces a zero-field editor for slow scans. When the foreground poll budget expires before CommonForms finishes and there are no embedded fields to use yet, the runtime stays in the processing view and keeps polling until the backend returns fields or a terminal failure.
- Firebase email action links land on the branded `/account-action` handler, which applies email verification codes and handles password reset flows before returning users to the app.
- Verification success now routes back through `/upload` and stores a short-lived onboarding marker in that browser, so newly verified password accounts resume the free-vs-trial onboarding choice even if Firebase makes them sign in again before the workspace can reopen.
- Legacy `/verify-email` links still normalize into `/account-action` so older emails continue working.
- Verification email resend is throttled in the UI (60-second cooldown, max 5 sends per day per account on that browser).
- Profile view shows the full enforced limit set, including PDF page caps, saved-form/storage caps, Fill By Link caps, API Fill caps, signing limits, credits, Stripe billing/subscription status, and template-access lock state when applicable. When a downgraded base account has locked saved forms, the retention summary also calls out how many signing drafts are blocked from send until the owner upgrades again, while sent/completed signing requests tied to those forms stay retained.
- On mobile, profile browsing remains available, but the workspace stays on the marketing/mobile-safe shell below the 900px breakpoint. Direct `/upload`, `/ui`, `/ui/forms/*`, and `/ui/groups/*` routes therefore fall back to the homepage shell instead of mounting the runtime, and resizing an active desktop workspace below 900px hides the editor until the viewport is widened again.
- When a Pro account downgrades to free and exceeds the free saved-form cap, the profile payload includes a compatibility retention summary that now describes lock-based access instead of deletion. The backend keeps the oldest-created saved forms up to the base cap accessible, marks the rest locked in place, and automatically reopens downgrade-managed Fill By Link records when the source template becomes accessible again after an upgrade.

## Demo and fixtures

- Demo assets are served from `frontend/public/demo`.
- Demo sessions allow downloading the generated PDF without signing in; saving to profile remains sign-in only.
- Mobile homepage walkthrough is marketing/demo only, but it now explains template prep, native Fill By Link intake, extraction from images/documents, final fill review, and the supported U.S. e-sign handoff.
- Small tracked fixtures live in `quickTestFiles/`; larger local datasets live in `samples/`.
- Regenerate demo rename/remap name maps from the repo root with `npm run demo:generate-name-maps`.

## Out of scope

- Full PDF content editing beyond form fields/overlays.
- Search & Fill from TXT uploads.
- Full offline persistence of workspace state beyond the saved-form/group resume manifest.
