import { useId, useMemo, useRef } from 'react';
import { CommonFormsAttribution } from '../ui/CommonFormsAttribution';
import { DialogFrame } from '../ui/Dialog';
import type { GroupUploadItem } from '../../hooks/useGroupUploadModal';
import './GroupUploadDialog.css';

type GroupUploadDialogProps = {
  open: boolean;
  groupName: string;
  onGroupNameChange: (value: string) => void;
  items: GroupUploadItem[];
  wantsRename: boolean;
  onWantsRenameChange: (checked: boolean) => void;
  wantsMap: boolean;
  onWantsMapChange: (checked: boolean) => void;
  processing: boolean;
  localError: string | null;
  progressLabel: string;
  pageSummary: {
    maxPages: number;
    totalPages: number;
    largestPageCount: number;
    withinLimit: boolean;
  };
  creditEstimate: {
    totalPages: number;
    totalCredits: number;
    documentCount: number;
    documents: Array<{ pageCount: number; totalCredits: number; bucketCount: number }>;
  } | null;
  creditsRemaining: number | null;
  schemaUploadInProgress: boolean;
  dataSourceLabel: string | null;
  onChooseDataSource: (kind: 'csv' | 'excel' | 'json' | 'txt') => void;
  onClose: () => void;
  onAddFiles: (files: File[] | FileList | null | undefined) => void;
  onRemoveFile: (itemId: string) => void;
  onConfirm: () => void;
};

function summarizeItem(item: GroupUploadItem): string {
  if (item.error) return item.error;
  if (typeof item.pageCount === 'number') {
    return `${item.pageCount} page${item.pageCount === 1 ? '' : 's'}`;
  }
  return item.detail || 'Pending';
}

