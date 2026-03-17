/**
 * Search & Fill modal for populating fields from data sources.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import type {
  DataSourceKind,
  PdfField,
} from '../../types';
import './SearchFillModal.css';
import type { CheckboxHint, CheckboxRule, TextTransformRule } from '../../types';
import { applySearchFillRowToFields } from '../../utils/searchFillApply';
import { Alert } from '../ui/Alert';
import { DialogFrame } from '../ui/Dialog';

type SearchMode = 'contains' | 'equals';

type PreparedSearchRow = {
  row: Record<string, unknown>;
  preview: {
    title: string;
    subtitle: string;
  };
  searchValueByKey: Map<string, string>;
  searchValues: string[];
  anySearchText: string;
};

type SearchFillModalProps = {
  open: boolean;
  onClose: () => void;
  sessionId?: number;
  dataSourceKind: DataSourceKind;
  dataSourceLabel: string | null;
  columns: string[];
  identifierKey: string | null;
  rows: Array<Record<string, unknown>>;
  fields: PdfField[];
  checkboxRules?: CheckboxRule[];
  checkboxHints?: CheckboxHint[];
  textTransformRules?: TextTransformRule[];
  onFieldsChange: (next: PdfField[]) => void;
  onClearFields: () => void;
  onAfterFill: () => void;
  onError: (message: string) => void;
  onRequestDataSource?: (kind: 'csv' | 'excel' | 'json') => void;
  searchPreset?: {
    query: string;
    searchKey?: string;
    searchMode?: SearchMode;
    autoRun?: boolean;
    autoFillOnSearch?: boolean;
    highlightResult?: boolean;
    token?: number;
  } | null;
  demoSearch?: {
    query: string;
    searchKey?: string;
    searchMode?: SearchMode;
    autoRun?: boolean;
    autoFillOnSearch?: boolean;
    highlightResult?: boolean;
    token?: number;
  } | null;
  demoInstruction?: ReactNode | null;
  fillTargets?: Array<{ id: string; name: string }>;
  activeFillTargetId?: string | null;
  onFillTargets?: (row: Record<string, unknown>, targetIds: string[]) => void | Promise<void>;
};

const VALIDATION_ERRORS = new Set([
  'Choose a CSV, Excel, JSON, or respondent source first.',
  'No record rows are available to search.',
  'Enter a search value.',
  'Choose a column to search.',
]);

function areStringArraysEqual(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}

/**
 * Build a concise preview label for search results.
 */
function rowPreview(
  row: Record<string, unknown>,
  lookup: Map<string, unknown>,
  identifierKey: string | null,
): { title: string; subtitle: string } {
  const get = (key: string) => lookup.get(key.toLowerCase());
  const mrn = identifierKey ? row[identifierKey] ?? get(identifierKey) : get('mrn');
  const fullName = get('full_name');
  const first = get('first_name');
  const last = get('last_name');
  const dob = get('dob') ?? get('date_of_birth');
  const titleParts = [];
  if (mrn) titleParts.push(String(mrn));
  if (fullName) titleParts.push(String(fullName));
  else if (first || last) titleParts.push([first, last].filter(Boolean).join(' '));
  const title = titleParts.join(' • ') || 'Record';
  const subtitleParts = [];
  if (dob) subtitleParts.push(`DOB ${String(dob)}`);
  const phone = get('phone') ?? get('mobile_phone') ?? get('home_phone');
  if (phone) subtitleParts.push(String(phone));
  const email = get('email') ?? get('email_address');
  if (email) subtitleParts.push(String(email));
  return { title, subtitle: subtitleParts.join(' • ') };
}

/**
 * Render the Search & Fill modal and apply data to fields.
 */
