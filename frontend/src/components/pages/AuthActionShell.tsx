import type { ReactNode } from 'react';

type AuthActionShellProps = {
  supportLabel: string;
  badge: string;
  title: string;
  description: ReactNode;
  toneClass: string;
  summaryTitle: string;
  summaryItems: ReactNode[];
  body?: ReactNode;
  footer?: ReactNode;
};

/**
 * Shared presentation shell for branded account-action pages.
 *
 * The shell keeps the visual treatment consistent between the public Firebase
 * action handler and the signed-in verification gate while allowing each flow
 * to inject its own interactive body content.
 */
const AuthActionShell = ({
  supportLabel,
  badge,
  title,
  description,
  toneClass,
  summaryTitle,
  summaryItems,
  body,
  footer,
}: AuthActionShellProps) => (
  <div className="verify-page">
    <div className={`verify-card verify-action-card ${toneClass}`}>
      <div className="verify-action-shell">
        <div className="verify-action-brand">
          <a className="verify-action-brandmark" href="/" aria-label="Open DullyPDF homepage">
            <img src="/DullyPDFLogoImproved.png" alt="" />
            <span>DullyPDF</span>
          </a>
          <span className="verify-action-support">{supportLabel}</span>
        </div>

        <div className="verify-header">
          <div className="verify-badge">{badge}</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>

      <div className="verify-action-summary">
        <h2>{summaryTitle}</h2>
        <ul>
          {summaryItems.map((entry, index) => (
            <li key={typeof entry === 'string' ? entry : `summary-item-${index}`}>{entry}</li>
          ))}
        </ul>
      </div>

      {body}
      {footer}
    </div>
  </div>
);

export default AuthActionShell;