export function GroupUploadDialog({
  open,
  groupName,
  onGroupNameChange,
  items,
  wantsRename,
  onWantsRenameChange,
  wantsMap,
  onWantsMapChange,
  processing,
  localError,
  progressLabel,
  pageSummary,
  creditEstimate,
  creditsRemaining,
  schemaUploadInProgress,
  dataSourceLabel,
  onChooseDataSource,
  onClose,
  onAddFiles,
  onRemoveFile,
  onConfirm,
}: GroupUploadDialogProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dialogTitleId = useId();
  const dialogDescriptionId = useId();

  const uploadedCountLabel = useMemo(
    () => `${items.length} PDF${items.length === 1 ? '' : 's'}`,
    [items.length],
  );
  const creditSummaryLabel = useMemo(() => {
    if (!creditEstimate) return 'No OpenAI credits selected.';
    return `${creditEstimate.totalCredits} credit${creditEstimate.totalCredits === 1 ? '' : 's'} across ${creditEstimate.documentCount} PDF${creditEstimate.documentCount === 1 ? '' : 's'}`;
  }, [creditEstimate]);

  return (
    <DialogFrame
      open={open}
      onClose={onClose}
      className="group-upload-modal"
      labelledBy={dialogTitleId}
      describedBy={dialogDescriptionId}
    >
      <div className="group-upload-modal__header">
        <div>
          <h2 id={dialogTitleId}>Upload PDF Group</h2>
          <p id={dialogDescriptionId}>Scan multiple PDFs, optionally run OpenAI actions, save them as templates, and open the group in one flow.</p>
        </div>
        <button
          type="button"
          className="group-upload-modal__close"
          onClick={onClose}
          aria-label="Close group upload dialog"
        >
          Close
        </button>
      </div>

      <div className="group-upload-modal__body">
        <div className="group-upload-modal__column group-upload-modal__column--main">
          <label className="group-upload-modal__field">
            <span>Group name</span>
            <input
              type="text"
              value={groupName}
              onChange={(event) => onGroupNameChange(event.target.value)}
              placeholder="New hire packet"
              maxLength={120}
              disabled={processing}
            />
          </label>

          <div className="group-upload-modal__section">
            <div className="group-upload-modal__section-header">
              <span>PDF uploads</span>
              <span className="group-upload-modal__badge">{uploadedCountLabel}</span>
            </div>
            <div
              className="group-upload-modal__dropzone"
              role="button"
              tabIndex={0}
              onClick={() => inputRef.current?.click()}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  inputRef.current?.click();
                }
              }}
              onDragOver={(event) => {
                event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                onAddFiles(event.dataTransfer.files);
              }}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".pdf"
                multiple
                hidden
                onChange={(event) => {
                  onAddFiles(event.target.files);
                  event.target.value = '';
                }}
              />
              <strong>Add PDFs</strong>
              <span>Drag them here or click to browse.</span>
            </div>
            <div className="group-upload-modal__file-list" aria-label="Uploaded PDFs">
              {items.length === 0 ? (
                <p className="group-upload-modal__empty">No PDFs added yet.</p>
              ) : (
                items.map((item) => {
                  const summaryLabel = summarizeItem(item);
                  const shouldRenderDetail =
                    Boolean(item.detail) && !item.error && item.detail !== summaryLabel;

                  return (
                    <div
                      key={item.id}
                      className={`group-upload-modal__file group-upload-modal__file--${item.status}`}
                    >
                      <div className="group-upload-modal__file-content">
                        <span className="group-upload-modal__file-name">{item.name}</span>
                        <span className="group-upload-modal__file-meta">{summaryLabel}</span>
                        {shouldRenderDetail ? (
                          <span className="group-upload-modal__file-detail">{item.detail}</span>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        className="group-upload-modal__remove"
                        onClick={() => onRemoveFile(item.id)}
                        disabled={processing}
                        aria-label={`Remove ${item.name}`}
                      >
                        Remove
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        <div className="group-upload-modal__column group-upload-modal__column--side">
          <div className="group-upload-modal__side-scroll">
            <div className="group-upload-modal__section">
              <div className="group-upload-modal__section-header">
                <span>Detection pipeline</span>
              </div>
              <label className="group-upload-modal__choice">
                <input type="radio" checked disabled />
                <CommonFormsAttribution suffix="(FFDNet-L)" />
              </label>
            </div>

            <div className="group-upload-modal__section">
              <div className="group-upload-modal__section-header">
                <span>OpenAI actions</span>
              </div>
              <p className="group-upload-modal__notice">
                Rename sends PDF pages and detected field tags. Mapping sends schema headers and field tags. No row data or field values are sent.
              </p>
              <label className="group-upload-modal__choice">
                <input
                  type="checkbox"
                  checked={wantsRename}
                  onChange={(event) => onWantsRenameChange(event.target.checked)}
                  disabled={processing}
                />
                Rename fields with OpenAI
              </label>
              <label className="group-upload-modal__choice">
                <input
                  type="checkbox"
                  checked={wantsMap}
                  onChange={(event) => onWantsMapChange(event.target.checked)}
                  disabled={processing}
                />
                Map to schema (CSV/Excel/JSON/TXT)
              </label>
              {wantsMap ? (
                <div className="group-upload-modal__schema">
                  <div className="group-upload-modal__schema-actions">
                    <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('csv')}>CSV</button>
                    <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('excel')}>Excel</button>
                    <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('json')}>JSON</button>
                    <button type="button" className="ui-button ui-button--ghost ui-button--compact" onClick={() => onChooseDataSource('txt')}>TXT</button>
                  </div>
                  <div className="group-upload-modal__schema-status" aria-live="polite">
                    <span className="group-upload-modal__schema-status-label">Schema file</span>
                    <span className="group-upload-modal__schema-status-value">
                      {dataSourceLabel || 'None selected'}{schemaUploadInProgress ? ' (processing)' : ''}
                    </span>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="group-upload-modal__section group-upload-modal__section--summary">
              <div className="group-upload-modal__section-header">
                <span>Usage summary</span>
              </div>
              <div className="group-upload-modal__stat-grid">
                <div className="group-upload-modal__stat">
                  <span>Total pages</span>
                  <strong>{pageSummary.totalPages}</strong>
                </div>
                <div className="group-upload-modal__stat">
                  <span>Largest PDF</span>
                  <strong>{pageSummary.largestPageCount}</strong>
                </div>
                <div className="group-upload-modal__stat">
                  <span>Detect page limit</span>
                  <strong>{pageSummary.maxPages}</strong>
                </div>
                <div className="group-upload-modal__stat">
                  <span>Estimated OpenAI credits</span>
                  <strong>{creditEstimate?.totalCredits ?? 0}</strong>
                </div>
              </div>
              <p className={`group-upload-modal__summary-line ${pageSummary.withinLimit ? 'is-valid' : 'is-invalid'}`}>
                {pageSummary.withinLimit
                  ? 'All PDFs are within your scan page limit.'
                  : `One or more PDFs exceed your ${pageSummary.maxPages}-page scan limit.`}
              </p>
              <p className="group-upload-modal__summary-line">
                {creditsRemaining === null
                  ? creditSummaryLabel
                  : `${creditSummaryLabel}. Remaining credits: ${creditsRemaining}.`}
              </p>
              <p className="group-upload-modal__footnote">
                Credit estimates follow the current backend billing model and sum each PDF&apos;s bucketed cost individually.
              </p>
            </div>

            {localError ? <div className="group-upload-modal__error">{localError}</div> : null}
          </div>

          <div className="group-upload-modal__actions">
            <button type="button" className="ui-button ui-button--ghost" onClick={onClose}>
              {processing ? 'Stop & Close' : 'Cancel'}
            </button>
            <button type="button" className="ui-button ui-button--primary" onClick={onConfirm} disabled={processing}>
              {processing ? progressLabel : 'Create PDF Group'}
            </button>
          </div>
        </div>
      </div>
    </DialogFrame>
  );
}
