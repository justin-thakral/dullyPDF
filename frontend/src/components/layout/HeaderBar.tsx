/**
 * Top navigation bar with zoom, user info, and data source actions.
 */
import { useEffect, useRef, useState } from 'react';
import type { DataSourceKind } from '../../types';

const HEADER_GROUP_TEMPLATE_TRIGGER_MAX_CHARS = 22;
const HEADER_GROUP_TEMPLATE_MENU_MAX_CHARS = 24;
const MIN_ZOOM_PERCENT = 25;
const MAX_ZOOM_PERCENT = 1000;

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
  groupName?: string | null;
  groupTemplates?: Array<{ id: string; name: string }>;
  groupTemplateStatuses?: Record<string, 'ready' | 'loading' | 'error'>;
  activeGroupTemplateId?: string | null;
  groupTemplateSwitchInProgress?: boolean;
  onSelectGroupTemplate?: (templateId: string) => void;
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
  onRenameAndMapGroup?: () => void;
  canRename?: boolean;
  canRenameAndMap?: boolean;
  canRenameAndMapGroup?: boolean;
  renameDisabledReason?: string | null;
  renameAndMapDisabledReason?: string | null;
  renameAndMapGroupDisabledReason?: string | null;
  renameAndMapGroupInProgress?: boolean;
  renameAndMapGroupButtonLabel?: string;
  onOpenSearchFill?: () => void;
  canSearchFill?: boolean;
  onOpenFillLink?: () => void;
  canFillLink?: boolean;
  onDownload?: () => void;
  onDownloadGroup?: () => void;
  onSaveToProfile?: () => void;
  downloadInProgress?: boolean;
  downloadGroupInProgress?: boolean;
  saveInProgress?: boolean;
  canDownload?: boolean;
  canDownloadGroup?: boolean;
  canSave?: boolean;
  demoLocked?: boolean;
  onDemoLockedAction?: () => void;
  demoFillLinkDocsHref?: string;
  demoCreateGroupDocsHref?: string;
};

function isSchemaPrerequisiteHint(reason: string | null | undefined): boolean {
  return reason === 'Connect a CSV, Excel, JSON, or TXT schema source first.' ||
    reason === 'Upload schema headers before mapping.' ||
    reason === 'Schema metadata is required before mapping.';
}

