import React, { useEffect, useId, useRef, useState } from 'react';
import './Dialog.css';

export type DialogTone = 'default' | 'danger';

type DialogShellProps = {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  onClose?: () => void;
  children?: React.ReactNode;
  footer?: React.ReactNode;
};

function DialogShell({ open, title, description, onClose, children, footer }: DialogShellProps) {
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      onClose?.();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="ui-dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="ui-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        onClick={(event) => event.stopPropagation()}
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
      </div>
    </div>
  );
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
