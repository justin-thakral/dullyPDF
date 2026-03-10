# Named Template Groups Plan

Concise summary:

- Scope this feature down to named groups of existing saved templates.
- Add group create/filter/open behavior inside the saved forms area on the upload screen.
- When a group is opened, load the first saved form in alphabetical order by current template name.
- Add a group template selector in the header, to the right of the zoom control, so users can switch between member PDFs without leaving the editor.
- Do not build links, public forms, shared group schemas, or group-level submissions in this pass.
- For group AI actions, use one explicit batch `Rename + Map Group` behavior that runs per-template rename/remap across all group members and persists each template. Do not silently overload the existing single-template buttons with different hidden behavior.

Assumptions:

- A group is owner-scoped and contains existing saved templates only.
- A template may belong to more than one group. The join model should support that from the start.
- Group open order is alphabetical by current saved-form name, not manual packet order.
- This phase does not include share links, public routes, pricing changes, homepage work, or SEO/docs work beyond minimal developer docs if needed.

## 1. Does this reduced scope make sense?

Yes. This is a much better first implementation slice than the original full workflow plan.

Why it fits the current repo:

- The app already has a durable saved-template layer in `backend/api/routes/saved_forms.py` and `backend/firebaseDB/template_database.py`.
- The upload screen already has a saved forms surface in `frontend/src/components/features/UploadView.tsx` and `frontend/src/components/features/UploadComponent.tsx`.
- Opening a saved form is already a first-class path in `frontend/src/hooks/useDetection.ts`.
- The editor shell already has a compact top-bar surface in `frontend/src/components/layout/HeaderBar.tsx`, which is the right place for a group member selector.

The main caveat:

- Current OpenAI rename/remap is session-based in `frontend/src/hooks/useOpenAiPipeline.ts` and `backend/api/routes/ai.py`.
- Current durable template persistence happens only when the form is overwritten through the save path in `frontend/src/hooks/useSaveDownload.ts` and `POST /api/saved-forms`.

That means group batch rename/remap is feasible, but it is not just "call the current rename endpoint on a group." It needs explicit orchestration and persistence.

Recommendation:

- In group mode, add one clear group action such as `Rename + Map Group`.
- Do not make the existing `Rename` and `Map Schema` buttons secretly mean "run both across all PDFs." That would be confusing and easy to misread.

## 2. Current repo touchpoints

### Frontend

- `frontend/src/components/features/UploadView.tsx`
  - Renders the upload screen and the saved forms section.
- `frontend/src/components/features/UploadComponent.tsx`
  - The `variant === 'saved'` branch currently renders the saved forms list.
  - This is the exact component that should gain group filtering and group creation UI.
- `frontend/src/hooks/useSavedForms.ts`
  - Holds saved form list state, active saved form id, deletion state, and quota dialog patterns.
  - Good place to mirror with a new `useGroups.ts` hook rather than overloading saved-form state.
- `frontend/src/hooks/useDetection.ts`
  - Contains the current saved-form load path.
  - `loadSavedForm(...)` already downloads the PDF, extracts fields in the browser, and creates a saved-form session.
  - Group open should reuse this path instead of inventing a second loader.
- `frontend/src/components/layout/HeaderBar.tsx`
  - The zoom control lives in `ui-header__meta`.
  - The group selector should sit immediately to the right of that existing zoom chip.
- `frontend/src/WorkspaceRuntime.tsx`
  - Owns `activeSavedFormId`, the current PDF, the current field list, and the OpenAI controls.
  - It should also own the new active group context.
- `frontend/src/hooks/useOpenAiPipeline.ts`
  - Current rename/map logic is tied to one active session or one active saved form.
  - Group batch AI should not be shoehorned into this hook without a higher-level orchestrator.
- `frontend/src/hooks/useSaveDownload.ts`
  - Current durable overwrite path for saved templates.
  - This is the behavior group batch rename/map eventually needs to preserve, even if the final orchestration moves server-side.

### Backend

- `backend/api/routes/saved_forms.py`
  - Durable template CRUD.
  - Key existing handlers:
    - `list_saved_forms`
    - `get_saved_form`
    - `download_saved_form`
    - `create_saved_form_session`
    - `save_form`
