/**
 * Upload panel for PDF detection or saved form selection.
 */
import React, { useMemo, useRef, useState } from 'react';
import type { SavedFormSummary, TemplateGroupSummary } from '../../services/api';
import './UploadComponent.css';

interface UploadComponentProps {
  onFileUpload?: (file: File) => void;
  onOpenDialog?: () => void;
  onValidationError?: (message: string) => void;
  onSelectSavedForm?: (formId: string) => void;
  onDeleteSavedForm?: (formId: string) => void;
  onDeleteGroup?: (groupId: string) => void;
  onEditGroup?: (groupId: string) => void;
  title?: string;
  subtitle?: string;
  variant?: 'detect' | 'fillable' | 'group' | 'saved';
  savedForms?: SavedFormSummary[];
  groups?: TemplateGroupSummary[];
  groupsLoading?: boolean;
  selectedGroupFilterId?: string;
  selectedGroupFilterLabel?: string | null;
  onSelectGroupFilter?: (groupId: string) => void;
  onOpenGroup?: (groupId: string) => void;
  onOpenCreateGroup?: () => void;
  savedFormsLoading?: boolean;
  deletingFormId?: string | null;
  deletingGroupId?: string | null;
  editingGroupId?: string | null;
}

/**
 * Render upload dropzone or saved forms list by variant.
 */
