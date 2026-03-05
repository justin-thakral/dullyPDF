/**
 * Top navigation bar with zoom, user info, and data source actions.
 */
import { useEffect, useRef, useState } from 'react';
import type { DataSourceKind } from '../../types';

type HeaderBarProps = {
  pageCount: number;
  currentPage: number;
  scale: number;
  userEmail?: string;
  onOpenProfile?: () => void;
  onSignIn?: () => void;
  onSignOut?: () => void;
  onScaleChange: (next: number) => void;
  onNavigateHome: () => void;
  dataSourceKind?: DataSourceKind;
  dataSourceLabel?: string | null;
  onChooseDataSource?: (kind: Exclude<DataSourceKind, 'none'>) => void;
  onClearDataSource?: () => void;
  mappingInProgress?: boolean;
  mapSchemaInProgress?: boolean;
  hasMappedSchema?: boolean;
  onMapSchema?: () => void;
  canMapSchema?: boolean;
  mapSchemaDisabledReason?: string | null;
  renameInProgress?: boolean;
  hasRenamedFields?: boolean;
  onRename?: () => void;
  onRenameAndMap?: () => void;
  canRename?: boolean;
  canRenameAndMap?: boolean;
  renameDisabledReason?: string | null;
  renameAndMapDisabledReason?: string | null;
  onOpenSearchFill?: () => void;
  canSearchFill?: boolean;
  onDownload?: () => void;
  onSaveToProfile?: () => void;
  downloadInProgress?: boolean;
  saveInProgress?: boolean;
  canDownload?: boolean;
  canSave?: boolean;
  demoLocked?: boolean;
  onDemoLockedAction?: () => void;
};

function isSchemaPrerequisiteHint(reason: string | null | undefined): boolean {
  return reason === 'Connect a CSV, Excel, JSON, or TXT schema source first.' ||
    reason === 'Upload schema headers before mapping.' ||
    reason === 'Schema metadata is required before mapping.';
}

/**
 * Render header controls for navigation, mapping, and account actions.
 */
