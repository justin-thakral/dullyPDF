import React, { useRef, useState } from 'react';
import './UploadComponent.css';

interface UploadComponentProps {
  onFileUpload?: (file: File) => void;
  onValidationError?: (message: string) => void;
  onSelectSavedForm?: (formId: string) => void;
  onDeleteSavedForm?: (formId: string) => void;
  title?: string;
  subtitle?: string;
  variant?: 'detect' | 'fillable' | 'saved';
  savedForms?: Array<{ id: string; name: string; createdAt: string }>;
  deletingFormId?: string | null;
}

const UploadComponent: React.FC<UploadComponentProps> = ({
  onFileUpload,
  onValidationError,
  onSelectSavedForm,
  onDeleteSavedForm,
  title,
  subtitle,
  variant = 'detect',
  savedForms = [],
  deletingFormId = null,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

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

  const handleFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
    event.target.value = '';
  };

  const handleDrag = (event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.type === 'dragenter' || event.type === 'dragover') {
      setDragActive(true);
    } else if (event.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);

    const file = event.dataTransfer.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
  };

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

  const heading =
    title ??
    (variant === 'fillable'
      ? 'Upload Fillable PDF Template'
      : variant === 'saved'
        ? 'Your Saved Forms'
        : 'Upload PDF Document');
  const sub =
    subtitle ??
    (variant === 'fillable'
      ? 'Open your existing fillable PDF directly in the editor'
      : variant === 'saved'
        ? 'Select a form from your saved templates'
        : 'Drag and drop your PDF file here, or click to browse');

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
          {savedForms.length === 0 ? (
            <p className="upload-requirements">No saved forms yet. Save a form to see it here.</p>
          ) : (
            <div className="saved-forms-list">
              {savedForms.map((form) => {
                const isDeleting = deletingFormId === form.id;
                const parsedDate = form.createdAt ? new Date(form.createdAt) : null;
                const dateLabel =
                  parsedDate && !Number.isNaN(parsedDate.getTime())
                    ? parsedDate.toLocaleDateString()
                    : 'Unknown date';
                return (
                  <div key={form.id} className="saved-form-row">
                    <button
                      type="button"
                      className="saved-form-item"
                      onClick={() => {
                        if (!isDeleting) onSelectSavedForm?.(form.id);
                      }}
                      disabled={isDeleting}
                    >
                      <div className="saved-form-name">{form.name}</div>
                      <div className="saved-form-date">{dateLabel}</div>
                    </button>
                    {onDeleteSavedForm && (
                      <button
                        type="button"
                        className="saved-form-delete"
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
    );
  }

  return (
    <div className={`upload-container ${variant === 'fillable' ? 'upload--fillable' : 'upload--detect'}`}>
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
          {sub} {variant !== 'fillable' && <span className="upload-link">click to browse</span>}
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
    </div>
  );
};

export default UploadComponent;