- `backend/firebaseDB/template_database.py`
  - Firestore collection `user_templates`.
  - Current durable template record is thin: ids, storage paths, loose metadata.
- `backend/api/routes/ai.py`
  - `rename_fields_ai` and schema mapping endpoints are built around one template/session at a time.
- `backend/api/routes/forms.py`
  - `POST /api/forms/materialize` is the backend primitive for generating an updated fillable PDF.
- `backend/api/schemas/models.py`
  - Existing request models; new group request/response models belong here.

### Important constraint discovered

The repo does not currently have a backend utility that can extract fillable fields from an already-saved template PDF.

That matters because:

- `create_saved_form_session` currently expects the client to send extracted fields.
- the browser already knows how to extract them via `extractFieldsFromPdf` in `frontend/src/utils/pdf.ts`
- a server-only group batch flow needs either:
  - stored field snapshots on group membership docs, or
  - a new backend field extraction implementation

For this scoped feature, the lower-risk answer is:

- store a field snapshot on each group membership

## 3. Reduced product behavior

### In scope

1. Users can create named groups from existing saved templates.
2. The saved forms area on the upload screen can filter by group.
3. The saved forms area can create a new group without leaving the upload screen.
4. Clicking a group opens the first template in that group by alphabetical template name.
5. The editor header shows a selector for all templates in the active group.
6. Switching the selector loads the chosen template into the existing editor.
7. Group AI action runs batch `Rename + Map` across all group members.

### Explicitly out of scope for this pass

- share links
- public respondent routes
- group search-and-fill as a canonical multi-template record system
- group-level canonical field concepts
- pricing/limit rules for groups
- homepage/demo/SEO/docs marketing work

## 4. Recommended data model

This reduced feature only needs a durable group container plus membership records.

Do not add group canonical field collections in this pass.

### A. `template_groups`

One document per named group.

Suggested fields:

- `owner_user_id`
- `name`
- `status` (`active`, `archived`, `deleted`)
- `created_at`
- `updated_at`

Notes:

- Keep the group doc small.
- Do not embed full template arrays or large field payloads here.

### B. `template_group_memberships`

Join model between a group and a saved template.

Suggested fields:

- `group_id`
- `owner_user_id`
- `template_id`
- `template_name_snapshot`
- `field_snapshot`
- `page_count_snapshot`
- `created_at`
- `updated_at`

Why the membership needs `field_snapshot`:

- current backend saved-form session creation requires extracted fields
- current backend does not extract them from saved templates on its own
- group batch rename/map needs a durable field payload per template

Why this model is enough for the reduced scope:

- group open order can be computed alphabetically from the current template names
- no manual packet ordering is needed yet
- no cross-template shared schema is needed yet

## 5. Backend plan

### New backend files

- `backend/api/routes/groups.py`
- `backend/firebaseDB/group_database.py`
- `backend/firebaseDB/group_membership_database.py`
- `backend/services/group_service.py`

### Existing backend files to update

- `backend/api/app.py`
- `backend/api/routes/__init__.py`
- `backend/api/schemas/models.py`
- `backend/api/routes/saved_forms.py`
  - only if shared helpers are factored out
- `backend/api/routes/ai.py`
  - only if shared AI orchestration helpers are factored out
- `backend/api/routes/forms.py`
  - only if shared materialize helper extraction is useful

### Recommended endpoints

- `GET /api/groups`
  - list group summaries for the signed-in owner
- `POST /api/groups`
  - create a named group
- `GET /api/groups/{group_id}`
  - return group detail plus member templates
- `POST /api/groups/{group_id}/templates`
  - add existing saved templates to a group
  - request should include `templateId` and the current extracted `fieldSnapshot`
- `DELETE /api/groups/{group_id}/templates/{template_id}`
  - remove one template from a group
- `POST /api/groups/{group_id}/rename-map`
  - batch `Rename + Map` every member template in the group

### Group create/add behavior

Recommended flow:

1. Frontend lets the user choose one or more existing saved templates.
2. For each selected template, frontend ensures it has a current `fieldSnapshot`.
3. Backend writes:
   - the group doc
   - one membership doc per template

