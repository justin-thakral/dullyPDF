# Usage Docs Pages

The frontend exposes public usage documentation under `/usage-docs/*` as the canonical docs URL
family. Legacy `/docs/*` URLs are retained only for compatibility and redirect to `/usage-docs/*`
with HTTP 301 on Firebase hosting.

These routes are handled in `src/main.tsx` without React Router so they remain lightweight and
consistent with existing legal-page routing.

## Routes

- `/usage-docs` -> overview
- `/usage-docs/getting-started`
- `/usage-docs/detection`
- `/usage-docs/rename-mapping`
- `/usage-docs/editor-workflow`
- `/usage-docs/search-fill`
- `/usage-docs/save-download-profile`
- `/usage-docs/troubleshooting`
- `/docs/*` permanently redirects to the matching `/usage-docs/*` path

Unknown slugs (for example `/usage-docs/typo`) are treated as not found:
- Firebase hosting returns a true 404 page (`frontend/public/404.html`) for unknown `/usage-docs/*` paths.
- Client-side fallback rendering (for local/dev rewrite behavior) uses `UsageDocsNotFoundPage` and applies `noindex,follow`.

## Files

- `src/components/pages/usageDocsContent.tsx`: route/page catalog + section content.
- `src/components/pages/UsageDocsPage.tsx`: docs page shell, sidebar, and section rendering.
- `src/components/pages/UsageDocsPage.css`: responsive layout and typography.
- `src/components/pages/UsageDocsNotFoundPage.tsx`: client-side docs 404 fallback page with noindex SEO metadata.
- `src/components/pages/UsageDocsNotFoundPage.css`: docs 404 fallback styling.

## Navigation model

- Header-level nav now uses a single entry button (`Docs & Privacy & Terms`) that lands on `/usage-docs`.
- In-page top nav on docs/legal pages provides movement between Home, Usage Docs, Privacy, and Terms.
- Sidebar includes:
  - `Pages`: jump between docs routes.
  - `On this page`: anchor links to section IDs in the active route.

## Billing and credits coverage

- The public docs now describe bucketed OpenAI credit pricing:
  - `totalCredits = baseCost * ceil(pageCount / bucketSize)`
  - Current defaults documented in UI/docs: `bucketSize=5`, base costs `Rename=1`, `Remap=1`, `Rename+Map=2`.
- The `Save / Download` docs page includes Stripe billing plan behavior from Profile:
  - `pro_monthly` and `pro_yearly` are recurring subscriptions with labels/pricing sourced from backend Stripe metadata
  - `refill_500` (Pro-only) is a one-time credit refill with label/pricing sourced from backend Stripe metadata
  - checkout and payment transactions are processed securely via Stripe Checkout.
  - subscription linkage/status + cancellation schedule metadata from backend profile state.
  - refill-credit retention across downgrades/upgrades.

## Responsive behavior

- Desktop/tablet: two-column layout with sticky sidebar.
- Small screens: sidebar moves above content and page links become an adaptive grid.
- Content containers enforce `min-width: 0` and use wrapping rules to prevent horizontal overflow.

## Entry points

- Desktop non-editor header includes one `Docs & Privacy & Terms` button that routes to `/usage-docs`.
- Mobile homepage CTA stack includes one `Docs & Privacy & Terms` button that routes to `/usage-docs`.