export default function SearchFillModal({
  open,
  onClose,
  sessionId,
  dataSourceKind,
  dataSourceLabel,
  columns,
  identifierKey,
  rows,
  fields,
  checkboxRules,
  checkboxHints,
  textTransformRules,
  onFieldsChange,
  onClearFields,
  onAfterFill,
  onError,
  onRequestDataSource,
  searchPreset,
  demoSearch,
  demoInstruction = null,
  fillTargets,
  activeFillTargetId = null,
  onFillTargets,
}: SearchFillModalProps) {
  const resolvedFillTargets = fillTargets ?? [];
  const resolvedSearchPreset = demoSearch ?? searchPreset ?? null;
  const [searchKey, setSearchKey] = useState<string>('');
  const [searchMode, setSearchMode] = useState<SearchMode>('contains');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PreparedSearchRow[]>([]);
  const [searching, setSearching] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedFillTargetIds, setSelectedFillTargetIds] = useState<string[]>([]);

  const canSearchAnyColumn = true;
  const hasRows = rows.length > 0;
  const hasSource = dataSourceKind !== 'none';
  const canRequestSource = Boolean(onRequestDataSource);
  const hasGroupFillTargets = resolvedFillTargets.length > 1;
  const dialogTitleId = useId();
  const dialogDescriptionId = useId();
  const availableKeys = useMemo(() => {
    const unique = new Set(columns.filter(Boolean));
    return Array.from(unique);
  }, [columns]);
  const preparedRows = useMemo<PreparedSearchRow[]>(() => {
    return rows.map((row) => {
      const rowKeys = availableKeys.length ? availableKeys : Object.keys(row);
      const searchValueByKey = new Map<string, string>();
      const lookup = new Map<string, unknown>();
      for (const [key, value] of Object.entries(row)) {
        const lowered = key.toLowerCase();
        if (!lookup.has(lowered)) {
          lookup.set(lowered, value);
        }
      }
      for (const key of rowKeys) {
        searchValueByKey.set(key, String(row[key] ?? '').toLowerCase());
      }
      const searchValues = rowKeys.map((key) => searchValueByKey.get(key) ?? '');
      return {
        row,
        preview: rowPreview(row, lookup, identifierKey),
        searchValueByKey,
        searchValues,
        anySearchText: searchValues.join('\n'),
      };
    });
  }, [availableKeys, identifierKey, rows]);
  const fillTargetSignature = useMemo(
    () => resolvedFillTargets.map((target) => `${target.id}:${target.name}`).join('|'),
    [resolvedFillTargets],
  );
  const fillTargetLookup = useMemo(
    () => new Map(resolvedFillTargets.map((target) => [target.id, target] as const)),
    [fillTargetSignature],
  );
  const fillTargetIdsKey = useMemo(
    () => resolvedFillTargets.map((target) => target.id).join('|'),
    [resolvedFillTargets],
  );
  const autoRunSignature = useMemo(() => {
    if (!resolvedSearchPreset?.autoRun) return null;
    const defaultKey = identifierKey || availableKeys[0] || '';
    const presetKey = resolvedSearchPreset.searchKey ?? defaultKey;
    const presetMode = resolvedSearchPreset.searchMode ?? 'contains';
    const presetQuery = resolvedSearchPreset.query ?? '';
    if (!presetQuery) return null;
    return JSON.stringify({
      sessionId,
      token: resolvedSearchPreset.token ?? null,
      searchKey: presetKey,
      searchMode: presetMode,
      query: presetQuery,
    });
  }, [
    availableKeys,
    identifierKey,
    resolvedSearchPreset?.autoRun,
    resolvedSearchPreset?.query,
    resolvedSearchPreset?.searchKey,
    resolvedSearchPreset?.searchMode,
    resolvedSearchPreset?.token,
    sessionId,
  ]);
  const lastAutoRunSignatureRef = useRef<string | null>(null);

  const clearValidationError = useCallback(() => {
    if (!localError) return;
    if (!VALIDATION_ERRORS.has(localError)) return;
    setLocalError(null);
  }, [localError]);

  const sourceStateRef = useRef({ hasRows, hasSource });
  useEffect(() => {
    const prev = sourceStateRef.current;
    sourceStateRef.current = { hasRows, hasSource };
    if (!localError) return;
    if (!VALIDATION_ERRORS.has(localError)) return;
    if (prev.hasRows !== hasRows || prev.hasSource !== hasSource) {
      setLocalError(null);
    }
  }, [hasRows, hasSource, localError]);

  /**
   * Apply a selected row to all fields, including checkbox rules.
   */
  const handleFill = useCallback(
    async (row: Record<string, unknown>) => {
      setLocalError(null);
      try {
        if (hasGroupFillTargets && onFillTargets) {
          const targetIds = selectedFillTargetIds.filter((targetId) => fillTargetLookup.has(targetId));
          if (targetIds.length === 0) {
            setLocalError('Select at least one PDF target before filling.');
            return;
          }
          await onFillTargets(row, targetIds);
        } else {
          const nextFields = applySearchFillRowToFields({
            row,
            fields,
            checkboxRules,
            checkboxHints,
            textTransformRules,
            dataSourceKind,
          });
          onFieldsChange(nextFields);
        }
        onAfterFill();
        onClose();
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to fill PDF.';
        onError(message);
        setLocalError(message);
      }
    },
    [
      checkboxHints,
      checkboxRules,
      fields,
      onAfterFill,
      onClose,
      onError,
      onFieldsChange,
      onFillTargets,
      fillTargetLookup,
      hasGroupFillTargets,
      dataSourceKind,
      selectedFillTargetIds,
      textTransformRules,
    ],
  );

  /**
   * Execute a search against local rows.
   */
  const executeSearch = useCallback(
    async ({
      queryValue,
      searchKeyValue,
      searchModeValue,
    }: {
      queryValue: string;
      searchKeyValue: string;
      searchModeValue: SearchMode;
    }) => {
      const failValidation = (message: string) => {
        setLocalError(message);
        setResults([]);
        setHasSearched(false);
      };
      if (!hasSource) {
        failValidation('Choose a CSV, Excel, JSON, or respondent source first.');
        return;
      }
      if (!hasRows) {
        failValidation('No record rows are available to search.');
        return;
      }
      if (!queryValue) {
        failValidation('Enter a search value.');
        return;
      }
      if (!searchKeyValue || (!canSearchAnyColumn && searchKeyValue === '__any__')) {
        failValidation('Choose a column to search.');
        return;
      }

      setLocalError(null);
      setHasSearched(true);
      setSearching(true);
      setResults([]);
      try {
        const q = queryValue.toLowerCase();
        const matches = (value: string) => (searchModeValue === 'equals' ? value === q : value.includes(q));
        const matched: PreparedSearchRow[] = [];
        for (const preparedRow of preparedRows) {
          if (searchKeyValue === '__any__') {
            const ok = searchModeValue === 'equals'
              ? preparedRow.searchValues.some((value) => matches(value))
              : matches(preparedRow.anySearchText);
            if (!ok) continue;
          } else {
            const value = preparedRow.searchValueByKey.get(searchKeyValue)
              ?? String(preparedRow.row[searchKeyValue] ?? '').toLowerCase();
            if (!matches(value)) continue;
          }
          matched.push(preparedRow);
          if (matched.length >= 25) break;
        }
        if (resolvedSearchPreset?.autoFillOnSearch && matched.length > 0) {
          await handleFill(matched[0].row);
          return;
        }
        setResults(matched);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Search failed.';
        setLocalError(message);
      } finally {
        setSearching(false);
      }
    },
    [canSearchAnyColumn, handleFill, hasRows, hasSource, preparedRows, resolvedSearchPreset?.autoFillOnSearch],
  );

  const runSearch = useCallback(
    async (override?: { query?: string; searchKey?: string; searchMode?: SearchMode }) => {
      const queryValue = (override?.query ?? query).trim();
      const searchKeyValue = override?.searchKey ?? searchKey;
      const searchModeValue = override?.searchMode ?? searchMode;
      await executeSearch({ queryValue, searchKeyValue, searchModeValue });
    },
    [executeSearch, query, searchKey, searchMode],
  );

  useEffect(() => {
    if (!open) return;
    const defaultKey = identifierKey || availableKeys[0] || '';
    const presetKey = resolvedSearchPreset?.searchKey ?? defaultKey;
    const presetMode = resolvedSearchPreset?.searchMode ?? 'contains';
    const presetQuery = resolvedSearchPreset?.query ?? '';
    setSearchKey(presetKey);
    setQuery(presetQuery);
    setResults([]);
    setSearching(false);
    setLocalError(null);
    setSearchMode(presetMode);
    setHasSearched(false);
    const defaultTargetId = activeFillTargetId && fillTargetLookup.has(activeFillTargetId)
      ? activeFillTargetId
      : resolvedFillTargets[0]?.id;
    const nextTargetIds = defaultTargetId ? [defaultTargetId] : [];
    setSelectedFillTargetIds((prev) => (areStringArraysEqual(prev, nextTargetIds) ? prev : nextTargetIds));
  }, [
    availableKeys,
    identifierKey,
    open,
    resolvedSearchPreset?.query,
    resolvedSearchPreset?.searchKey,
    resolvedSearchPreset?.searchMode,
    sessionId,
    activeFillTargetId,
    fillTargetIdsKey,
    fillTargetLookup,
  ]);

  useEffect(() => {
    if (!open) {
      lastAutoRunSignatureRef.current = null;
      return;
    }
    if (!resolvedSearchPreset?.autoRun || !autoRunSignature) return;
    if (lastAutoRunSignatureRef.current === autoRunSignature) return;
    lastAutoRunSignatureRef.current = autoRunSignature;
    const defaultKey = identifierKey || availableKeys[0] || '';
    const presetKey = resolvedSearchPreset.searchKey ?? defaultKey;
    const presetMode = resolvedSearchPreset.searchMode ?? 'contains';
    const presetQuery = resolvedSearchPreset.query ?? '';
    void executeSearch({
      queryValue: presetQuery.trim(),
      searchKeyValue: presetKey,
      searchModeValue: presetMode,
    });
  }, [
    autoRunSignature,
    availableKeys,
    executeSearch,
    identifierKey,
    open,
    resolvedSearchPreset?.autoRun,
    resolvedSearchPreset?.query,
    resolvedSearchPreset?.searchKey,
    resolvedSearchPreset?.searchMode,
  ]);

  const toggleFillTarget = useCallback((targetId: string, checked: boolean) => {
    setSelectedFillTargetIds((prev) => {
      if (checked) {
        if (prev.includes(targetId)) return prev;
        return [...prev, targetId];
      }
      if (prev.length <= 1) return prev;
      return prev.filter((value) => value !== targetId);
    });
  }, []);

  const handleSelectCurrentTarget = useCallback(() => {
    const targetId = activeFillTargetId && fillTargetLookup.has(activeFillTargetId)
      ? activeFillTargetId
      : resolvedFillTargets[0]?.id;
    if (!targetId) return;
    setSelectedFillTargetIds([targetId]);
  }, [activeFillTargetId, fillTargetLookup, resolvedFillTargets]);

  const handleSelectAllTargets = useCallback(() => {
    setSelectedFillTargetIds(resolvedFillTargets.map((target) => target.id));
  }, [resolvedFillTargets]);

  const canClearFields = useMemo(
    () =>
      fields.some((field) => {
        const value = field.value;
        if (value === null || value === undefined) return false;
        if (typeof value === 'string') return value.trim().length > 0;
        if (typeof value === 'boolean') return value;
        return true;
      }),
    [fields],
  );

  const handleClear = useCallback(() => {
    onClearFields();
    setLocalError(null);
  }, [onClearFields]);

  if (!open) return null;

  return (
    <DialogFrame
      open={open}
      onClose={onClose}
      className="searchfill-modal__card"
      labelledBy={dialogTitleId}
      describedBy={dialogDescriptionId}
    >
      <div className="searchfill-modal__header">
        <div>
          <h2 className="searchfill-modal__title" id={dialogTitleId}>Search, Fill &amp; Clear</h2>
          <p className="searchfill-modal__subtitle" id={dialogDescriptionId}>
            {hasGroupFillTargets
              ? 'Find a record locally and populate the selected PDFs in this group.'
              : 'Find a record locally and populate the current PDF.'}
          </p>
        </div>
        <button
          className="searchfill-modal__close"
          onClick={onClose}
          type="button"
          aria-label="Close"
        >
          ×
        </button>
      </div>
      <div className="searchfill-modal__body">
        {demoInstruction ? (
          <div className="searchfill-demo-note" role="note" aria-label="Demo instruction">
            <p className="searchfill-demo-note__eyebrow">Demo</p>
            <div className="searchfill-demo-note__body">{demoInstruction}</div>
          </div>
        ) : null}

        <div className="searchfill-meta">
          <div className="searchfill-source">
            <span className="searchfill-source__label">Source</span>
            <span className="searchfill-source__value">
              {dataSourceLabel || (dataSourceKind === 'none' ? 'None selected' : dataSourceKind.toUpperCase())}
            </span>
          </div>
          <div className="searchfill-source">
            <span className="searchfill-source__label">Records</span>
            <span className="searchfill-source__value">{rows.length}</span>
          </div>
        </div>

        {hasGroupFillTargets ? (
          <section className="searchfill-targets" aria-label="Fill targets">
            <div className="searchfill-targets__header">
              <div>
                <p className="searchfill-targets__eyebrow">Fill targets</p>
                <h3>Select which PDFs receive the row</h3>
              </div>
              <div className="searchfill-actions">
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={handleSelectCurrentTarget}
                  disabled={searching}
                >
                  Current PDF
                </button>
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={handleSelectAllTargets}
                  disabled={searching}
                >
                  All PDFs
                </button>
              </div>
            </div>
            <div className="searchfill-targets__list">
              {resolvedFillTargets.map((target) => {
                const checked = selectedFillTargetIds.includes(target.id);
                const isCurrent = target.id === activeFillTargetId;
                return (
                  <label key={target.id} className="searchfill-targets__item">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) => toggleFillTarget(target.id, event.target.checked)}
                      disabled={searching || (checked && selectedFillTargetIds.length === 1)}
                    />
                    <span className="searchfill-targets__name">
                      {target.name}
                      {isCurrent ? <em>Current</em> : null}
                    </span>
                  </label>
                );
              })}
            </div>
            <p className="searchfill-targets__summary">
              {selectedFillTargetIds.length} PDF{selectedFillTargetIds.length === 1 ? '' : 's'} selected
            </p>
          </section>
        ) : null}

        {!hasRows ? (
          <div className="searchfill-alert searchfill-alert--empty">
            <Alert
              tone="info"
              variant="inline"
              size="sm"
              message={
                hasSource
                  ? 'The connected source has no record rows to search.'
                  : 'No record rows are loaded yet. Upload a CSV, Excel, or JSON file to search and fill.'
              }
            />
            {canRequestSource ? (
              <div className="searchfill-actions searchfill-actions--empty">
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={() => onRequestDataSource?.('csv')}
                >
                  Upload CSV
                </button>
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={() => onRequestDataSource?.('excel')}
                >
                  Upload Excel
                </button>
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--compact"
                  onClick={() => onRequestDataSource?.('json')}
                >
                  Upload JSON
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

          <div className="searchfill-controls">
            <div className="searchfill-field">
              <label className="searchfill-label" htmlFor="searchfill-key">
                Column
              </label>
              <select
                id="searchfill-key"
                name="searchfill-key"
                value={searchKey}
                onChange={(event) => {
                  setSearchKey(event.target.value);
                  clearValidationError();
                }}
                disabled={!hasRows || searching}
              >
                {canSearchAnyColumn ? (
                  <option value="__any__">Any column</option>
                ) : null}
                {availableKeys.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>

            <div className="searchfill-field">
              <label className="searchfill-label" htmlFor="searchfill-mode">
                Match
              </label>
              <select
                id="searchfill-mode"
                name="searchfill-mode"
                value={searchMode}
                onChange={(event) => {
                  setSearchMode(event.target.value as SearchMode);
                  clearValidationError();
                }}
                disabled={!hasRows || searching}
              >
                <option value="contains">Contains</option>
                <option value="equals">Equals</option>
              </select>
            </div>

            <div className="searchfill-field searchfill-field--grow">
              <label className="searchfill-label" htmlFor="searchfill-query">
                Search
              </label>
              <input
                id="searchfill-query"
                name="searchfill-query"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  clearValidationError();
                }}
                placeholder="MRN, name, etc."
                disabled={!hasRows || searching}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void runSearch();
                  }
                }}
              />
            </div>

            <div className="searchfill-actions">
              <button
                type="button"
                className="ui-button ui-button--primary ui-button--compact"
                data-demo-target={demoSearch?.autoFillOnSearch ? 'search-fill-search' : undefined}
                onClick={() => void runSearch()}
                disabled={!hasRows || searching}
              >
                {searching ? 'Searching…' : 'Search'}
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={handleClear}
                disabled={!canClearFields || searching}
              >
                Clear inputs
              </button>
            </div>
          </div>

          {localError ? (
            <div className="searchfill-alert">
              <Alert tone="error" variant="inline" size="sm" message={localError} />
            </div>
          ) : null}

          <div className="searchfill-results" aria-label="Search results">
            {results.length === 0 ? (
              <div
                className={[
                  'searchfill-results__empty',
                  hasSearched && !searching && !localError ? 'searchfill-results__empty--not-found' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                {hasSearched && !searching && !localError ? '(search) not found' : 'No results yet.'}
              </div>
            ) : (
              results.map((result, index) => {
                const demoTargetProps =
                  demoSearch?.highlightResult && index === 0
                    ? { 'data-demo-target': 'search-fill-result' }
                    : {};
                return (
                  <div key={index} className="searchfill-result">
                    <div className="searchfill-result__text">
                      <div className="searchfill-result__title">{result.preview.title}</div>
                      {result.preview.subtitle ? <div className="searchfill-result__subtitle">{result.preview.subtitle}</div> : null}
                    </div>
                    <button
                      type="button"
                      className="ui-button ui-button--primary ui-button--compact"
                      {...demoTargetProps}
                      onClick={() => void handleFill(result.row)}
                      disabled={searching}
                    >
                      {hasGroupFillTargets ? 'Fill selected PDFs' : 'Fill PDF'}
                    </button>
                  </div>
                );
              })
            )}
          </div>
      </div>
      <div className="searchfill-modal__footer">
        <button className="ui-button ui-button--ghost" onClick={onClose} type="button">
          Close
        </button>
      </div>
    </DialogFrame>
  );
}