export function HeaderBar({
  pageCount,
  currentPage,
  scale,
  userEmail,
  onOpenProfile,
  onSignIn,
  onSignOut,
  onScaleChange,
  onNavigateHome,
  dataSourceKind = 'none',
  dataSourceLabel,
  onChooseDataSource,
  onClearDataSource,
  mappingInProgress = false,
  mapSchemaInProgress = false,
  hasMappedSchema = false,
  onMapSchema,
  canMapSchema = false,
  mapSchemaDisabledReason = null,
  renameInProgress = false,
  hasRenamedFields = false,
  onRename,
  onRenameAndMap,
  canRename = false,
  canRenameAndMap = false,
  renameDisabledReason = null,
  renameAndMapDisabledReason = null,
  onOpenSearchFill,
  canSearchFill = false,
  onDownload,
  onSaveToProfile,
  downloadInProgress = false,
  saveInProgress = false,
  canDownload = false,
  canSave = false,
  demoLocked = false,
  onDemoLockedAction,
}: HeaderBarProps) {
  const hasMappingControls = Boolean(
    onChooseDataSource || onMapSchema || onRename || onRenameAndMap || onOpenSearchFill,
  );
  const userInitial = userEmail ? userEmail.charAt(0).toUpperCase() : null;
  const mapSchemaLabel = mapSchemaInProgress ? 'Mapping' : hasMappedSchema ? 'Mapped' : 'Map Schema';
  const renameLabel = renameInProgress ? 'Renaming' : hasRenamedFields ? 'Renamed' : 'Rename';
  const renameAndMapLabel = mapSchemaInProgress ? 'Mapping' : 'Rename + Map';
  const demoOverride = demoLocked && Boolean(onDemoLockedAction);
  const deferSchemaPrereqHint = isSchemaPrerequisiteHint(mapSchemaDisabledReason);
  const disableMapSchema = demoOverride
    ? false
    : mappingInProgress || mapSchemaInProgress || (!canMapSchema && !deferSchemaPrereqHint);
  const disableRename =
    demoOverride ? false : !canRename || mappingInProgress || renameInProgress || mapSchemaInProgress;
  const disableRenameAndMap =
    demoOverride ? false : !canRenameAndMap || mappingInProgress || renameInProgress || mapSchemaInProgress;
  const disableSearch = !canSearchFill || mappingInProgress;
  const showSearchHint = !canSearchFill;
  const rawActionHint = demoOverride
    ? null
    : disableMapSchema
      ? mapSchemaDisabledReason
      : disableRenameAndMap
        ? renameAndMapDisabledReason
        : disableRename
          ? renameDisabledReason
          : null;
  const actionHint = isSchemaPrerequisiteHint(rawActionHint) ? null : rawActionHint;
  const mapSchemaTooltip = disableMapSchema
    ? mapSchemaDisabledReason || 'Mapping is unavailable right now.'
    : 'Map PDF field names to schema headers';
  const renameTooltip = disableRename
    ? renameDisabledReason || 'Rename is unavailable right now.'
    : 'Rename PDF field names using OpenAI';
  const renameAndMapTooltip = disableRenameAndMap
    ? renameAndMapDisabledReason || 'Rename + Map is unavailable right now.'
    : 'Run Rename and Map in one step';
  const disableDownload = demoOverride ? false : !canDownload || downloadInProgress;
  const disableSave = demoOverride ? false : !canSave || saveInProgress;

  const [showDataMenu, setShowDataMenu] = useState(false);
  const isConnected = dataSourceKind !== 'none';
  const connectedKind =
    dataSourceKind === 'excel'
      ? 'XLS'
      : dataSourceKind === 'txt'
        ? 'TXT'
        : dataSourceKind.toUpperCase();
  const dataSourceTitle = isConnected ? `Connected ${connectedKind}` : 'Schema';
  const dataSourceSubtitle = isConnected ? null : 'CSV/XLS/JSON/TXT';
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
            min={0.25}
            max={10}
            step={0.05}
            value={scale}
            id="header-zoom"
            name="header-zoom"
            aria-label="Zoom"
            onChange={(event) => onScaleChange(Number(event.target.value))}
          />
          <span className="ui-chip__value">{Math.round(scale * 100)}%</span>
        </div>
      </div>
      <div className="ui-header__actions">
        <div className="ui-header__actions-top">
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
            <picture>
              <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
              <img className="logo-image" src="/DullyPDFLogoImproved.png" alt="DullyPDF" decoding="async" />
            </picture>
            <span className="logo-text">DullyPDF</span>
          </div>
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
                  data-demo-target="data-source"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    setShowDataMenu((prev) => !prev);
                  }}
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
                        if (demoOverride) {
                          onDemoLockedAction?.();
                          return;
                        }
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
                        if (demoOverride) {
                          onDemoLockedAction?.();
                          return;
                        }
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
                        if (demoOverride) {
                          onDemoLockedAction?.();
                          return;
                        }
                        setShowDataMenu(false);
                        onChooseDataSource?.('json');
                      }}
                    >
                      <span className="data-source__badge">JSON</span>
                      <span>JSON file…</span>
                    </button>
                    <button
                      type="button"
                      className="data-source__item"
                      role="menuitem"
                      onClick={() => {
                        if (demoOverride) {
                          onDemoLockedAction?.();
                          return;
                        }
                        setShowDataMenu(false);
                        onChooseDataSource?.('txt');
                      }}
                    >
                      <span className="data-source__badge">TXT</span>
                      <span>TXT schema…</span>
                    </button>
                    {dataSourceKind !== 'none' && onClearDataSource ? (
                      <button
                        type="button"
                        className="data-source__item data-source__item--danger"
                        role="menuitem"
                        onClick={() => {
                          if (demoOverride) {
                            onDemoLockedAction?.();
                            return;
                          }
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
              {onRename ? (
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  data-demo-target="openai-rename"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    onRename?.();
                  }}
                  disabled={disableRename}
                  title={renameTooltip}
                >
                  {renameLabel}
                </button>
              ) : null}
              <button
                className="ui-button ui-button--ghost ui-button--compact"
                type="button"
                data-demo-target="openai-remap"
                aria-disabled={disableMapSchema}
                onClick={() => {
                  if (demoOverride) {
                    onDemoLockedAction?.();
                    return;
                  }
                  onMapSchema?.();
                }}
                disabled={disableMapSchema}
                title={mapSchemaTooltip}
              >
                {mapSchemaLabel}
              </button>
              {onRenameAndMap ? (
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    onRenameAndMap?.();
                  }}
                  disabled={disableRenameAndMap}
                  title={renameAndMapTooltip}
                >
                  {renameAndMapLabel}
                </button>
              ) : null}
              {onOpenSearchFill ? (
                <div className="ui-header__search-fill">
                  <button
                    className="ui-button ui-button--ghost ui-button--compact"
                    type="button"
                    data-demo-target="search-fill"
                    onClick={onOpenSearchFill}
                    disabled={disableSearch}
                  >
                    Search, Fill &amp; Clear
                  </button>
                  {showSearchHint ? (
                    <span className="ui-header__search-hint">Requires CSV/Excel/JSON rows</span>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
          {actionHint ? <span className="ui-header__action-hint">{actionHint}</span> : null}
          {onSaveToProfile ? (
            <div className="ui-header__save-row ui-header__save-row--inline">
              {onDownload ? (
                <button
                  className="ui-button ui-button--primary ui-button--compact ui-header__save"
                  type="button"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    onDownload?.();
                  }}
                  disabled={disableDownload}
                >
                  {downloadInProgress ? 'Downloading...' : 'Download'}
                </button>
              ) : null}
              <button
                className="ui-button ui-button--primary ui-button--compact ui-header__save"
                type="button"
                onClick={() => {
                  if (demoOverride) {
                    onDemoLockedAction?.();
                    return;
                  }
                  onSaveToProfile?.();
                }}
                disabled={disableSave}
              >
                {saveInProgress ? 'Saving...' : 'Save'}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </header>
  );
}
