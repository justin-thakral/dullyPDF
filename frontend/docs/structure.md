# Source Structure

```
sandbox UI/
  src/
    components/
      layout/HeaderBar.tsx
      panels/FieldsPanel.tsx
      panels/PageList.tsx
      viewer/FieldOverlay.tsx
      viewer/PdfViewer.tsx
    utils/
      coords.ts
      fields.ts
      pdf.ts
    types.ts
    App.tsx
    App.css
    index.css
```

## Key files

- `src/App.tsx`: Application state and layout composition.
- `src/utils/pdf.ts`: PDF.js loader and page-size helpers.
- `src/components/viewer/PdfViewer.tsx`: Canvas rendering and overlay host.
- `src/components/viewer/FieldOverlay.tsx`: Field drag/resize logic.
- `src/components/panels/FieldsPanel.tsx`: Field list and inspector inputs.
- `src/App.css`: Component styling for the UI shell.
- `src/index.css`: Global theme tokens and base styles.
