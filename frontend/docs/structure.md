# Source Structure

```text
frontend/
  src/
    App.tsx
    App.css
    main.tsx
    index.css
    components/
      demo/
      features/
      layout/
      panels/
      pages/
      ui/
      viewer/
    hooks/
    services/
    config/
    styles/
    types/
    utils/
```

## Key files and directories

- `frontend/src/App.tsx`: Top-level shell that keeps `/` on the marketing homepage, auto-starts the runtime for `/upload` and `/ui*` workspace routes, and owns browser history synchronization between the lightweight shell and the runtime.
- `frontend/src/WorkspaceRuntime.tsx`: Main signed-in runtime that renders upload/processing/editor/profile/auth states and now coordinates direct route restore for saved forms/groups.
- `frontend/src/workspaceLazyComponents.tsx`: Lazy import registry for large runtime-only screens/dialogs so `WorkspaceRuntime` stays orchestration-focused and does not pull every rarely used UI island into one chunk.
- `frontend/src/utils/workspaceRoutes.ts`: Parser/builder helpers for workspace browser routes (`/upload`, `/ui`, `/ui/profile`, `/ui/forms/:id`, `/ui/groups/:id?template=:id`).
- `frontend/src/utils/workspaceResumeState.ts`: Session-scoped resume manifest helpers for restoring saved-form/group routes after refresh without persisting full document state locally.
- `frontend/src/hooks/`: App feature hooks extracted from `App.tsx` (`useAuth`, `useSavedForms`, `useDetection`, `useOpenAiPipeline`, `useDataSource`, `usePipelineModal`, `useSaveDownload`, `useDemo`, `useFieldHistory`, `useFieldState`, `useDialog`, `useGroupTemplateCache`).
- `frontend/src/services/apiConfig.ts`: Shared fetch wrapper, auth headers, status normalization, and API base URL resolution.
- `frontend/src/services/api.ts`: Profile/contact/recaptcha, schema persistence, OpenAI endpoints, saved forms, materialize/download operations.
- `frontend/src/services/detectionApi.ts`: Detection upload + polling (`/detect-fields`) and detection-session keep-alive.
- `frontend/src/config/intentPages.ts`: Content + FAQ + SEO metadata config for public intent and industry landing routes.
- `frontend/src/config/publicRouteSeoData.mjs`: Shared source of truth for public route metadata and build-time static body content used by the runtime SEO adapter plus the static HTML and sitemap generators.
- `frontend/src/config/routeSeo.ts`: Typed runtime adapter over the shared public route SEO dataset for all indexable public pages (`/`, legal, `/usage-docs/*`, intent pages, hub pages, and blog routes).
- `frontend/src/utils/seo.ts`: Head-tag applier for title, description, canonical, Open Graph, and Twitter metadata from the shared SEO map.
- `frontend/src/components/viewer/PdfViewer.tsx`: PDF canvas rendering and overlay mounting.
- `frontend/src/components/panels/FieldListPanel.tsx`: Field list, page navigation, filter/search, and display toggles.
- `frontend/src/components/panels/FieldInspectorPanel.tsx`: Selected-field metadata/geometry editing, create/delete actions, undo/redo controls.
- `frontend/src/components/features/SearchFillModal.tsx`: Record search and field fill logic.
- `frontend/src/components/features/UploadView.tsx`: Upload + saved-form selection UI and OpenAI preflight modal entry.
- `frontend/src/components/pages/*.tsx`: Homepage, auth pages, profile page, legal pages, public usage docs pages (`/usage-docs/*`), and intent landing pages.
- `frontend/src/components/pages/IntentLandingPage.tsx`: Shared renderer for workflow/industry authority pages, including long-form article sections, FAQ blocks, related docs, optional source panels, and inline legal-footnote rendering for authority-heavy pages.
- `frontend/src/components/pages/AccountActionPage.tsx`: Public branded Firebase email action handler for verification and password reset links (`/account-action`, with legacy `/verify-email` compatibility).
- `frontend/src/components/pages/AuthActionShell.tsx`: Shared branded shell used by the public account-action route and the signed-in verification gate.
- `frontend/src/components/pages/PublicNotFoundPage.tsx`: Generic noindex 404 page for unknown public routes that should never fall back to the editor shell.
- `frontend/src/components/pages/IntentHubPage.tsx`: Hub directory pages for `/workflows` and `/industries` that aggregate intent routes.
- `frontend/src/components/pages/IntentPageShell.tsx`: Shared shell for intent marketing pages (global header nav, breadcrumb + hero/CTA block, and footer).
- `frontend/src/config/appConstants.tsx`: Shared app-level constants (history limits, demo assets/steps, processing copy).
- `frontend/src/utils/pdf.ts`: PDF.js loading, page size extraction, and AcroForm field extraction. On Windows, Excel/Microsoft 365 exports are reopened with embedded-font preference to reduce Office-export render drift.
- `frontend/src/styles/*.css` + `frontend/src/components/**/*.css`: Shared shell styles and component-scoped styles.
- `scripts/seo-route-data.mjs`: Build-time re-export bridge for the shared public route SEO dataset. Existing scripts import this path, but `frontend/src/config/publicRouteSeoData.mjs` is the source of truth.

For the hook interaction map, see `frontend/docs/app-hooks.md`.
