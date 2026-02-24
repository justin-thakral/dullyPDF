# Usage Docs Pages

The frontend exposes public usage documentation under `/usage-docs/*` (with `/docs/*` aliases).
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
- `/docs/*` mirrors the same page slugs

Unknown slugs (for example `/usage-docs/typo`) fall back to the overview page and show a warning.

## Files

- `src/components/pages/usageDocsContent.tsx`: route/page catalog + section content.
- `src/components/pages/UsageDocsPage.tsx`: docs page shell, sidebar, and section rendering.
- `src/components/pages/UsageDocsPage.css`: responsive layout and typography.

## Navigation model

- Header-level nav links (Home, Usage Docs, Privacy, Terms) provide global movement.
- Sidebar includes:
  - `Pages`: jump between docs routes.
  - `On this page`: anchor links to section IDs in the active route.

## Billing and credits coverage

- The public docs now describe bucketed OpenAI credit pricing:
  - `totalCredits = baseCost * ceil(pageCount / bucketSize)`
  - Current defaults documented in UI/docs: `bucketSize=5`, base costs `Rename=1`, `Remap=1`, `Rename+Map=2`.
- The `Save / Download` docs page includes Stripe billing plan behavior from Profile:
  - `pro_monthly` and `pro_yearly` labels/pricing sourced from backend Stripe metadata
  - `refill_500` (Pro-only) label/pricing sourced from backend Stripe metadata
  - subscription linkage/status + cancellation schedule metadata from backend profile state.
  - refill-credit retention across downgrades/upgrades.

## Responsive behavior

- Desktop/tablet: two-column layout with sticky sidebar.
- Small screens: sidebar moves above content and page links become an adaptive grid.
- Content containers enforce `min-width: 0` and use wrapping rules to prevent horizontal overflow.

## Entry points

- Desktop non-editor header adds `Usage Docs` button before `Privacy & Terms`.
- Mobile homepage CTA stack adds a white `Usage Docs` button below `Privacy & Terms`.
