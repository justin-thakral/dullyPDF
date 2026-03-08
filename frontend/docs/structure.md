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

- `frontend/src/App.tsx`: Top-level orchestration that composes feature hooks and renders app states (homepage/upload/processing/editor/profile/auth).
- `frontend/src/hooks/`: App feature hooks extracted from `App.tsx` (`useAuth`, `useSavedForms`, `useDetection`, `useOpenAiPipeline`, `useDataSource`, `usePipelineModal`, `useSaveDownload`, `useDemo`, `useFieldHistory`, `useFieldState`, `useDialog`).
- `frontend/src/services/apiConfig.ts`: Shared fetch wrapper, auth headers, status normalization, and API base URL resolution.
- `frontend/src/services/api.ts`: Profile/contact/recaptcha, schema persistence, OpenAI endpoints, saved forms, materialize/download operations.
- `frontend/src/services/detectionApi.ts`: Detection upload + polling (`/detect-fields`) and detection-session keep-alive.
- `frontend/src/config/intentPages.ts`: Content + FAQ + SEO metadata config for public intent and industry landing routes.
- `frontend/src/config/routeSeo.ts`: Canonical SEO route metadata map for all indexable public pages (`/`, legal, `/usage-docs/*`, intent pages, hub pages, and blog routes).
- `frontend/src/utils/seo.ts`: Head-tag applier for title, description, canonical, Open Graph, and Twitter metadata from the shared SEO map.
- `frontend/src/components/viewer/PdfViewer.tsx`: PDF canvas rendering and overlay mounting.
- `frontend/src/components/panels/FieldListPanel.tsx`: Field list, page navigation, filter/search, and display toggles.
- `frontend/src/components/panels/FieldInspectorPanel.tsx`: Selected-field metadata/geometry editing, create/delete actions, undo/redo controls.
- `frontend/src/components/features/SearchFillModal.tsx`: Record search and field fill logic.
- `frontend/src/components/features/UploadView.tsx`: Upload + saved-form selection UI and OpenAI preflight modal entry.
- `frontend/src/components/pages/*.tsx`: Homepage, auth pages, profile page, legal pages, public usage docs pages (`/usage-docs/*`), and intent landing pages.
- `frontend/src/components/pages/PublicNotFoundPage.tsx`: Generic noindex 404 page for unknown public routes that should never fall back to the editor shell.
- `frontend/src/components/pages/IntentHubPage.tsx`: Hub directory pages for `/workflows` and `/industries` that aggregate intent routes.
- `frontend/src/components/pages/IntentPageShell.tsx`: Shared shell for intent marketing pages (global header nav, breadcrumb + hero/CTA block, and footer).
- `frontend/src/config/appConstants.tsx`: Shared app-level constants (history limits, demo assets/steps, processing copy).
- `frontend/src/utils/pdf.ts`: PDF.js loading, page size extraction, and AcroForm field extraction.
- `frontend/src/styles/*.css` + `frontend/src/components/**/*.css`: Shared shell styles and component-scoped styles.
- `scripts/seo-route-data.mjs`: Build-time mirror of public SEO routes used by the static HTML and sitemap generators. Keep it aligned with `routeSeo.ts`.

For the hook interaction map, see `frontend/docs/app-hooks.md`.
