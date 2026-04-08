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

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(', ');

function isVisibleElement(element: HTMLElement) {
  if (element.hasAttribute('hidden') || element.getAttribute('aria-hidden') === 'true') return false;
  if (typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') return true;
  const style = window.getComputedStyle(element);
  return style.display !== 'none' && style.visibility !== 'hidden';
}

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    return isVisibleElement(element);
  });
}

type DialogShellProps = {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  onClose?: () => void;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  headerActions?: React.ReactNode;
  showCloseButton?: boolean;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
};

type DialogFrameProps = {
  open: boolean;
  onClose?: () => void;
  className?: string;
  labelledBy?: string;
  describedBy?: string;
  children: React.ReactNode;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
};

type DialogCloseButtonProps = {
  onClick: () => void;
  label?: string;
  className?: string;
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
  closeOnBackdrop = true,
  closeOnEscape = true,
}: DialogFrameProps) {
  const dialogId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useDialogBodyLock(open);

  useEffect(() => {
    if (!open) return undefined;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    addOpenDialog(dialogId);
    return () => removeOpenDialog(dialogId);
  }, [dialogId, open]);

  useEffect(() => {
    if (!open) return undefined;
    const dialogElement = dialogRef.current;
    const frame = window.requestAnimationFrame(() => {
      if (!dialogElement) return;
      if (dialogElement.contains(document.activeElement)) return;
      dialogElement.focus();
    });

    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (open) return undefined;
    const target = restoreFocusRef.current;
    if (!target || !target.isConnected) return undefined;
    target.focus();
    restoreFocusRef.current = null;
    return undefined;
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isTopmostDialog(dialogId)) return;
      if (event.key === 'Escape' && closeOnEscape) {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== 'Tab') return;

      const dialogElement = dialogRef.current;
      if (!dialogElement) return;
      const focusable = getFocusableElements(dialogElement);
      if (focusable.length === 0) {
        event.preventDefault();
        dialogElement.focus();
        return;
      }

      const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const activeInsideDialog = active ? dialogElement.contains(active) : false;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (!activeInsideDialog) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }

      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
        return;
      }

      if (event.shiftKey && (active === first || active === dialogElement)) {
        event.preventDefault();
        last.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [closeOnEscape, dialogId, onClose, open]);

  if (!open) return null;

  const dialogClassName = ['ui-dialog', className].filter(Boolean).join(' ');
  const dialogContent = (
    <div
      className="ui-dialog-backdrop"
      role="presentation"
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div
        ref={dialogRef}
        className={dialogClassName}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
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

export function DialogCloseButton({
  onClick,
  label = 'Close dialog',
  className,
}: DialogCloseButtonProps) {
  const buttonClassName = ['ui-dialog__close', className].filter(Boolean).join(' ');

  return (
    <button type="button" className={buttonClassName} onClick={onClick} aria-label={label}>
      ×
    </button>
  );
}

function DialogShell({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  className,
  headerActions,
  showCloseButton = true,
  closeOnBackdrop = true,
  closeOnEscape = true,
}: DialogShellProps) {
  const titleId = useId();
  const descId = useId();

  return (
    <DialogFrame
      open={open}
      onClose={onClose}
      className={className}
      labelledBy={titleId}
      describedBy={description ? descId : undefined}
      closeOnBackdrop={closeOnBackdrop}
      closeOnEscape={closeOnEscape}
    >
      <header className="ui-dialog__header">
        <h2 className="ui-dialog__title" id={titleId}>
          {title}
        </h2>
        {headerActions || (showCloseButton && onClose) ? (
          <div className="ui-dialog__header-actions">
            {headerActions}
            {showCloseButton && onClose ? (
              <DialogCloseButton onClick={onClose} label={`Close ${title} dialog`} />
            ) : null}
          </div>
        ) : null}
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
  onClose?: () => void;
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
  onClose,
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
    <DialogShell open={open} title={title} description={description} onClose={onClose ?? onCancel}>
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

type PromptDialogBodyProps = Omit<PromptDialogProps, 'open'>;

function PromptDialogBody({
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
}: PromptDialogBodyProps) {
  const [value, setValue] = useState(defaultValue);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const primaryClass = tone === 'danger' ? 'ui-button ui-button--danger' : 'ui-button ui-button--primary';
  const canSubmit = !requireValue || value.trim().length > 0;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit(value);
  };

  return (
    <DialogShell open title={title} description={description} onClose={onCancel}>
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
  if (!open) {
    return null;
  }

  return (
    <PromptDialogBody
      key={`${title}:${defaultValue}`}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      cancelLabel={cancelLabel}
      tone={tone}
      defaultValue={defaultValue}
      placeholder={placeholder}
      requireValue={requireValue}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />
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
