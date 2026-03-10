import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './Dialog.css';

export type DialogTone = 'default' | 'danger';

const OPEN_DIALOG_STACK: string[] = [];

function addOpenDialog(dialogId: string) {
  OPEN_DIALOG_STACK.push(dialogId);
}

function removeOpenDialog(dialogId: string) {
  const index = OPEN_DIALOG_STACK.lastIndexOf(dialogId);
  if (index >= 0) {
    OPEN_DIALOG_STACK.splice(index, 1);
  }
}

function isTopmostDialog(dialogId: string) {
  return OPEN_DIALOG_STACK[OPEN_DIALOG_STACK.length - 1] === dialogId;
}

type DialogShellProps = {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  onClose?: () => void;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
};

type DialogFrameProps = {
  open: boolean;
  onClose?: () => void;
  className?: string;
  labelledBy?: string;
  describedBy?: string;
  children: React.ReactNode;
};

function useDialogBodyLock(open: boolean) {
  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined;
    const body = document.body;
    const activeCount = Number(body.dataset.uiDialogCount || '0');
    body.dataset.uiDialogCount = String(activeCount + 1);
    body.classList.add('ui-dialog-open');

    return () => {
      const nextCount = Math.max(0, Number(body.dataset.uiDialogCount || '1') - 1);
      if (nextCount === 0) {
        delete body.dataset.uiDialogCount;
        body.classList.remove('ui-dialog-open');
        return;
      }
      body.dataset.uiDialogCount = String(nextCount);
    };
  }, [open]);
}

export function DialogFrame({
  open,
  onClose,
  className,
  labelledBy,
  describedBy,
  children,
}: DialogFrameProps) {
  const dialogId = useId();

  useDialogBodyLock(open);

  useEffect(() => {
    if (!open) return undefined;
    addOpenDialog(dialogId);
    return () => removeOpenDialog(dialogId);
  }, [dialogId, open]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (!isTopmostDialog(dialogId)) return;
      event.preventDefault();
      onClose?.();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [dialogId, onClose, open]);

  if (!open) return null;

  const dialogClassName = ['ui-dialog', className].filter(Boolean).join(' ');
  const dialogContent = (
    <div className="ui-dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className={dialogClassName}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );

  if (typeof document === 'undefined') {
    return dialogContent;
  }

  return createPortal(dialogContent, document.body);
}

function DialogShell({ open, title, description, onClose, children, footer, className }: DialogShellProps) {
  const titleId = useId();
  const descId = useId();

  return (
    <DialogFrame
      open={open}
      onClose={onClose}
      className={className}
      labelledBy={titleId}
      describedBy={description ? descId : undefined}
    >
      <header className="ui-dialog__header">
        <h2 className="ui-dialog__title" id={titleId}>
          {title}
        </h2>
      </header>
      {description ? (
        <div className="ui-dialog__message" id={descId}>
          {description}
        </div>
      ) : null}
      {children}
      {footer}
    </DialogFrame>
  );
}

export function Dialog(props: DialogShellProps) {
  return <DialogShell {...props} />;
}

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string | null;
  tone?: DialogTone;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Continue',
  cancelLabel,
  tone = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) {
      confirmRef.current?.focus();
    }
  }, [open]);

  const primaryClass = tone === 'danger' ? 'ui-button ui-button--danger' : 'ui-button ui-button--primary';

  const resolvedCancelLabel = cancelLabel ?? 'Cancel';

  return (
    <DialogShell open={open} title={title} description={description} onClose={onCancel}>
      <div className="ui-dialog__actions">
        {cancelLabel === null ? null : (
          <button className="ui-button ui-button--ghost" type="button" onClick={onCancel}>
            {resolvedCancelLabel}
          </button>
        )}
        <button className={primaryClass} type="button" onClick={onConfirm} ref={confirmRef}>
          {confirmLabel}
        </button>
      </div>
    </DialogShell>
  );
}

export type PromptDialogProps = {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
  defaultValue?: string;
  placeholder?: string;
  requireValue?: boolean;
  onSubmit: (value: string) => void;
  onCancel: () => void;
};

export function PromptDialog({
  open,
  title,
  description,
  confirmLabel = 'Save',
  cancelLabel = 'Cancel',
  tone = 'default',
  defaultValue = '',
  placeholder,
  requireValue = false,
  onSubmit,
  onCancel,
}: PromptDialogProps) {
  const [value, setValue] = useState(defaultValue);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setValue(defaultValue);
    inputRef.current?.focus();
  }, [defaultValue, open]);

  const primaryClass = tone === 'danger' ? 'ui-button ui-button--danger' : 'ui-button ui-button--primary';
  const canSubmit = !requireValue || value.trim().length > 0;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit(value);
  };

  return (
    <DialogShell open={open} title={title} description={description} onClose={onCancel}>
      <div className="ui-dialog__input-row">
        <input
          ref={inputRef}
          className="ui-dialog__input"
          type="text"
          value={value}
          placeholder={placeholder}
          id="dialog-input"
          name="dialog-input"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
        />
      </div>
      <div className="ui-dialog__actions">
        {cancelLabel ? (
          <button className="ui-button ui-button--ghost" type="button" onClick={onCancel}>
            {cancelLabel}
          </button>
        ) : null}
        <button className={primaryClass} type="button" onClick={() => onSubmit(value)} disabled={!canSubmit}>
          {confirmLabel}
        </button>
      </div>
    </DialogShell>
  );
}

export type SavedFormsLimitDialogProps = {
  open: boolean;
  maxSavedForms: number;
  savedForms: Array<{ id: string; name: string; createdAt: string }>;
  deletingFormId?: string | null;
  onDelete: (formId: string) => void;
  onClose: () => void;
};

export function SavedFormsLimitDialog({
  open,
  maxSavedForms,
  savedForms,
  deletingFormId = null,
  onDelete,
  onClose,
}: SavedFormsLimitDialogProps) {
  const description = `Maxed saved forms (${maxSavedForms} max). Delete one of these or exit out without saving.`;

  return (
    <DialogShell open={open} title="Saved forms limit reached" description={description} onClose={onClose}>
      <div className="saved-forms-dialog">
        {savedForms.length === 0 ? (
          <p className="saved-forms-dialog__empty">No saved forms are available.</p>
        ) : (
          <div className="saved-forms-dialog__list saved-forms-list">
            {savedForms.map((form) => {
              const isDeleting = deletingFormId === form.id;
              const parsedDate = form.createdAt ? new Date(form.createdAt) : null;
              const dateLabel =
                parsedDate && !Number.isNaN(parsedDate.getTime())
                  ? parsedDate.toLocaleDateString()
                  : 'Unknown date';
              return (
                <div key={form.id} className="saved-form-row">
                  <div className="saved-form-item saved-form-item--static">
                    <div className="saved-form-name">{form.name}</div>
                    <div className="saved-form-date">{dateLabel}</div>
                  </div>
                  <button
                    type="button"
                    className="saved-form-delete"
                    onClick={() => {
                      if (!isDeleting) onDelete(form.id);
                    }}
                    disabled={isDeleting}
                    aria-label={`Delete saved form ${form.name}`}
                  >
                    {isDeleting ? 'Deleting...' : 'Delete'}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="ui-dialog__actions">
        <button className="ui-button ui-button--ghost" type="button" onClick={onClose}>
          Exit without saving
        </button>
      </div>
    </DialogShell>
  );
}
