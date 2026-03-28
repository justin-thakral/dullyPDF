# Frontend Docs

- `overview.md` - Product scope, end-to-end workflow, saved-form group behavior, public docs/SEO routes, and Fill By Link respondent flow.
- `running.md` - Local startup, env files, script entrypoints, and public route testing notes.
- `structure.md` - Current `src` layout and key modules.
- `app-hooks.md` - How `App.tsx` composes extracted hooks.
- `api-routing.md` - Same-origin `/api/*` calls vs direct backend calls.
- `api.md` - Implementation guide for the saved-template `API Fill` product surface, request contract, and rollout guardrails.
- `field-editing.md` - Overlay, inspector, and fill behavior.
- `styling.md` - Tokens, stylesheet modules, and typography rules.
- `usage-docs.md` - Public `/usage-docs/*` information architecture and page layout notes.
- `seo-operations.md` - Weekly SEO operations, query tuning, and authority growth workflow.

Customer-facing pricing or limit changes should also update the homepage copy, `publicRouteSeoData.mjs`, `intentPages.ts`, usage docs content, and root/frontend README surfaces in the same branch.
Public plan-route changes should stay aligned across `/free-features`, `/premium-features`, homepage quick-info links, route SEO, and build-time static route generation.
Customer-facing feature launches should keep public docs aligned across `/usage-docs/*`, intent pages, and the shared public route SEO source in `frontend/src/config/publicRouteSeoData.mjs`. `scripts/seo-route-data.mjs` is only a build-time bridge.
