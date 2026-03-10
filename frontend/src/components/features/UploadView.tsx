import './UploadView.css';
import type { DataSourceKind } from '../../types';
import { useState, type ReactNode } from 'react';
import type { SavedFormSummary, TemplateGroupSummary } from '../../services/api';
import { Alert } from '../ui/Alert';
import { CommonFormsAttribution } from '../ui/CommonFormsAttribution';
import { DialogFrame } from '../ui/Dialog';
import { GroupCreateDialog } from './GroupCreateDialog';
import UploadComponent from './UploadComponent';

export interface UploadViewProps {
  loadError: string | null;
  showPipelineModal: boolean;
  pendingDetectFile: File | null;
  pendingDetectPageCount: number | null;
  pendingDetectPageCountLoading: boolean;
  pendingDetectCreditEstimate: {
    totalCredits: number;
    bucketCount: number;
    baseCost: number;
  } | null;
  pendingDetectWithinPageLimit: boolean;
  pendingDetectCreditsRemaining: number | null;
  uploadWantsRename: boolean;
  uploadWantsMap: boolean;
  schemaUploadInProgress: boolean;
  dataSourceLabel: string | null;
  pipelineError: string | null;
  verifiedUser: boolean;
  savedForms: SavedFormSummary[];
  groups: TemplateGroupSummary[];
  groupsLoading: boolean;
  groupsCreating: boolean;
  updatingGroupId: string | null;
  selectedGroupFilterId: string;
  selectedGroupFilterLabel: string | null;
  savedFormsLoading: boolean;
  deletingFormId: string | null;
  deletingGroupId: string | null;
  onSetUploadWantsRename: (checked: boolean) => void;
  onSetUploadWantsMap: (checked: boolean) => void;
  onSetPipelineError: (error: string | null) => void;
  onSetLoadError: (error: string | null) => void;
  onChooseDataSource: (kind: Exclude<DataSourceKind, 'none'>) => void;
  onPipelineCancel: () => void;
  onPipelineConfirm: () => void;
  onDetectUpload: (file: File) => void;
  onFillableUpload: (file: File) => void;
  onOpenGroupUpload: () => void;
  onSelectSavedForm: (formId: string) => void;
  onDeleteSavedForm: (formId: string) => void;
  onSelectGroupFilter: (groupId: string) => void;
  onOpenGroup: (groupId: string) => void;
  onCreateGroup: (payload: { name: string; templateIds: string[] }) => Promise<unknown> | void;
  onUpdateGroup: (groupId: string, payload: { name: string; templateIds: string[] }) => Promise<unknown> | void;
  onDeleteGroup: (groupId: string) => void;
  groupUploadDialog?: ReactNode;
}

