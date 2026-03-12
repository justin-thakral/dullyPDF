# Overview

The frontend is a React + TypeScript app for loading PDFs, editing fields, organizing saved forms into named groups, publishing native Fill By Link forms for either one saved template or an open group, and filling records from local data sources or stored respondent submissions. It connects to the FastAPI backend for detection, OpenAI rename/mapping, profile data, saved forms, template groups, and Fill By Link owner/respondent flows.

## Main workflow

1. Load a PDF (detection upload, fillable upload, saved form, or a saved-form group that opens the alphabetically first template first).
2. Detect fields with CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) via `/detect-fields`, or import embedded AcroForm widgets.
3. Optionally run OpenAI rename and schema mapping.
4. Edit fields in overlay/list/inspector panels.
5. Save the template, optionally add it to a named saved-form group, then either publish a native Fill By Link for the active template or publish one merged Fill By Link for the open group before loading local CSV/Excel/JSON rows.
6. Reopen templates from the upload screen through the saved-form browser, which supports group filtering, an `Open groups` toggle, inline group deletion, and a stable selected-group label while the group list refreshes.
7. When a group is open, switch between member templates from the header and run batch Rename + Map across every saved form in that group.
8. Run Search & Fill from CSV/Excel/JSON rows or stored Fill By Link respondent records.
9. Download a filled PDF or save it to the signed-in profile.
10. Persist and replay deterministic fill rules (`fillRules`) including text split/join transforms.
11. Persist a versioned saved-form editor snapshot so reopened templates and group switches can hydrate fields/page sizes without re-extracting them on every open.

## Public usage docs

- End-user documentation is available at canonical `/usage-docs/*` URLs.
- Legacy `/docs/*` URLs are compatibility redirects (HTTP 301) to `/usage-docs/*`.
- Canonical style is non-trailing slash for non-root routes; `/path/` should only 301 once to `/path` (never loop).
- The docs include dedicated pages for detection, rename/mapping, editor workflow, Search & Fill, Fill By Link, Create Group workflows, save/download/Profile behavior, and troubleshooting.
- Route handling lives in `frontend/src/main.tsx` alongside legal page route handling.
- Unknown public URLs should resolve to a noindex 404 experience instead of falling back to the app homepage.

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
- Group Fill By Link merges every distinct respondent-facing field across the group into one HTML form while individual template links remain available.
- Editing the membership of a group closes its active group Fill By Link so the owner must reopen it against the updated group schema.
- Respondents fill a DullyPDF-hosted HTML form, not the PDF itself.
- Owners can optionally require every public question before DullyPDF accepts a submission.
- Owners review stored respondent submissions inside the workspace and materialize the final PDF only when they select a respondent and run Search & Fill against the target template or group. Template links can also optionally expose a post-submit PDF download for the respondent's own submitted copy.
- Tier messaging exposed in the marketing/docs surface is: free = 1 active link and 5 accepted responses, premium = a shareable link on every saved template and up to 10,000 responses per link.

## Auth and profile

- Firebase auth supports email/password, Google, and GitHub.
- Password users must verify email before editor access.
- The lightweight homepage shell keeps signed-in users on the marketing shell until they explicitly open workflow/profile, then waits for `/api/health` before mounting the runtime so Cloud Run scale-from-zero shows a startup screen instead of background profile/groups/saved-form failures on page load.
- Firebase email action links land on the branded `/account-action` handler, which applies email verification codes and handles password reset flows before returning users to the app.
- Legacy `/verify-email` links still normalize into `/account-action` so older emails continue working.
- Verification email resend is throttled in the UI (60-second cooldown, max 5 sends per day per account on that browser).
- Profile view shows limits, credits, Stripe billing/subscription status, saved forms, and Fill By Link pricing/limit messaging.
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
- Offline persistence (state is session-scoped unless saved).