const UploadComponent: React.FC<UploadComponentProps> = ({
  onFileUpload,
  onOpenDialog,
  onValidationError,
  onSelectSavedForm,
  onDeleteSavedForm,
  onDeleteGroup,
  onEditGroup,
  title,
  subtitle,
  variant = 'detect',
  savedForms = [],
  groups = [],
  groupsLoading = false,
  selectedGroupFilterId = 'all',
  selectedGroupFilterLabel = null,
  onSelectGroupFilter,
  onOpenGroup,
  onOpenCreateGroup,
  savedFormsLoading = false,
  deletingFormId = null,
  deletingGroupId = null,
  editingGroupId = null,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [showGroupLibrary, setShowGroupLibrary] = useState(false);

  /**
   * Validate file type/size before passing it upstream.
   */
  const handleFileSelect = (file: File) => {
    const name = file.name.toLowerCase();
    const isPdf =
      file.type === 'application/pdf' ||
      file.type === 'application/octet-stream' ||
      file.type === '' ||
      name.endsWith('.pdf');
    if (!isPdf) {
      onValidationError?.('Please select a PDF file.');
      return;
    }

    if (file.size > 50 * 1024 * 1024) {
      onValidationError?.('File size must be less than 50MB.');
      return;
    }

    onFileUpload?.(file);
  };

  /**
   * Handle native file input changes.
   */
  const handleFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
    event.target.value = '';
  };

  /**
   * Toggle drag state for dropzone UI.
   */
  const handleDrag = (event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.type === 'dragenter' || event.type === 'dragover') {
      setDragActive(true);
    } else if (event.type === 'dragleave') {
      setDragActive(false);
    }
  };

  /**
   * Process a dropped file and validate it.
   */
  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);

    const file = event.dataTransfer.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
  };

  /**
   * Open the file picker, using showPicker when supported.
   */
  const openFileDialog = () => {
    const input = fileInputRef.current;
    if (!input) return;
    const picker = input.showPicker;
    if (typeof picker === 'function') {
      try {
        picker.call(input);
        return;
      } catch {
        // Fallback to click if showPicker is blocked by browser gesture rules.
      }
    }
    input.click();
  };

  const inputId = `${variant}-pdf-input`;
  const inputName = `${variant}-pdf`;

  const activeGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupFilterId) ?? null,
    [groups, selectedGroupFilterId],
  );
  const hasSelectedGroupFilterOption = useMemo(
    () => selectedGroupFilterId === 'all' || groups.some((group) => group.id === selectedGroupFilterId),
    [groups, selectedGroupFilterId],
  );
  const resolvedSelectedGroupFilterLabel = selectedGroupFilterId === 'all'
    ? 'All saved forms'
    : activeGroup?.name
      || selectedGroupFilterLabel
      || (groupsLoading ? 'Loading selected group…' : 'Selected group unavailable');

  const filteredSavedForms = useMemo(() => {
    if (selectedGroupFilterId === 'all') return savedForms;
    if (!activeGroup) return [];
    const allowedIds = new Set(activeGroup.templateIds);
    return savedForms.filter((form) => allowedIds.has(form.id));
  }, [activeGroup, savedForms, selectedGroupFilterId]);

  const savedFormsHeading = activeGroup ? activeGroup.name : resolvedSelectedGroupFilterLabel;
  const savedFormsCountLabel = `${filteredSavedForms.length} saved form${filteredSavedForms.length === 1 ? '' : 's'}`;
  const groupsCountLabel = `${groups.length} group${groups.length === 1 ? '' : 's'}`;
  const savedSectionHeading = showGroupLibrary ? 'Groups' : savedFormsHeading;
  const savedSectionCountLabel = showGroupLibrary ? groupsCountLabel : savedFormsCountLabel;
  const savedSectionSummary = showGroupLibrary
    ? 'Open a workflow group or delete one you no longer need.'
    : 'Choose a saved template to reopen in the editor.';
  const groupToggleLabel = showGroupLibrary ? 'Switch to templates' : 'Switch to groups';

  const heading =
    title ??
    (variant === 'fillable'
      ? 'Upload Fillable PDF Template'
      : variant === 'group'
        ? 'Upload PDF Group'
        : variant === 'saved'
        ? 'Your Saved Forms'
        : 'Upload PDF Document');
  const sub =
    subtitle ??
    (variant === 'fillable'
      ? 'Open a fillable PDF directly in the editor to fill, sign, and search fields'
      : variant === 'group'
        ? 'Upload multiple PDFs in one batch to detect, rename, and map fields across a workflow'
      : variant === 'saved'
        ? 'Select a form from your saved templates'
        : 'Upload a PDF to auto-detect fields, then edit, fill, sign, and search in the form builder');

  if (variant === 'saved') {
    const hasIntroText =
      (typeof heading === 'string' && heading.trim().length > 0) ||
      (typeof sub === 'string' && sub.trim().length > 0);

    return (
      <div className="upload-container upload--saved">
        <div className="upload-area upload-area--saved">
          {hasIntroText && (
            <div className="saved-intro">
              {heading && heading.trim().length > 0 && <h3>{heading}</h3>}
              {sub && sub.trim().length > 0 && <p>{sub}</p>}
            </div>
          )}
          <div className="saved-browser">
            <div className="saved-browser__toolbar">
              <span className="saved-browser__toolbar-title">Open Saved Form:</span>
              <label className="saved-browser__filter" aria-label="Filter saved forms by group">
                <select
                  id="saved-browser-group-filter"
                  name="saved_browser_group_filter"
                  value={hasSelectedGroupFilterOption ? selectedGroupFilterId : '__selected_group_pending__'}
                  onChange={(event) => onSelectGroupFilter?.(event.target.value)}
                >
                  <option value="all">All saved forms</option>
                  {!hasSelectedGroupFilterOption ? (
                    <option value="__selected_group_pending__">{resolvedSelectedGroupFilterLabel}</option>
                  ) : null}
                  {groups.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className={`saved-browser__toggle ${showGroupLibrary ? 'saved-browser__toggle--active' : ''}`}>
                <input
                  id="saved-browser-group-toggle"
                  name="saved_browser_group_toggle"
                  type="checkbox"
                  checked={showGroupLibrary}
                  onChange={(event) => setShowGroupLibrary(event.target.checked)}
                />
                <span>{groupToggleLabel}</span>
              </label>
              <button
                type="button"
                className="saved-browser__toolbar-button"
                onClick={() => onOpenCreateGroup?.()}
              >
                Create Group
              </button>
            </div>
            <div className="saved-browser__header">
              <p className="saved-browser__summary">
                <span className="saved-browser__summary-title">{savedSectionHeading}:</span>
                <span className="saved-browser__summary-text">
                  {activeGroup && !showGroupLibrary
                    ? `${savedSectionSummary} Filtered to ${activeGroup.name}.`
                    : savedSectionSummary}
                </span>
              </p>
              <span className="saved-browser__count">{savedSectionCountLabel}</span>
            </div>
            <div className="saved-browser__viewport" aria-live="polite">
              {showGroupLibrary ? (
                groupsLoading ? (
                  <p className="saved-browser__empty" role="status">Loading groups…</p>
                ) : groups.length === 0 ? (
                  <p className="saved-browser__empty">No groups yet. Create a group from your saved forms.</p>
                ) : (
                  <div className="saved-chip-list" aria-label="Saved form groups">
                    {groups.map((group) => {
                      const isDeletingGroup = deletingGroupId === group.id;
                      const isEditingGroup = editingGroupId === group.id;
                      const isActiveFilter = group.id === selectedGroupFilterId;
                      const isLockedGroup = Boolean(group.locked || group.accessStatus === 'locked');
                      return (
                        <div
                          key={group.id}
                          className={[
                            'saved-chip',
                            'saved-chip--group',
                            isActiveFilter ? 'saved-chip--active' : '',
                            isLockedGroup ? 'saved-chip--locked' : '',
                          ].filter(Boolean).join(' ')}
                        >
                          <button
                            type="button"
                            className="saved-chip__content"
                            onClick={() => {
                              if (!isDeletingGroup && !isLockedGroup) onOpenGroup?.(group.id);
                            }}
                            disabled={isDeletingGroup || isLockedGroup}
                          >
                            <span className="saved-chip__label">{group.name}</span>
                            <span className="saved-chip__meta">
                              {group.templateCount} template{group.templateCount === 1 ? '' : 's'}
                              {isLockedGroup ? ' • Locked on base' : ''}
                            </span>
                          </button>
                          {isLockedGroup ? (
                            <span className="saved-chip__status saved-chip__status--locked">Locked</span>
                          ) : null}
                          {!isLockedGroup && onEditGroup && (
                            <button
                              type="button"
                              className="saved-chip__action"
                              onClick={() => {
                                if (!isDeletingGroup && !isEditingGroup) onEditGroup(group.id);
                              }}
                              disabled={isDeletingGroup || isEditingGroup}
                              aria-label={`Edit group ${group.name}`}
                            >
                              {isEditingGroup ? 'Loading…' : 'Edit'}
                            </button>
                          )}
                          {!isLockedGroup && onDeleteGroup && (
                            <button
                              type="button"
                              className="saved-chip__action saved-chip__action--danger"
                              onClick={() => {
                                if (!isDeletingGroup && !isEditingGroup) onDeleteGroup(group.id);
                              }}
                              disabled={isDeletingGroup || isEditingGroup}
                              aria-label={`Delete group ${group.name}`}
                            >
                              {isDeletingGroup ? 'Loading…' : 'Delete'}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )
              ) : savedFormsLoading && savedForms.length === 0 ? (
                <p className="saved-browser__empty" role="status">Loading saved forms while the backend starts…</p>
              ) : savedForms.length === 0 ? (
                <p className="saved-browser__empty">No saved forms yet. Save a form to see it here.</p>
              ) : filteredSavedForms.length === 0 ? (
                <p className="saved-browser__empty">No saved forms match this group filter.</p>
              ) : (
                <div className="saved-chip-list" aria-label="Saved templates">
                  {filteredSavedForms.map((form) => {
                    const isDeleting = deletingFormId === form.id;
                    const isLocked = Boolean(form.locked || form.accessStatus === 'locked');
                    const parsedDate = form.createdAt ? new Date(form.createdAt) : null;
                    const dateLabel =
                      parsedDate && !Number.isNaN(parsedDate.getTime())
                        ? parsedDate.toLocaleDateString()
                        : 'Unknown date';
                    return (
                      <div
                        key={form.id}
                        className={[
                          'saved-chip',
                          'saved-chip--form',
                          isLocked ? 'saved-chip--locked' : '',
                        ].filter(Boolean).join(' ')}
                      >
                        <button
                          type="button"
                          className="saved-chip__content"
                          onClick={() => {
                            if (!isDeleting && !isLocked) onSelectSavedForm?.(form.id);
                          }}
                          disabled={isDeleting || isLocked}
                        >
                          <span className="saved-chip__label">{form.name}</span>
                          <span className="saved-chip__meta">
                            {dateLabel}
                            {isLocked ? ' • Locked on base' : ''}
                          </span>
                        </button>
                        {isLocked ? (
                          <span className="saved-chip__status saved-chip__status--locked">Locked</span>
                        ) : null}
                        {!isLocked && onDeleteSavedForm && (
                          <button
                            type="button"
                            className="saved-chip__action saved-chip__action--danger"
                            onClick={() => {
                              if (!isDeleting) onDeleteSavedForm(form.id);
                            }}
                            disabled={isDeleting}
                            aria-label={`Delete saved form ${form.name}`}
                          >
                            {isDeleting ? 'Loading…' : 'Delete'}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const isGroupVariant = variant === 'group';
  const containerClass = variant === 'fillable'
    ? 'upload--fillable'
    : isGroupVariant
      ? 'upload--group'
      : 'upload--detect';

  return (
    <div className={`upload-container ${containerClass}`}>
      {isGroupVariant ? (
        <button
          type="button"
          className="upload-area"
          onClick={onOpenDialog}
        >
          <div className="upload-icon upload-icon--group" aria-hidden="true" />
          <h3>{heading}</h3>
          <p>{sub}</p>
          <p className="upload-requirements">Detect, rename, map, and group multiple PDFs in one batch</p>
        </button>
      ) : (
        <label
          className={`upload-area ${dragActive ? 'drag-active' : ''}`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={openFileDialog}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              openFileDialog();
            }
          }}
        >
          <div
            className={variant === 'fillable' ? 'upload-icon upload-icon--template' : 'upload-icon upload-icon--pdf'}
            aria-hidden="true"
          />
          <h3>{heading}</h3>
          <p>
            {sub}
          </p>
          <p className="upload-requirements">Supports PDF files up to 50MB</p>
          <input
            ref={fileInputRef}
            id={inputId}
            name={inputName}
            type="file"
            accept=".pdf"
            onChange={handleFileInput}
            className="upload-input"
            aria-label={heading || 'Upload PDF'}
          />
        </label>
      )}
    </div>
  );
};

export default UploadComponent;