Why the frontend should send `fieldSnapshot`:

- it already has `extractFieldsFromPdf`
- it avoids building a second fillable-field extraction system on the backend
- it gives the batch AI path a usable durable field payload

### Group open behavior

Recommended backend response for `GET /api/groups/{group_id}`:

- group metadata
- member template ids
- current template names
- membership ids
- optional field snapshot version info

The frontend should sort by current template name and open the first one alphabetically.

### Batch `Rename + Map Group`

This is the part that needs the most care.

Recommended behavior:

1. Frontend sends `groupId` and `schemaId`.
2. Backend resolves all group memberships.
3. For each member template:
   - load the saved template
   - create or refresh a saved-form session using the stored `field_snapshot`
   - run rename + mapping against that one template/session
   - materialize the updated PDF
   - overwrite the existing saved form
   - update stored metadata and refresh membership `field_snapshot` if the field list changed
4. Backend returns per-template results:
   - success/failure
   - updated template id
   - error message if any

Important recommendation:

- make this endpoint explicitly batch `Rename + Map`
- do not try to support independent group-level `Rename` and independent group-level `Map Schema` in the first pass

Why:

- your requested behavior is "rename + remap everything at once"
- that is simpler to explain
- it avoids split-state problems where some templates were renamed but not mapped

### Job model recommendation

Do not assume this will always fit cleanly in one short synchronous HTTP request.

Recommended implementation approach:

- first pass: synchronous only if the group size is small and the current OpenAI task mode stays reliable
- safer approach: return a job id and poll progress, especially if group size can exceed 2-3 templates

This is the one place where "just call backend once" may otherwise become fragile.

## 6. Frontend plan

### A. Upload screen changes

Target files:

- `frontend/src/components/features/UploadView.tsx`
- `frontend/src/components/features/UploadComponent.tsx`
- new `frontend/src/hooks/useGroups.ts`
- new `frontend/src/components/features/GroupCreateDialog.tsx`

Recommended UI changes inside the saved forms component:

1. Add a lightweight group filter control above the saved form rows.
2. Add a `Create Group` action in the same saved-forms area.
3. Keep the saved form rows visible, but filter them by the selected group.
4. Also show group rows so a user can click a group directly.

Recommended first-pass UX:

- Filter options:
  - `All`
  - one option per group
- Group create modal:
  - group name
  - multi-select existing saved templates
- Group row click:
  - loads the first template alphabetically

Avoid:

- a separate full-screen group management page in this pass

### B. Active group state

Target file:

- `frontend/src/WorkspaceRuntime.tsx`

Add new state:

- `activeGroupId`
- `activeGroupName`
- `activeGroupTemplateIds`
- `activeGroupTemplateSummaries`

Behavior:

- when a group is opened, set active group context and load the first template
- when a single saved form is opened directly, clear active group context

### C. Header selector

Target file:

- `frontend/src/components/layout/HeaderBar.tsx`

Add props for:

- active group name
- active group member list
- active member template id
- template switch callback

Placement:

- to the right of the existing zoom chip in `ui-header__meta`

Behavior:

- only render when a group is active
- switching the selector reuses the existing saved-form load path
- preserve current editor shell, panels, and toolbar

### D. Saved-form load reuse

Target file:

- `frontend/src/hooks/useDetection.ts`

Do not invent a second "load group template" pipeline.

Instead:

- reuse `loadSavedForm(formId, pdfState)`
- drive it from group open and group selector change

This is the cleanest fit with the current runtime.

## 7. Rename/remap behavior in this reduced scope

This is the one part of your proposal that needs a small adjustment.

What makes sense:

- group mode should offer one batch AI action
- that action should run across every template in the group

What does not make sense:

- keeping the current separate `Rename` and `Map Schema` buttons but making them both silently do `Rename + Map Group`

Recommended product behavior:

- in group mode, show one explicit action:
  - `Rename + Map Group`
- keep the current single-template controls unchanged when no group is active

Why this is the right compromise:

- it matches your desired backend behavior
- it avoids surprising users
- it reduces edge cases in the first implementation

### Persistence strategy

For the batch action to be durable, it should overwrite each saved template after a successful per-template rename/map run.

