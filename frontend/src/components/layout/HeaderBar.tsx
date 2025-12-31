import { useEffect, useRef, useState } from 'react';

export type DataSourceKind = 'sql' | 'csv' | 'excel' | 'txt' | 'none';

type HeaderBarProps = {
  pageCount: number;
  currentPage: number;
  scale: number;
  userEmail?: string;
  onSignIn?: () => void;
  onSignOut?: () => void;
  onScaleChange: (next: number) => void;
  onNavigateHome: () => void;
  dataSourceKind?: DataSourceKind;
  dataSourceLabel?: string | null;
  onChooseDataSource?: (kind: Exclude<DataSourceKind, 'none'>) => void;
  onDisconnectSql?: () => void;
  onClearDataSource?: () => void;
  mappingInProgress?: boolean;
  mapDbInProgress?: boolean;
  mappingError?: string | null;
  hasMappedDb?: boolean;
  onMapDb?: () => void;
  canMapDb?: boolean;
  onOpenSearchFill?: () => void;
  canSearchFill?: boolean;
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
  dataSourceKind = 'none',
  dataSourceLabel,
  onChooseDataSource,
  onDisconnectSql,
  onClearDataSource,
  mappingInProgress = false,
  mapDbInProgress = false,
  mappingError,
  hasMappedDb = false,
  onMapDb,
  canMapDb = false,
  onOpenSearchFill,
  canSearchFill = false,
  onDownload,
  onSaveToProfile,
  downloadInProgress = false,
  saveInProgress = false,
  canDownload = false,
  canSave = false,
}: HeaderBarProps) {
  const hasMappingControls = Boolean(onChooseDataSource || onMapDb || onOpenSearchFill);
  const userInitial = userEmail ? userEmail.charAt(0).toUpperCase() : null;
  const mapDbLabel = mapDbInProgress ? 'Loading' : hasMappedDb ? 'Mapped' : 'Map DB';
  const disableMapDb = !canMapDb || mappingInProgress || mapDbInProgress;
  const disableSearch = !canSearchFill || mappingInProgress;

  const [showDataMenu, setShowDataMenu] = useState(false);
  const isConnected = dataSourceKind !== 'none';
  const connectedKind =
    dataSourceKind === 'excel' ? 'XLS' : dataSourceKind.toUpperCase();
  const dataSourceTitle = isConnected ? `Connected ${connectedKind}` : 'Database';
  const dataSourceSubtitle = isConnected ? null : 'SQL/CSV/XLS/TXT';
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (!menuRef.current) return;
      if (menuRef.current.contains(target)) return;
      setShowDataMenu(false);
    };
    if (showDataMenu) {
      window.addEventListener('mousedown', handleClick);
    }
    return () => window.removeEventListener('mousedown', handleClick);
  }, [showDataMenu]);

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
        <div className="ui-header__actions-top">
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
          <div className="header-logo">
            <img className="logo-image" src="/DullyPDF.png" alt="DullyPDF" />
            <span className="logo-text">DullyPDF</span>
          </div>
        </div>
        {hasMappingControls || onSaveToProfile ? (
          <div className="ui-header__actions-bottom">
            {hasMappingControls ? (
              <div className="ui-header__tools">
                <div className="data-source" ref={menuRef}>
                  <button
                    className="ui-button ui-button--ghost ui-button--compact data-source__button"
                    type="button"
                    onClick={() => setShowDataMenu((prev) => !prev)}
                    disabled={mappingInProgress}
                    aria-haspopup="menu"
                    aria-expanded={showDataMenu}
                  >
                    <span className="data-source__title">{dataSourceTitle}</span>
                    {dataSourceSubtitle ? (
                      <span className="data-source__subtitle">{dataSourceSubtitle}</span>
                    ) : null}
                    <span className="data-source__caret" aria-hidden="true">
                      ▾
                    </span>
                  </button>
                  {showDataMenu ? (
                    <div className="data-source__menu" role="menu" aria-label="Choose data source">
                      {dataSourceLabel ? (
                        <div className="data-source__current" aria-label="Current source">
                          <span className="data-source__current-label">Current:</span>
                          <span className="data-source__current-value">{dataSourceLabel}</span>
                        </div>
                      ) : null}
                      <button
                        type="button"
                        className="data-source__item"
                        role="menuitem"
                        onClick={() => {
                          setShowDataMenu(false);
                          onChooseDataSource?.('sql');
                        }}
                      >
                        <span className="data-source__badge">SQL</span>
                        <span>SQL database…</span>
                      </button>
                      <button
                        type="button"
                        className="data-source__item"
                        role="menuitem"
                        onClick={() => {
                          setShowDataMenu(false);
                          onChooseDataSource?.('csv');
                        }}
                      >
                        <span className="data-source__badge">CSV</span>
                        <span>CSV file…</span>
                      </button>
                      <button
                        type="button"
                        className="data-source__item"
                        role="menuitem"
                        onClick={() => {
                          setShowDataMenu(false);
                          onChooseDataSource?.('excel');
                        }}
                      >
                        <span className="data-source__badge">XLS</span>
                        <span>Excel file…</span>
                      </button>
                      <button
                        type="button"
                        className="data-source__item"
                        role="menuitem"
                        onClick={() => {
                          setShowDataMenu(false);
                          onChooseDataSource?.('txt');
                        }}
                      >
                        <span className="data-source__badge">TXT</span>
                        <span>TXT field list…</span>
                      </button>
                      {dataSourceKind === 'sql' && onDisconnectSql ? (
                        <button
                          type="button"
                          className="data-source__item data-source__item--danger"
                          role="menuitem"
                          onClick={() => {
                            setShowDataMenu(false);
                            onDisconnectSql?.();
                          }}
                        >
                          Disconnect SQL
                        </button>
                      ) : null}
                      {dataSourceKind !== 'none' && dataSourceKind !== 'sql' && onClearDataSource ? (
                        <button
                          type="button"
                          className="data-source__item data-source__item--danger"
                          role="menuitem"
                          onClick={() => {
                            setShowDataMenu(false);
                            onClearDataSource?.();
                          }}
                        >
                          Clear data source
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={onMapDb}
                  disabled={disableMapDb}
                >
                  {mapDbLabel}
                </button>
                {onOpenSearchFill ? (
                  <button
                    className="ui-button ui-button--ghost ui-button--compact"
                    type="button"
                    onClick={onOpenSearchFill}
                    disabled={disableSearch}
                  >
                    Search &amp; Fill
                  </button>
                ) : null}
              </div>
            ) : null}
            {onSaveToProfile ? (
              <div className="ui-header__save-row ui-header__save-row--inline">
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
        ) : null}
        {mappingError ? <span className="ui-header__error">{mappingError}</span> : null}
      </div>
    </header>
  );
}
