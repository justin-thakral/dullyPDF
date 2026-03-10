# Git And Documentation Workflow

Use one focused branch per feature, avoid reverting unrelated work, and ship customer-facing copy updates in the same branch as the feature when limits, pricing, or public routes change.

## Required docs surfaces for customer-facing changes

When a feature changes product messaging, pricing, limits, or public workflows, update these surfaces together:

- Root `README.md`
- `frontend/README.md`
- `frontend/docs/README.md`
- `frontend/docs/overview.md`
- `frontend/docs/running.md`
- Homepage marketing copy
- `frontend/src/config/routeSeo.ts`
- `frontend/src/config/intentPages.ts`
- `frontend/src/components/pages/usageDocsContent.tsx`

## Fill By Link checklist

When Fill By Link behavior changes, verify these points before merging:

- Homepage copy still explains the native DullyPDF-hosted HTML form workflow.
- Free and premium caps match the product decision everywhere they are exposed.
- Usage docs still describe respondent storage, owner selection flow, and saved-template dependency.
- SEO metadata and intent pages still reflect the current Fill By Link positioning.
- Mobile landing/demo copy still explains Fill By Link even though the full editor is desktop-only.

## Public route notes

- Public documentation and intent pages should stay indexable when they represent canonical marketing content.
- Public respondent routes such as `/respond/:token` should remain non-indexable because they are user-specific workflow endpoints.
- If a new public route is added, decide in the same branch whether it belongs in sitemap/static rendering, a canonical landing page, or a noindex workflow route.
