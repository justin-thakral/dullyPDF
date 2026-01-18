import './Alert.css';

export type AlertTone = 'error' | 'warning' | 'info' | 'success';
export type AlertVariant = 'inline' | 'banner' | 'pill';
export type AlertSize = 'md' | 'sm';

type AlertProps = {
  tone?: AlertTone;
  variant?: AlertVariant;
  size?: AlertSize;
  title?: string;
  message: string;
  onDismiss?: () => void;
  dismissLabel?: string;
  className?: string;
};

/**
 * Shared alert component with tone + placement variants.
 */
export function Alert({
  tone = 'info',
  variant = 'inline',
  size = 'md',
  title,
  message,
  onDismiss,
  dismissLabel = 'Dismiss',
  className,
}: AlertProps) {
  const role = tone === 'error' || tone === 'warning' ? 'alert' : 'status';
  const ariaLive = tone === 'error' || tone === 'warning' ? 'assertive' : 'polite';
  const classes = [
    'ui-alert',
    `ui-alert--${tone}`,
    `ui-alert--${variant}`,
    `ui-alert--${size}`,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes} role={role} aria-live={ariaLive}>
      <span className="ui-alert__accent" aria-hidden="true" />
      <div className="ui-alert__content">
        {title ? <p className="ui-alert__title">{title}</p> : null}
        <p className="ui-alert__message">{message}</p>
      </div>
      {onDismiss ? (
        <button className="ui-alert__dismiss" type="button" onClick={onDismiss}>
          {dismissLabel}
        </button>
      ) : null}
    </div>
  );
}