export default function UploadView({
  loadError,
  showPipelineModal,
  pendingDetectFile,
  pendingDetectPageCount,
  pendingDetectPageCountLoading,
  pendingDetectCreditEstimate,
  pendingDetectWithinPageLimit,
  pendingDetectCreditsRemaining,
  uploadWantsRename,
  uploadWantsMap,
  schemaUploadInProgress,
  dataSourceLabel,
  pipelineError,
  verifiedUser,
  savedForms,
  groups,
  groupsLoading,
  groupsCreating,
  updatingGroupId,
  selectedGroupFilterId,
  selectedGroupFilterLabel,
  savedFormsLoading,
  deletingFormId,
  deletingGroupId,
  onSetUploadWantsRename,
  onSetUploadWantsMap,
  onSetPipelineError,
  onSetLoadError,
  onChooseDataSource,
  onPipelineCancel,
  onPipelineConfirm,
  onDetectUpload,
  onFillableUpload,
  onOpenGroupUpload,
  onSelectSavedForm,
  onDeleteSavedForm,
  onSelectGroupFilter,
  onOpenGroup,
  onCreateGroup,
  onUpdateGroup,
  onDeleteGroup,
  groupUploadDialog,
}: UploadViewProps) {
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const editingGroup = groups.find((group) => group.id === editingGroupId) ?? null;
  const groupDialogOpen = showCreateGroup || Boolean(editingGroup);
  const groupDialogSubmitting = groupsCreating || Boolean(editingGroupId && updatingGroupId === editingGroupId);

  return (
    <div className="upload-layout">
      {groupUploadDialog}
      <GroupCreateDialog
        open={groupDialogOpen}
        savedForms={savedForms}
        submitting={groupDialogSubmitting}
        mode={editingGroup ? 'edit' : 'create'}
        initialName={editingGroup?.name || ''}
        initialSelectedIds={editingGroup?.templateIds || []}
        onClose={() => {
          setShowCreateGroup(false);
          setEditingGroupId(null);
        }}
        onSubmit={async (payload) => {
          try {
            if (editingGroup) {
              await onUpdateGroup(editingGroup.id, payload);
            } else {
              await onCreateGroup(payload);
            }
            setShowCreateGroup(false);
            setEditingGroupId(null);
          } catch {
            // Keep the dialog open so the user can adjust the name or selection.
          }
        }}
      />
      {showPipelineModal && (
        <DialogFrame
          open={showPipelineModal}
          onClose={onPipelineCancel}
          className="pipeline-modal"
          labelledBy="pipeline-modal-title"
          describedBy={pendingDetectFile ? 'pipeline-modal-description' : undefined}
        >
          <div className="pipeline-modal__header">
            <h2 id="pipeline-modal-title" className="pipeline-modal__title">Choose your detection pipeline</h2>
            {pendingDetectFile && <p id="pipeline-modal-description" className="pipeline-modal__subtitle">{pendingDetectFile.name}</p>}
          </div>
          <div className="pipeline-modal__section">
            <span className="pipeline-modal__section-title">Detection pipeline</span>
            <label className="pipeline-modal__choice">
              <input type="radio" name="pipeline" value="commonforms" checked disabled />
              <CommonFormsAttribution suffix="(FFDNet-L)" />
            </label>
          </div>
          <div className="pipeline-modal__section">
            <span className="pipeline-modal__section-title">OpenAI actions</span>
            <p className="pipeline-modal__notice">Rename sends PDF pages and detected field tags. Mapping sends schema header names and field tags. If both are selected, OpenAI receives the PDF pages and schema headers to standardize names. No row data or field values are sent.</p>
            <label className="pipeline-modal__choice">
              <input type="checkbox" id="pipeline-rename" name="pipeline-rename" checked={uploadWantsRename}
                onChange={(event) => { onSetPipelineError(null); onSetUploadWantsRename(event.target.checked); }} />
              Rename fields with OpenAI
            </label>
            <label className="pipeline-modal__choice">
              <input type="checkbox" id="pipeline-map" name="pipeline-map" checked={uploadWantsMap}
                onChange={(event) => { onSetPipelineError(null); onSetUploadWantsMap(event.target.checked); }} />
              Map to schema (CSV/Excel/JSON/TXT)
            </label>
            {uploadWantsRename || uploadWantsMap ? (
              <p className="pipeline-modal__hint">
                {uploadWantsRename && uploadWantsMap ? 'OpenAI will receive the PDF pages, detected field tags, and your database field headers. No row data or field values are sent.'
                  : uploadWantsRename ? 'OpenAI will receive the PDF pages and detected field tags. No row data or field values are sent.'
                    : 'OpenAI will receive your database field headers and detected field tags. No row data or field values are sent.'}
              </p>
            ) : null}
            {uploadWantsMap ? (
              <div className="pipeline-modal__schema-block">
                <div className="pipeline-modal__source-row">
                  <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('csv')}>CSV</button>
                  <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('excel')}>Excel</button>
                  <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('json')}>JSON</button>
                  <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('txt')}>TXT</button>
                </div>
                <span className="pipeline-modal__status pipeline-modal__status--center">
                  Schema file: {dataSourceLabel || 'None selected'}{schemaUploadInProgress ? ' (processing)' : ''}
                </span>
              </div>
            ) : null}
            <div className="pipeline-modal__summary">
              <div className="pipeline-modal__summary-grid">
                <div className="pipeline-modal__summary-stat">
                  <span>Pages</span>
                  <strong>{pendingDetectPageCountLoading ? 'Counting…' : (pendingDetectPageCount ?? 'Unknown')}</strong>
                </div>
                <div className="pipeline-modal__summary-stat">
                  <span>Scan limit</span>
                  <strong>{pendingDetectWithinPageLimit ? 'Within limit' : 'Over limit'}</strong>
                </div>
                <div className="pipeline-modal__summary-stat">
                  <span>Estimated credits</span>
                  <strong>{pendingDetectCreditEstimate?.totalCredits ?? 0}</strong>
                </div>
                <div className="pipeline-modal__summary-stat">
                  <span>Credits remaining</span>
                  <strong>{pendingDetectCreditsRemaining ?? 'Unknown'}</strong>
                </div>
              </div>
              {pendingDetectCreditEstimate ? (
                <p className="pipeline-modal__summary-copy">
                  {pendingDetectCreditEstimate.totalCredits} credit{pendingDetectCreditEstimate.totalCredits === 1 ? '' : 's'} across {pendingDetectCreditEstimate.bucketCount} billing bucket{pendingDetectCreditEstimate.bucketCount === 1 ? '' : 's'} at {pendingDetectCreditEstimate.baseCost} credit{pendingDetectCreditEstimate.baseCost === 1 ? '' : 's'} each.
                </p>
              ) : (
                <p className="pipeline-modal__summary-copy">
                  Detection is free. Enable Rename or Map to estimate OpenAI credit usage.
                </p>
              )}
            </div>
          </div>
          {pipelineError ? <div className="pipeline-modal__alert"><Alert tone="error" variant="inline" size="sm" message={pipelineError} /></div> : null}
          <div className="pipeline-modal__actions">
            <button className="ui-button ui-button--ghost" type="button" onClick={onPipelineCancel}>Cancel</button>
            <button className="ui-button ui-button--primary" type="button" onClick={onPipelineConfirm}
              disabled={!pendingDetectFile || (uploadWantsMap && schemaUploadInProgress)}>Continue</button>
          </div>
        </DialogFrame>
      )}
      <div className="upload-primary-grid">
        <UploadComponent variant="detect" title="Upload PDF for Field Detection" subtitle="Drag and drop your PDF file here, or"
          onFileUpload={onDetectUpload} onValidationError={(message) => onSetLoadError(message)} />
        <UploadComponent
          variant="group"
          title="Upload PDF Group"
          subtitle="Create a named workflow from multiple PDFs in one batch"
          onOpenDialog={onOpenGroupUpload}
        />
        <UploadComponent variant="fillable" title="Upload Fillable PDF Template" subtitle="Open your existing fillable PDF directly in the editor"
          onFileUpload={onFillableUpload} onValidationError={(message) => onSetLoadError(message)} />
      </div>
      {verifiedUser && (
        <section className="saved-forms-section" aria-label="Open saved form">
          <UploadComponent variant="saved" title="" subtitle="" savedForms={savedForms}
            groups={groups} groupsLoading={groupsLoading}
            selectedGroupFilterId={selectedGroupFilterId}
            selectedGroupFilterLabel={selectedGroupFilterLabel}
            savedFormsLoading={savedFormsLoading}
            deletingGroupId={deletingGroupId}
            editingGroupId={updatingGroupId}
            onSelectGroupFilter={onSelectGroupFilter}
            onOpenGroup={onOpenGroup}
            onOpenCreateGroup={() => setShowCreateGroup(true)}
            onEditGroup={(groupId) => {
              setShowCreateGroup(false);
              setEditingGroupId(groupId);
            }}
            onDeleteGroup={onDeleteGroup}
            onSelectSavedForm={onSelectSavedForm} onDeleteSavedForm={onDeleteSavedForm} deletingFormId={deletingFormId} />
        </section>
      )}
      {loadError ? <div className="upload-alert"><Alert tone="error" variant="inline" message={loadError} /></div> : null}
    </div>
  );
}
