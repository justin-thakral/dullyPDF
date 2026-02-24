import './UploadView.css';
import type { DataSourceKind } from '../../types';
import type { SavedFormSummary } from '../../services/api';
import { Alert } from '../ui/Alert';
import { CommonFormsAttribution } from '../ui/CommonFormsAttribution';
import UploadComponent from './UploadComponent';

export interface UploadViewProps {
  loadError: string | null;
  showPipelineModal: boolean;
  pendingDetectFile: File | null;
  uploadWantsRename: boolean;
  uploadWantsMap: boolean;
  schemaUploadInProgress: boolean;
  dataSourceLabel: string | null;
  pipelineError: string | null;
  verifiedUser: boolean;
  savedForms: SavedFormSummary[];
  savedFormsLoading: boolean;
  deletingFormId: string | null;
  onSetUploadWantsRename: (checked: boolean) => void;
  onSetUploadWantsMap: (checked: boolean) => void;
  onSetPipelineError: (error: string | null) => void;
  onSetLoadError: (error: string | null) => void;
  onChooseDataSource: (kind: Exclude<DataSourceKind, 'none'>) => void;
  onPipelineCancel: () => void;
  onPipelineConfirm: () => void;
  onDetectUpload: (file: File) => void;
  onFillableUpload: (file: File) => void;
  onSelectSavedForm: (formId: string) => void;
  onDeleteSavedForm: (formId: string) => void;
}

export default function UploadView({
  loadError,
  showPipelineModal,
  pendingDetectFile,
  uploadWantsRename,
  uploadWantsMap,
  schemaUploadInProgress,
  dataSourceLabel,
  pipelineError,
  verifiedUser,
  savedForms,
  savedFormsLoading,
  deletingFormId,
  onSetUploadWantsRename,
  onSetUploadWantsMap,
  onSetPipelineError,
  onSetLoadError,
  onChooseDataSource,
  onPipelineCancel,
  onPipelineConfirm,
  onDetectUpload,
  onFillableUpload,
  onSelectSavedForm,
  onDeleteSavedForm,
}: UploadViewProps) {
  return (
    <div className="upload-layout">
      {showPipelineModal && (
        <div className="pipeline-modal" role="dialog" aria-modal="true" aria-labelledby="pipeline-modal-title">
          <div className="pipeline-modal__card">
            <div className="pipeline-modal__header">
              <h2 id="pipeline-modal-title" className="pipeline-modal__title">Choose your detection pipeline</h2>
              {pendingDetectFile && <p className="pipeline-modal__subtitle">{pendingDetectFile.name}</p>}
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
            </div>
            {pipelineError ? <div className="pipeline-modal__alert"><Alert tone="error" variant="inline" size="sm" message={pipelineError} /></div> : null}
            <div className="pipeline-modal__actions">
              <button className="ui-button ui-button--ghost" type="button" onClick={onPipelineCancel}>Cancel</button>
              <button className="ui-button ui-button--primary" type="button" onClick={onPipelineConfirm}
                disabled={!pendingDetectFile || (uploadWantsMap && schemaUploadInProgress)}>Continue</button>
            </div>
          </div>
        </div>
      )}
      <div className="upload-primary-grid">
        <UploadComponent variant="detect" title="Upload PDF for Field Detection" subtitle="Drag and drop your PDF file here, or"
          onFileUpload={onDetectUpload} onValidationError={(message) => onSetLoadError(message)} />
        <UploadComponent variant="fillable" title="Upload Fillable PDF Template" subtitle="Open your existing fillable PDF directly in the editor"
          onFileUpload={onFillableUpload} onValidationError={(message) => onSetLoadError(message)} />
      </div>
      {verifiedUser && (
        <section className="saved-forms-section" aria-label="Open saved form">
          <h2 className="saved-forms-title">Open Saved Form:</h2>
          <UploadComponent variant="saved" title="" subtitle="" savedForms={savedForms}
            savedFormsLoading={savedFormsLoading}
            onSelectSavedForm={onSelectSavedForm} onDeleteSavedForm={onDeleteSavedForm} deletingFormId={deletingFormId} />
        </section>
      )}
      {loadError ? <div className="upload-alert"><Alert tone="error" variant="inline" message={loadError} /></div> : null}
    </div>
  );
}
