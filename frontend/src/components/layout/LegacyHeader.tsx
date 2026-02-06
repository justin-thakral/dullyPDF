/**
 * Legacy header layout for the older multi-step flow.
 */
import React from 'react';
import './LegacyHeader.css';

interface LegacyHeaderProps {
  currentView: 'homepage' | 'upload' | 'processing' | 'editor';
  onNavigateHome: () => void;
  showBackButton?: boolean;
  userEmail?: string | null;
  onOpenProfile?: () => void;
  onSignOut?: () => void;
  onSignIn?: () => void;
}

/**
 * Render the legacy header based on the current view.
 */
const LegacyHeader: React.FC<LegacyHeaderProps> = ({
  currentView,
  onNavigateHome,
  showBackButton = false,
  userEmail,
  onOpenProfile,
  onSignOut,
  onSignIn,
}) => {
  /**
   * Map view names to display titles.
   */
  const getTitle = () => {
    switch (currentView) {
      case 'homepage':
        return 'PDF Form Generator';
      case 'upload':
        return 'Upload PDF Document';
      case 'processing':
        return 'Processing Document';
      case 'editor':
        return 'Form Field Editor';
      default:
        return 'PDF Form Generator';
    }
  };

  /**
   * Map view names to descriptive subtitle text.
   */
  const getDescription = () => {
    switch (currentView) {
      case 'homepage':
        return 'Transform PDFs into interactive forms with AI-powered field detection';
      case 'upload':
        return 'Select a PDF file to begin automatic form field detection';
      case 'processing':
        return 'Analyzing document and detecting form fields using AI';
      case 'editor':
        return 'Review and edit detected form fields with precision tools';
      default:
        return 'Professional PDF form generation tools';
    }
  };

  const userInitial = userEmail ? userEmail.charAt(0).toUpperCase() : null;

  return (
    <header className="app-header">
      <div className="header-content">
        <div className="header-left">
          {showBackButton && (
            <button
              onClick={onNavigateHome}
              className="back-button"
              aria-label="Return to homepage"
            >
              <span className="back-icon">←</span>
              Home
            </button>
          )}
          <div className="header-branding">
            <h1 className="header-title">{getTitle()}</h1>
            <p className="header-description">{getDescription()}</p>
          </div>
        </div>

        <div className="header-right">
          <a className="header-link-button" href="/privacy">
            Privacy &amp; Terms
          </a>
          {userEmail ? (
            <div className="header-account">
              {onOpenProfile ? (
                <button
                  type="button"
                  className="header-account__button header-account__button--interactive"
                  onClick={onOpenProfile}
                  title="Open profile"
                >
                  <div className="user-avatar" aria-hidden="true">
                    {userInitial}
                  </div>
                  <div className="user-detail">
                    <span className="user-email" title={userEmail}>
                      {userEmail}
                    </span>
                  </div>
                </button>
              ) : (
                <div className="header-account__button">
                  <div className="user-avatar" aria-hidden="true">
                    {userInitial}
                  </div>
                  <div className="user-detail">
                    <span className="user-email" title={userEmail}>
                      {userEmail}
                    </span>
                  </div>
                </div>
              )}
              {onSignOut && (
                <button type="button" className="signout-button" onClick={onSignOut}>
                  Sign out
                </button>
              )}
            </div>
          ) : (
            onSignIn && (
              <button type="button" className="signin-button" onClick={onSignIn}>
                Sign in
              </button>
            )
          )}
          <div className="header-logo">
            <img className="logo-image" src="/DullyPDFLogoImproved.png" alt="DullyPDF" />
            <span className="logo-text">DullyPDF</span>
          </div>
        </div>
      </div>
    </header>
  );
};

export default LegacyHeader;
