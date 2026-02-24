# App Hook Architecture

`frontend/src/App.tsx` orchestrates app state and renders UI states, while most behavior lives in extracted hooks under `frontend/src/hooks/`.

## Hook groups

- Core editor state:
  - `useFieldHistory`
  - `useFieldState`
  - `useDialog`
- Auth and saved forms:
  - `useAuth`
  - `useSavedForms` (saved-form list state, retry logic, and saved-form loading status during backend startup)
- Detection and OpenAI pipeline:
  - `useDetection`
  - `useOpenAiPipeline`
  - `useDataSource`
  - `usePipelineModal`
- Output and demo:
  - `useSaveDownload`
  - `useDemo`

## Bridge refs used in `App.tsx`

`App.tsx` keeps a few refs to break circular dependencies between hooks:

- `savedFormsBridge`: lets auth-triggered flows call saved-form refresh/reset actions.
- `openAiBridge`: lets detection flows call OpenAI actions and setters.
- `openAiSettersForDataSource`: lets data-source flows surface mapping/openai status.
- `clearWorkspaceRef`: gives hooks a stable callback for full app reset.
- `demoBridgeRef`: exposes demo lock state to session keep-alive logic.

## Reset flow

`clearWorkspace` in `App.tsx` is the full reset path. It clears:

- PDF/document + page state.
- Field history/state selections and visibility flags.
- Detection, OpenAI, data-source, pipeline modal, saved-form, and dialog hook state.
- Search & Fill visibility/session token state.

Use this reset path when starting a new document workflow or returning to homepage state.

## Extending the architecture

1. Put new state in the hook that owns that concern.
2. Expose explicit actions from the hook return value.
3. Wire actions in `App.tsx` through props/callbacks.
4. Add a bridge ref only when two hooks must call each other and callback wiring alone is not enough.