function truncateHeaderText(value: string, maxChars: number): string {
  const normalized = value.trim();
  if (normalized.length <= maxChars) return normalized;
  return `${normalized.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}

function formatGroupTemplateOptionLabel(
  template: { id: string; name: string },
  status: 'ready' | 'loading' | 'error' | undefined,
  options?: { maxNameChars?: number },
): string {
  const baseName = options?.maxNameChars
    ? truncateHeaderText(template.name, options.maxNameChars)
    : template.name;
  if (status === 'loading') {
    return `${baseName} (Preparing...)`;
  }
  if (status === 'error') {
    return `${baseName} (Reload needed)`;
  }
  return baseName;
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
  groupName = null,
  groupTemplates = [],
  groupTemplateStatuses = {},
  activeGroupTemplateId = null,
  groupTemplateSwitchInProgress = false,
  onSelectGroupTemplate,
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
  onRenameAndMapGroup,
  canRename = false,
  canRenameAndMap = false,
  canRenameAndMapGroup = false,
  renameDisabledReason = null,
  renameAndMapDisabledReason = null,
  renameAndMapGroupDisabledReason = null,
  renameAndMapGroupInProgress = false,
  renameAndMapGroupButtonLabel,
  onOpenSearchFill,
  canSearchFill = false,
  onOpenFillLink,
  canFillLink = false,
  onDownload,
  onDownloadGroup,
  onSaveToProfile,
  downloadInProgress = false,
  downloadGroupInProgress = false,
  saveInProgress = false,
  canDownload = false,
  canDownloadGroup = false,
  canSave = false,
  demoLocked = false,
  onDemoLockedAction,
  demoFillLinkDocsHref,
  demoCreateGroupDocsHref,
}: HeaderBarProps) {
  const hasMappingControls = Boolean(
    onChooseDataSource || onMapSchema || onRename || onRenameAndMap || onRenameAndMapGroup || onOpenSearchFill || onOpenFillLink,
  );
  const hasGroupContext = Boolean(groupName && groupTemplates.length > 0);
  const userInitial = userEmail ? userEmail.charAt(0).toUpperCase() : null;
  const mapSchemaLabel = mapSchemaInProgress ? 'Mapping' : hasMappedSchema ? 'Mapped' : 'Map Schema';
  const renameLabel = renameInProgress ? 'Renaming' : hasRenamedFields ? 'Renamed' : 'Rename';
  const renameAndMapLabel = mapSchemaInProgress ? 'Mapping' : 'Rename + Map';
  const renameAndMapGroupLabel =
    renameAndMapGroupButtonLabel ||
    (renameAndMapGroupInProgress ? 'Running group action…' : 'Rename + Map Group');
  const demoOverride = demoLocked && Boolean(onDemoLockedAction);
  const deferSchemaPrereqHint = isSchemaPrerequisiteHint(mapSchemaDisabledReason);
  const disableMapSchema = demoOverride
    ? false
    : mappingInProgress || mapSchemaInProgress || (!canMapSchema && !deferSchemaPrereqHint);
  const disableRename =
    demoOverride ? false : !canRename || mappingInProgress || renameInProgress || mapSchemaInProgress;
  const disableRenameAndMap =
    demoOverride ? false : !canRenameAndMap || mappingInProgress || renameInProgress || mapSchemaInProgress;
  const disableRenameAndMapGroup =
    demoOverride ? false : !canRenameAndMapGroup || mappingInProgress || renameInProgress || mapSchemaInProgress || renameAndMapGroupInProgress;
  const disableSearch = !canSearchFill || mappingInProgress;
  const disableFillLink = !canFillLink || mappingInProgress;
  const showDemoFillLinkDocs = demoLocked && Boolean(demoFillLinkDocsHref);
  const showDemoCreateGroupDocs = demoLocked && Boolean(demoCreateGroupDocsHref);
  const showSearchHint = !canSearchFill;
  const rawActionHint = demoOverride
    ? null
    : hasGroupContext && disableRenameAndMapGroup
      ? renameAndMapGroupDisabledReason
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
  const renameAndMapGroupTooltip = disableRenameAndMapGroup
    ? renameAndMapGroupDisabledReason || 'Rename + Map Group is unavailable right now.'
    : `Run Rename + Map for every saved form in ${groupName || 'this group'}`;
  const disableGroupSelect =
    groupTemplateSwitchInProgress || mappingInProgress || renameInProgress || mapSchemaInProgress || renameAndMapGroupInProgress;
  const disableDownload = demoOverride ? false : !canDownload || downloadInProgress;
  const disableDownloadGroup = demoOverride ? false : !canDownloadGroup || downloadGroupInProgress;
  const disableSave = demoOverride ? false : !canSave || saveInProgress;
  const activeGroupTemplate =
    groupTemplates.find((template) => template.id === activeGroupTemplateId) ||
    groupTemplates[0] ||
    null;
  const activeGroupTemplateFullLabel = activeGroupTemplate
    ? formatGroupTemplateOptionLabel(
      activeGroupTemplate,
      groupTemplateStatuses[activeGroupTemplate.id],
    )
    : 'Preparing...';
  const activeGroupTemplateDisplayLabel = activeGroupTemplate
    ? formatGroupTemplateOptionLabel(
      activeGroupTemplate,
      groupTemplateStatuses[activeGroupTemplate.id],
      { maxNameChars: HEADER_GROUP_TEMPLATE_TRIGGER_MAX_CHARS },
    )
    : 'Preparing...';

  const [showDataMenu, setShowDataMenu] = useState(false);
  const [showGroupMenu, setShowGroupMenu] = useState(false);
  const [zoomPercentInput, setZoomPercentInput] = useState(String(Math.round(scale * 100)));
  const isConnected = dataSourceKind !== 'none';
  const connectedKind =
    dataSourceKind === 'excel'
      ? 'XLS'
      : dataSourceKind === 'respondent'
        ? 'LINK'
      : dataSourceKind === 'txt'
        ? 'TXT'
        : dataSourceKind.toUpperCase();
  const dataSourceTitle = isConnected ? `Connected ${connectedKind}` : 'Schema';
  const dataSourceSubtitle = isConnected ? null : 'CSV/XLS/JSON/TXT';
  const dataSourceMenuRef = useRef<HTMLDivElement | null>(null);
  const groupMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      const clickedInsideDataSource = dataSourceMenuRef.current?.contains(target) ?? false;
      const clickedInsideGroupMenu = groupMenuRef.current?.contains(target) ?? false;
      if (!clickedInsideDataSource) {
        setShowDataMenu(false);
      }
      if (!clickedInsideGroupMenu) {
        setShowGroupMenu(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setShowDataMenu(false);
      setShowGroupMenu(false);
    };
    if (showDataMenu || showGroupMenu) {
      window.addEventListener('mousedown', handleClick);
      window.addEventListener('keydown', handleEscape);
    }
    return () => {
      window.removeEventListener('mousedown', handleClick);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [showDataMenu, showGroupMenu]);

  useEffect(() => {
    setShowGroupMenu(false);
  }, [activeGroupTemplateId]);

  useEffect(() => {
    setZoomPercentInput(String(Math.round(scale * 100)));
  }, [scale]);

  const commitZoomPercent = (rawValue: string) => {
    const trimmed = rawValue.trim();
    if (!trimmed) {
      setZoomPercentInput(String(Math.round(scale * 100)));
      return;
    }
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      setZoomPercentInput(String(Math.round(scale * 100)));
      return;
    }
    const clamped = Math.min(MAX_ZOOM_PERCENT, Math.max(MIN_ZOOM_PERCENT, Math.round(parsed)));
    setZoomPercentInput(String(clamped));
    onScaleChange(clamped / 100);
  };

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
        <div className="ui-chip ui-chip--page">
          <span className="ui-chip__single-value">
            {pageCount > 0 ? `Page ${currentPage}/${pageCount}` : 'Page --'}
          </span>
        </div>
        <div className="ui-chip ui-chip--slider">
          <span className="ui-chip__label">Zoom</span>
          <div className="ui-zoom-input-shell">
            <input
              className="ui-zoom-input"
              type="number"
              min={MIN_ZOOM_PERCENT}
              max={MAX_ZOOM_PERCENT}
              step={1}
              value={zoomPercentInput}
              id="header-zoom"
              name="header-zoom"
              inputMode="numeric"
              aria-label="Zoom percentage"
              onChange={(event) => setZoomPercentInput(event.target.value)}
              onBlur={(event) => commitZoomPercent(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.currentTarget.blur();
                  return;
                }
                if (event.key === 'Escape') {
                  setZoomPercentInput(String(Math.round(scale * 100)));
                  event.currentTarget.blur();
                }
              }}
            />
            <span className="ui-chip__value ui-chip__value--suffix">%</span>
          </div>
        </div>
        {hasGroupContext ? (
          <div
            ref={groupMenuRef}
            className={`ui-chip ui-chip--group-selector${showGroupMenu ? ' ui-chip--group-selector-open' : ''}`}
          >
            {disableGroupSelect ? (
              <div
                className="ui-group-select ui-group-select--disabled"
                aria-live="polite"
                title={activeGroupTemplateFullLabel}
              >
                {activeGroupTemplateDisplayLabel}
              </div>
            ) : (
              <>
                <button
                  type="button"
                  className="ui-group-select ui-group-select--trigger"
                  aria-label={groupName ? `Open template in ${groupName}` : 'Open group template'}
                  aria-haspopup="listbox"
                  aria-expanded={showGroupMenu}
                  title={activeGroupTemplateFullLabel}
                  onClick={() => {
                    setShowDataMenu(false);
                    setShowGroupMenu((previous) => !previous);
                  }}
                >
                  <span className="ui-group-select__value">{activeGroupTemplateDisplayLabel}</span>
                  <span className="ui-group-select__caret" aria-hidden="true">▾</span>
                </button>
                {showGroupMenu ? (
                  <div
                    className="ui-group-menu"
                    role="listbox"
                    aria-label={groupName ? `Templates in ${groupName}` : 'Group templates'}
                  >
                    {groupTemplates.map((template) => {
                      const status = groupTemplateStatuses[template.id];
                      const optionDisabled =
                        status === 'loading' && template.id !== activeGroupTemplateId;
                      const optionFullLabel = formatGroupTemplateOptionLabel(template, status);
                      const optionDisplayLabel = formatGroupTemplateOptionLabel(
                        template,
                        status,
                        { maxNameChars: HEADER_GROUP_TEMPLATE_MENU_MAX_CHARS },
                      );
                      const optionSelected = template.id === activeGroupTemplateId;
                      return (
                        <button
                          key={template.id}
                          type="button"
                          className={`ui-group-menu__item${optionSelected ? ' ui-group-menu__item--selected' : ''}`}
                          role="option"
                          aria-selected={optionSelected}
                          disabled={optionDisabled}
                          title={optionFullLabel}
                          onClick={() => {
                            setShowGroupMenu(false);
                            onSelectGroupTemplate?.(template.id);
                          }}
                        >
                          <span className="ui-group-menu__label">{optionDisplayLabel}</span>
                          {optionSelected ? (
                            <span className="ui-group-menu__status" aria-hidden="true">✓</span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : null}
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
              <div className="data-source" ref={dataSourceMenuRef}>
                <button
                  className="ui-button ui-button--ghost ui-button--compact data-source__button"
                  type="button"
                  data-demo-target="data-source"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    setShowGroupMenu(false);
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
              {!hasGroupContext && onRename ? (
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
              {!hasGroupContext ? (
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
              ) : null}
              {!hasGroupContext && onRenameAndMap ? (
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
              {hasGroupContext && onRenameAndMapGroup ? (
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    onRenameAndMapGroup?.();
                  }}
                  disabled={disableRenameAndMapGroup}
                  title={renameAndMapGroupTooltip}
                >
                  {renameAndMapGroupLabel}
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
                    <span className="ui-header__search-hint">Requires CSV/Excel/JSON/respondent rows</span>
                  ) : null}
                </div>
              ) : null}
              {showDemoFillLinkDocs ? (
                <a
                  className="ui-button ui-button--ghost ui-button--compact"
                  href={demoFillLinkDocsHref}
                >
                  See Link Filling docs
                </a>
              ) : null}
              {showDemoCreateGroupDocs ? (
                <a
                  className="ui-button ui-button--ghost ui-button--compact"
                  href={demoCreateGroupDocsHref}
                >
                  See Create Group docs
                </a>
              ) : null}
              {!showDemoFillLinkDocs && !showDemoCreateGroupDocs && onOpenFillLink ? (
                <button
                  className="ui-button ui-button--ghost ui-button--compact"
                  type="button"
                  onClick={() => {
                    if (demoOverride) {
                      onDemoLockedAction?.();
                      return;
                    }
                    onOpenFillLink();
                  }}
                  disabled={disableFillLink}
                  title={canFillLink ? 'Publish or manage a DullyPDF Fill By Link.' : 'Load a saved template to use Fill By Link.'}
                >
                  Fill By Link
                </button>
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
                    onDownload?.();
                  }}
                  disabled={disableDownload}
                >
                  {downloadInProgress ? 'Downloading...' : 'Download'}
                </button>
              ) : null}
              {onDownloadGroup ? (
                <button
                  className="ui-button ui-button--primary ui-button--compact ui-header__save"
                  type="button"
                  onClick={() => {
                    onDownloadGroup?.();
                  }}
                  disabled={disableDownloadGroup}
                >
                  {downloadGroupInProgress ? 'Downloading Group...' : 'Download Group'}
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
