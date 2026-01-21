# Source Structure

```
frontend/
  src/
    components/
      features/
        SearchFillModal.tsx
        UploadComponent.tsx
      layout/
        HeaderBar.tsx
        LegacyHeader.tsx
      panels/
        FieldInspectorPanel.tsx
        FieldListPanel.tsx
      pages/
        Homepage.tsx
        LoginPage.tsx
        ProfilePage.tsx
        VerifyEmailPage.tsx
      ui/
        Alert.tsx
        Dialog.tsx
      viewer/
        FieldOverlay.tsx
        FieldInputOverlay.tsx
        PdfViewer.tsx
    services/
      apiConfig.ts
      auth.ts
      authTokenStore.ts
      detectionApi.ts
      firebaseClient.ts
    api.ts
    utils/
      confidence.ts
      coords.ts
      csv.ts
      dataSource.ts
      excel.ts
      schema.ts
      fieldUi.ts
      fields.ts
      pdf.ts
    App.tsx
    App.css
    index.css
```

## Key files

- `frontend/src/App.tsx`: Top-level state and workflow orchestration.
- `frontend/src/components/pages/LoginPage.tsx`: FirebaseUI sign-in entry point.
- `frontend/src/components/pages/VerifyEmailPage.tsx`: Email verification gate for password logins.
- `frontend/src/components/pages/ProfilePage.tsx`: Profile view for tier limits and saved forms.
- `frontend/src/utils/pdf.ts`: PDF.js loader + AcroForm extraction.
- `frontend/src/components/viewer/PdfViewer.tsx`: Canvas rendering and overlay host.
- `frontend/src/components/viewer/FieldOverlay.tsx`: Drag/resize overlay logic.
- `frontend/src/components/panels/FieldListPanel.tsx`: Filtering + selection list.
- `frontend/src/components/panels/FieldInspectorPanel.tsx`: Inspector edits and actions.
- `frontend/src/components/features/SearchFillModal.tsx`: Search & Fill workflow.
- `frontend/src/api.ts`: Backend API wrapper for schema + rename endpoints.
- `frontend/src/services/apiConfig.ts`: API base URL + auth headers.
- `frontend/src/utils/alertMessages.ts`: Shared alert copy for UI flows.
- `frontend/src/utils/schema.ts`: Schema inference + TXT parsing.
- `frontend/src/App.css`: UI shell styles.
- `frontend/src/index.css`: Global tokens and base styles.
