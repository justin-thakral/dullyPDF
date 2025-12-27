type HeaderBarProps = {
  pageCount: number;
  currentPage: number;
  scale: number;
  userEmail?: string;
  onSignIn?: () => void;
  onSignOut?: () => void;
  onScaleChange: (next: number) => void;
  onNavigateHome: () => void;
  connId?: string | null;
  mappingInProgress?: boolean;
  mapDbInProgress?: boolean;
  mappingError?: string | null;
  onConnectDb?: () => void;
  onDisconnectDb?: () => void;
  onMapDb?: () => void;
  onOpenFieldMapper?: () => void;
  onDownload?: () => void;
  onSaveToProfile?: () => void;
  downloadInProgress?: boolean;
  saveInProgress?: boolean;
  canDownload?: boolean;
  canSave?: boolean;
};

export function HeaderBar({
  pageCount,
  currentPage,
  scale,
  userEmail,
  onSignIn,
  onSignOut,
  onScaleChange,
  onNavigateHome,
  connId,
  mappingInProgress = false,
  mapDbInProgress = false,
  mappingError,
  onConnectDb,
  onDisconnectDb,
  onMapDb,
  onOpenFieldMapper,
  onDownload,
  onSaveToProfile,
  downloadInProgress = false,
  saveInProgress = false,
  canDownload = false,
  canSave = false,
}: HeaderBarProps) {
  const hasMappingControls = Boolean(onConnectDb || onDisconnectDb || onMapDb || onOpenFieldMapper);
  const userInitial = userEmail ? userEmail.charAt(0).toUpperCase() : null;
  const mapDbLabel = mapDbInProgress ? 'Loading' : 'Map DB';
  const disableMapDb = !connId || mappingInProgress || mapDbInProgress;

  return (
    <header className="ui-header">
      <div className="ui-header__brand">
        <button
          type="button"
          className="back-button ui-header__back"
          onClick={onNavigateHome}
          aria-label="Return to homepage"
        >
          <span className="back-icon">←</span>
          Home
        </button>
        <div>
          <p className="ui-header__kicker">DullyPDF</p>
          <h1 className="ui-header__title">Form Field Editor</h1>
        </div>
      </div>
      <div className="ui-header__meta">
        <div className="ui-chip">
          <span className="ui-chip__label">Page</span>
          <span className="ui-chip__value">
            {pageCount > 0 ? `${currentPage} / ${pageCount}` : '--'}
          </span>
        </div>
        <div className="ui-chip ui-chip--slider">
          <span className="ui-chip__label">Zoom</span>
          <input
            className="ui-zoom"
            type="range"
            min={0.6}
            max={2}
            step={0.05}
            value={scale}
            onChange={(event) => onScaleChange(Number(event.target.value))}
          />
          <span className="ui-chip__value">{Math.round(scale * 100)}%</span>
        </div>
      </div>
      <div className="ui-header__actions">
        <div className="ui-header__actions-col ui-header__actions-col--left">
          {userEmail ? (
            <div className="header-account">
              <div className="user-avatar" aria-hidden="true">
                {userInitial}
              </div>
              <div className="user-detail">
                <span className="user-email" title={userEmail}>
                  {userEmail}
                </span>
              </div>
              {onSignOut ? (
                <button type="button" className="signout-button" onClick={onSignOut}>
                  Sign out
                </button>
              ) : null}
            </div>
          ) : onSignIn ? (
            <button type="button" className="signin-button" onClick={onSignIn}>
              Sign in
            </button>
          ) : null}
          {hasMappingControls ? (
            <div className="ui-header__tools-row">
              <div className="ui-header__tools">
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={connId ? onDisconnectDb : onConnectDb}
                  disabled={mappingInProgress}
                >
                  {connId ? 'Disconnect DB' : 'Connect DB'}
                </button>
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={onMapDb}
                  disabled={disableMapDb}
                >
                  {mapDbLabel}
                </button>
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={onOpenFieldMapper}
                  disabled={mappingInProgress}
                >
                  Map via .txt
                </button>
              </div>
              {mappingError ? <span className="ui-header__error">{mappingError}</span> : null}
            </div>
          ) : null}
        </div>
        <div className="ui-header__actions-col ui-header__actions-col--right">
          <div className="header-logo">
            <img className="logo-image" src="/DullyPDF.png" alt="DullyPDF" />
            <span className="logo-text">DullyPDF</span>
          </div>
          {onSaveToProfile ? (
            <div className="ui-header__save-row">
              {onDownload ? (
                <button
                  className="ui-button ui-button--primary ui-button--compact ui-header__save"
                  type="button"
                  onClick={onDownload}
                  disabled={!canDownload || downloadInProgress}
                >
                  {downloadInProgress ? 'Downloading...' : 'Download'}
                </button>
              ) : null}
              <button
                className="ui-button ui-button--primary ui-button--compact ui-header__save"
                type="button"
                onClick={onSaveToProfile}
                disabled={!canSave || saveInProgress}
              >
                {saveInProgress ? 'Saving...' : 'Save'}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
