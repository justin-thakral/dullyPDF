# App Hook Architecture

`frontend/src/App.tsx` bootstraps the app, while `frontend/src/WorkspaceRuntime.tsx` owns the main workspace state and renders UI states. Most behavior lives in extracted hooks under `frontend/src/hooks/`.

## Hook groups

- Core editor state:
  - `useFieldHistory`
  - `useFieldState`
  - `useDialog`
- Auth and saved forms:
  - `useAuth`
  - `useSavedForms` (saved-form list state, retry logic, and saved-form loading status during backend startup; also coordinates best-effort group/profile refresh after template mutations)
  - `useDowngradeRetentionRuntime` (owns Stripe checkout launch/cancel flows, return-url reconciliation, and downgrade-retention dialog state/actions so billing and free-plan downgrade behavior stay out of `WorkspaceRuntime.tsx`)
- Group template orchestration:
  - `useGroupTemplateCache` (instant group template switching, snapshot caching, per-template display-mode restore, dirty-template tracking for group exit prompts, bounded background prefetch, and multi-template Search & Fill application)
  - `useWorkspaceFillLinks` (keeps Fill By Link orchestration out of `WorkspaceRuntime.tsx` by coordinating template/group publish, reopen, response search/loading, dirty-schema guards, and Search & Fill handoff)
- Detection and OpenAI pipeline:
  - `useDetection` (detection upload state, status polling, source-aware processing copy for detect/fill-able upload/saved form/saved group entry points, and cancellation of stale/background pollers when the active document changes)
  - `useOpenAiPipeline` (includes lazy saved-form session recreation when Rename starts before the initial saved-form session prewarm succeeds)
  - `useDataSource`
  - `usePipelineModal`
- Output and demo:
  - `useSaveDownload` (forces overwrite-only saves while a group is open so the active template cannot fork out of the group silently)
  - `useGroupDownload` (downloads the open group as a zip archive using the current cached state of each template)
  - `useDemo`

## Bridge refs used in `WorkspaceRuntime.tsx`

`WorkspaceRuntime.tsx` keeps a few refs to break circular dependencies between hooks:

- `savedFormsBridge`: lets auth-triggered flows call saved-form refresh/reset actions.
- `openAiBridge`: lets detection flows call OpenAI actions and setters.
- `openAiSettersForDataSource`: lets data-source flows surface mapping/openai status.
- `clearWorkspaceRef`: gives hooks a stable callback for full app reset.
- `demoBridgeRef`: exposes demo lock state to session keep-alive logic.

## Reset flow

`clearWorkspace` in `WorkspaceRuntime.tsx` is the full reset path. It clears:

- PDF/document + page state.
- Field history/state selections and visibility flags.
- Detection, OpenAI, data-source, pipeline modal, saved-form, and dialog hook state.
- Search & Fill visibility/session token state.

Use this reset path when starting a new document workflow or returning to homepage state.

## Extending the architecture

1. Put new state in the hook that owns that concern.
2. Expose explicit actions from the hook return value.
3. Wire actions in `WorkspaceRuntime.tsx` through props/callbacks.
4. Add a bridge ref only when two hooks must call each other and callback wiring alone is not enough.