That means the group batch path should not stop at "AI returned renamed fields."

It must also:

1. generate the updated fillable PDF
2. overwrite the existing saved form
3. refresh the group membership snapshot

If you skip that persistence step, the group action will look successful in-session but disappear later.

## 8. Backward compatibility

Keep unchanged:

- direct saved-form open
- direct single-template rename
- direct single-template mapping
- direct single-template download/save

Groups in this pass are just:

- a saved-template organization layer
- a navigation layer
- a batch AI layer

They are not yet:

- a new canonical data model for filling packets
- a public workflow system

## 9. Deferred work

Do not include these in the first implementation:

- share links
- public routes
- group-level search and fill
- group-level canonical field concepts
- packet downloads
- billing rules for groups
- homepage/demo/SEO changes

These can come later after the named-group foundation is stable.

## 10. Testing plan

### Backend

Add tests for:

- group CRUD and membership writes
- ownership enforcement
- duplicate membership protection
- `GET /api/groups/{group_id}` detail payload
- batch `Rename + Map Group` success/failure aggregation
- overwrite persistence after successful batch AI

Likely test locations:

- `backend/test/unit/api/`
- `backend/test/unit/firebase/`

Mirror patterns from:

- `backend/test/unit/api/test_main_saved_forms_endpoints_blueprint.py`
- `backend/test/unit/api/test_main_ai_endpoints_blueprint.py`
- `backend/test/unit/firebase/test_app_database_user_and_template_blueprint.py`

### Frontend

Add tests for:

- saved forms component group filter behavior
- group create dialog
- group click opening alphabetical first template
- header group selector visibility and switching
- group mode action rendering
- batch group action progress/error states

Likely test locations:

- `frontend/test/unit/components/features/`
- `frontend/test/unit/components/layout/`
- `frontend/test/unit/app/`
- `frontend/test/unit/api/`

Mirror patterns from:

- `frontend/test/unit/components/features/test_upload_component.test.tsx`
- `frontend/test/unit/components/pages/test_profile_page.test.tsx`
- `frontend/test/unit/app/test_app.test.tsx`
- `frontend/test/unit/api/test_api_service.test.ts`

## 11. Step-by-step implementation order

### Step 1: add the minimal group data model

1. Create `template_groups` storage helpers.
2. Create `template_group_memberships` storage helpers.
3. Add backend routes for group list/create/detail/add/remove.
4. Add API client methods and types in `frontend/src/services/api.ts`.

### Step 2: add upload-screen group create and filter

1. Build `useGroups.ts`.
2. Build `GroupCreateDialog.tsx`.
3. Extend the saved-forms area in `UploadComponent.tsx`.
4. Allow filtering saved forms by selected group.

### Step 3: add group open behavior

1. Add active group state to `WorkspaceRuntime.tsx`.
2. On group click, fetch group detail.
3. Sort members alphabetically by current template name.
4. Open the first template through the existing saved-form loader.

### Step 4: add the header selector

1. Extend `HeaderBar.tsx` props.
2. Render the group template selector next to zoom.
3. Switching selector loads the chosen template through `loadSavedForm`.

### Step 5: add batch `Rename + Map Group`

1. Add a backend batch endpoint.
2. Feed it `groupId` and `schemaId`.
3. Run per-template saved-form session creation from membership snapshots.
4. Run rename + map for each template.
5. Persist the updated PDF back into the saved form.
6. Return per-template results and show them in the UI.

### Step 6: polish and harden

1. Handle partial failures cleanly.
2. Refresh active group member names and snapshots after batch runs.
3. Add unit/integration coverage.
4. Verify group switching, saved-form filtering, and overwrite persistence manually.

## Final recommendation

This reduced plan makes sense and fits the current codebase much better than the original all-at-once Groups feature.

The only change I recommend to your wording is this:

- do not make `Rename` and `Map Schema` secretly mean `Rename + Map Group`
- instead, add one explicit group batch action and keep single-template semantics unchanged

Everything else in your narrowed scope is coherent:

- create groups from existing templates
- filter saved forms by group
- open the first alphabetical template
- switch group members from the header
- batch `Rename + Map` across the group

That is a reasonable first implementation slice.
