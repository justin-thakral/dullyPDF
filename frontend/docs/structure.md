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
- `frontend/src/components/viewer/PdfViewer.tsx`: PDF canvas rendering and overlay mounting.
- `frontend/src/components/panels/FieldListPanel.tsx`: Field list, page navigation, filter/search, and display toggles.
- `frontend/src/components/panels/FieldInspectorPanel.tsx`: Selected-field metadata/geometry editing, create/delete actions, undo/redo controls.
- `frontend/src/components/features/SearchFillModal.tsx`: Record search and field fill logic.
- `frontend/src/components/features/UploadView.tsx`: Upload + saved-form selection UI and OpenAI preflight modal entry.
- `frontend/src/components/pages/*.tsx`: Homepage, auth pages, profile page, and legal pages.
- `frontend/src/config/appConstants.tsx`: Shared app-level constants (history limits, demo assets/steps, processing copy).
- `frontend/src/utils/pdf.ts`: PDF.js loading, page size extraction, and AcroForm field extraction.
- `frontend/src/styles/*.css` + `frontend/src/components/**/*.css`: Shared shell styles and component-scoped styles.

For the hook interaction map, see `frontend/docs/app-hooks.md`.
