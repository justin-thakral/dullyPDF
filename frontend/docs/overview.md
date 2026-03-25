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
- The docs include dedicated pages for detection, rename/mapping, editor workflow, Search & Fill, Fill By Link, signature workflow, API Fill, Create Group workflows, save/download/Profile behavior, and troubleshooting.
- Route handling lives in `frontend/src/main.tsx` alongside legal page route handling.
- Unknown public URLs should resolve to a noindex 404 experience instead of falling back to the app homepage.

## Workspace routing

- `/` is the marketing shell only.
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
- Two hub routes aggregate intent pages for cleaner global navigation:
  - `/workflows` lists workflow-intent pages.
  - `/industries` lists industry-intent pages.
- Hub routes are part of the build-time static HTML and sitemap generation, so direct requests should serve route-specific HTML before React loads.

## Data source behavior

- CSV/Excel/JSON imports parse schema headers and rows.
- Fill By Link respondent submissions are stored as structured records and can be re-used through the same Search & Fill flow in the workspace.
- TXT imports are schema-only (headers/types, no rows).
- Schema metadata can be persisted to `/api/schemas` for mapping.
- OpenAI confirmations warn before sending PDF/schema content; row values and field values are not included in OpenAI rename/map requests.

## Fill By Link

- Fill By Link is a native DullyPDF workflow that starts from either a saved template or an open saved-form group and publishes a public `/respond/:token` route.
- Template links can now optionally enable `Require signature after submit`. In that mode, the public Fill By Link still collects respondent answers first, but the published form excludes signature-ceremony-managed questions and hands the respondent off to the existing public `/sign/:token` ceremony after submit. The publish flow now requires a visible signer-email question, and the public submit path rejects the response up front if that answer is missing or not a valid email address.
- Signing adds a separate public `/sign/:token` route for owner-created signing requests. Owners can save a signing draft, review the source hash/version, and send `Sign`-mode requests after the frontend materializes the current workspace state into an immutable PDF snapshot and the backend stores that exact source. Milestone 5 extends the same immutable boundary to `Fill and Sign`: reviewed Search & Fill data and stored Fill By Link respondent records now freeze through the existing `/api/forms/materialize` path, `fill_link_response` provenance is stored on the signing request when available, and the owner must explicitly confirm that the current filled PDF is the exact record to freeze before send. The signing dialog now supports one-recipient manual entry, pasted TXT/CSV batches, and uploaded `.txt` / `.csv` recipient files, with invalid rows called out before drafts are saved.
- The owner signing dialog also has a dedicated `Responses` tab for the active document. It summarizes waiting vs signed requests, highlights manual follow-up cases when invite delivery is unavailable, and exposes source-PDF, signed-form, and audit-receipt downloads directly from the workspace.
- Template Fill By Link `Responses` now surface linked signing state too. When a response completes the post-submit signing path, the owner can download the signed PDF and audit receipt directly from that response row instead of relying on the respondent completion screen.
- Milestone 3 turned the public route into a real signer ceremony: business requests go through review -> adopt signature -> explicit finish, consumer requests insert a separate e-consent step first, and every action is tied to the immutable PDF hash plus a public signing session. Milestone 4 completes the artifact loop so a finished request now stores a signed PDF, a KMS-sealed audit-manifest envelope, and a human-readable audit receipt; the public completion page exposes signer downloads for the signed PDF and audit receipt while owner APIs expose the full artifact set.
- Group Fill By Link merges every distinct respondent-facing field across the group into one HTML form while individual template links remain available.
- Editing the membership of a group closes its active group Fill By Link so the owner must reopen it against the updated group schema.
- Respondents fill a DullyPDF-hosted HTML form, not the PDF itself.
- The owner dialog is now a large web-form builder with global settings, searchable question management, live preview, and a separate responses tab.
- Owners can set global defaults such as `Require all visible questions`, form intro text, a default text character limit, and template-only respondent PDF behavior. Respondent PDF downloads stay `Flat PDF` by default so submitted values are baked into page content, and template links can opt into `Editable PDF` downloads when preserving form widgets is more important than a receipt-style copy. If post-submit signing is enabled, respondent downloads are forced back to `Flat PDF` so the response snapshot used for signing never exposes an editable public artifact.
- Template links can add custom web-form questions (`text`, `textarea`, `date`, `checkbox`, `radio`, `select`, `email`, `phone`) while group links currently work from the merged PDF-derived field set only.
- When post-submit signing is enabled for a template link, the owner must map a signer name question and signer email question. The backend creates the signing request from the stored response snapshot, materializes the immutable filled PDF server-side, then returns a signing handoff payload so the respondent can continue directly into `/sign/:token`.
- If that handoff fails transiently, the respondent success screen now exposes a retry action that reuses the stored Fill By Link response instead of asking them to refill the form.
- Owners review stored respondent submissions inside the workspace and materialize the final PDF only when they select a respondent and run Search & Fill against the target template or group. Template links can also optionally expose a post-submit PDF download for the respondent's own submitted copy, with a publish-time choice between the flat default and an editable-with-fields variant.
- Tier messaging exposed in the marketing/docs surface is: free = 1 active link and 5 accepted responses, premium = a shareable link on every saved template and up to 10,000 responses per link.

## Auth and profile

- Firebase auth supports email/password, Google, and GitHub.
- Password users must verify email before editor access.
- The lightweight homepage shell keeps signed-in users on the marketing shell until they explicitly open workflow/profile, then waits for `/api/health` before mounting the runtime so Cloud Run scale-from-zero shows a startup screen instead of background profile/groups/saved-form failures on page load.
- Saved-form and saved-group workspace routes survive refresh. The runtime stores a small session-scoped resume manifest for the active saved form/group route so it can restore page/zoom and opportunistically reuse existing backend session ids after reload.
- The resume manifest is not a full offline cache. It never stores PDF bytes, unsaved uploads, or unsaved field edits, and the saved form/group still rehydrates from backend data plus the saved editor snapshot.
- Firebase email action links land on the branded `/account-action` handler, which applies email verification codes and handles password reset flows before returning users to the app.
- Legacy `/verify-email` links still normalize into `/account-action` so older emails continue working.
- Verification email resend is throttled in the UI (60-second cooldown, max 5 sends per day per account on that browser).
- Profile view shows limits, credits, Stripe billing/subscription status, saved forms, and Fill By Link pricing/limit messaging.
- On mobile, profile browsing remains available, but reopening saved forms is desktop-only so the editor never loads below the 900px mobile breakpoint. Direct `/ui/forms/*` and `/ui/groups/*` refreshes therefore fall back to the marketing/mobile-safe shell below the 900px breakpoint instead of mounting the editor.
- When a Pro account downgrades to free and exceeds the free saved-form cap, the profile payload includes a downgrade-retention summary. The UI opens a warning dialog on each site visit, lets the owner swap which saved forms remain, and keeps the queued set for 30 days before purge unless Pro is reactivated or the owner chooses delete-now.

## Demo and fixtures

- Demo assets are served from `frontend/public/demo`.
- Demo sessions allow downloading the generated PDF without signing in; saving to profile remains sign-in only.
- Mobile homepage walkthrough is marketing/demo only, but it now explains the native Fill By Link path alongside local Search & Fill.
- Small tracked fixtures live in `quickTestFiles/`; larger local datasets live in `samples/`.
- Regenerate demo rename/remap name maps from the repo root with `npm run demo:generate-name-maps`.

## Out of scope

- Full PDF content editing beyond form fields/overlays.
- Search & Fill from TXT uploads.
- Full offline persistence of workspace state beyond the saved-form/group resume manifest.
