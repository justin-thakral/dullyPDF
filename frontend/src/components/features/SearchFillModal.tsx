import { useCallback, useEffect, useMemo, useState } from 'react';
import type { PdfField } from '../../types';
import type { DataSourceKind } from '../layout/HeaderBar';
import './SearchFillModal.css';
import { DB } from '../../services/db';
import { normaliseDataKey } from '../../utils/dataSource';

type SearchMode = 'contains' | 'equals';

type SearchFillModalProps = {
  open: boolean;
  onClose: () => void;
  dataSourceKind: DataSourceKind;
  dataSourceLabel: string | null;
  connId: string | null;
  columns: string[];
  identifierKey: string | null;
  rows: Array<Record<string, unknown>>;
  fields: PdfField[];
  onFieldsChange: (next: PdfField[]) => void;
  onAfterFill: () => void;
  onError: (message: string) => void;
};

function coerceValue(value: unknown): string | number | boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value);
}

function parseDateFromUnknown(value: unknown): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === 'string') {
    const match = value.match(/\d{4}-\d{2}-\d{2}/);
    if (!match) return null;
    const parsed = new Date(`${match[0]}T00:00:00Z`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return null;
}

function formatDateValue(value: unknown): string | null {
  const parsed = parseDateFromUnknown(value);
  if (!parsed) return null;
  return parsed.toISOString().slice(0, 10);
}

function computeAgeYears(dob: Date, reference: Date): number {
  let age = reference.getUTCFullYear() - dob.getUTCFullYear();
  const monthDelta = reference.getUTCMonth() - dob.getUTCMonth();
  if (monthDelta < 0 || (monthDelta === 0 && reference.getUTCDate() < dob.getUTCDate())) {
    age -= 1;
  }
  return Math.max(0, age);
}

function rowPreview(row: Record<string, unknown>, identifierKey: string | null): { title: string; subtitle: string } {
  const get = (key: string) => {
    const foundKey = Object.keys(row).find((candidate) => candidate.toLowerCase() === key.toLowerCase());
    return foundKey ? row[foundKey] : undefined;
  };
  const mrn = identifierKey ? row[identifierKey] : get('mrn');
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

export default function SearchFillModal({
  open,
  onClose,
  dataSourceKind,
  dataSourceLabel,
  connId,
  columns,
  identifierKey,
  rows,
  fields,
  onFieldsChange,
  onAfterFill,
  onError,
}: SearchFillModalProps) {
  const [searchKey, setSearchKey] = useState<string>('');
  const [searchMode, setSearchMode] = useState<SearchMode>('contains');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Array<Record<string, unknown>>>([]);
  const [searching, setSearching] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const canSearchAnyColumn = dataSourceKind !== 'sql';
  const hasData = dataSourceKind === 'sql' ? Boolean(connId) : rows.length > 0;

  const availableKeys = useMemo(() => {
    const unique = new Set(columns.filter(Boolean));
    return Array.from(unique);
  }, [columns]);

  useEffect(() => {
    if (!open) return;
    const defaultKey = identifierKey || availableKeys[0] || '';
    setSearchKey(defaultKey);
    setQuery('');
    setResults([]);
    setSearching(false);
    setLocalError(null);
    setSearchMode('contains');
    setHasSearched(false);
  }, [availableKeys, identifierKey, open]);

  const runSearch = useCallback(async () => {
    if (!hasData) {
      setLocalError('Choose a SQL, CSV, or Excel source first.');
      return;
    }
    if (!query.trim()) {
      setLocalError('Enter a search value.');
      return;
    }
    if (!searchKey || (!canSearchAnyColumn && searchKey === '__any__')) {
      setLocalError('Choose a column to search.');
      return;
    }

    setLocalError(null);
    setHasSearched(true);
    setSearching(true);
    setResults([]);
    try {
      if (dataSourceKind === 'sql') {
        if (!connId) throw new Error('Missing SQL connection.');
        const matches = await DB.searchRows(connId, searchKey, query, { mode: searchMode, limit: 25 });
        setResults(matches);
        return;
      }

      const q = query.trim().toLowerCase();
      const matches = (value: string) => (searchMode === 'equals' ? value === q : value.includes(q));
      const matched: Array<Record<string, unknown>> = [];
      for (const row of rows) {
        if (searchKey === '__any__') {
          const keys = availableKeys.length ? availableKeys : Object.keys(row);
          const ok = keys.some((key) => matches(String(row[key] ?? '').toLowerCase()));
          if (!ok) continue;
        } else {
          const value = String(row[searchKey] ?? '').toLowerCase();
          if (!matches(value)) continue;
        }
        matched.push(row);
        if (matched.length >= 25) break;
      }
      setResults(matched);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Search failed.';
      setLocalError(message);
    } finally {
      setSearching(false);
    }
  }, [availableKeys, canSearchAnyColumn, connId, dataSourceKind, hasData, query, rows, searchKey, searchMode]);

  const handleFill = useCallback(
    async (row: Record<string, unknown>) => {
      setLocalError(null);

      const normalizedRow = new Map<string, unknown>();
      for (const [key, value] of Object.entries(row)) {
        normalizedRow.set(normaliseDataKey(key), value);
      }

      const resolveValueForField = (field: PdfField): unknown | undefined => {
        const normalizedName = normaliseDataKey(field.name);
        const direct = normalizedRow.get(normalizedName);
        if (direct !== undefined) return direct;

        const suffixMatch = normalizedName.match(/^(.*)_\d+$/);
        if (suffixMatch) {
          const base = suffixMatch[1];
          const baseValue = normalizedRow.get(base);
          if (baseValue !== undefined) return baseValue;
        }

        if (normalizedName === 'name') {
          const full = normalizedRow.get('full_name');
          if (full !== undefined) return full;
          const first = normalizedRow.get('first_name');
          const last = normalizedRow.get('last_name');
          if (first || last) {
            return [first, last].filter(Boolean).join(' ');
          }
        }

        if (normalizedName === 'age') {
          const dobValue = normalizedRow.get('dob') ?? normalizedRow.get('date_of_birth');
          const dob = parseDateFromUnknown(dobValue);
          if (!dob) return undefined;
          const refValue = normalizedRow.get('date') ?? normalizedRow.get('visit_date');
          const reference = parseDateFromUnknown(refValue) ?? new Date();
          return computeAgeYears(dob, reference);
        }

        return undefined;
      };

      const nextFields = fields.map((field) => {
        const matchValue = resolveValueForField(field);
        if (matchValue === undefined) return field;
        if (field.type === 'date') {
          const dateValue = formatDateValue(matchValue);
          if (dateValue === null) return field;
          return { ...field, value: dateValue };
        }
        return { ...field, value: coerceValue(matchValue) };
      });

      onFieldsChange(nextFields);
      try {
        onAfterFill();
        onClose();
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to fill PDF.';
        onError(message);
        setLocalError(message);
      }
    },
    [
      fields,
      onAfterFill,
      onClose,
      onError,
      onFieldsChange,
    ],
  );

  if (!open) return null;

  return (
    <div className="connectdb-modal" role="dialog" aria-modal="true">
      <div className="connectdb-backdrop" onClick={onClose} />
      <div className="connectdb-panel searchfill-panel">
        <div className="connectdb-header">
          <h3>Search &amp; Fill</h3>
          <button className="connectdb-close" onClick={onClose} type="button" aria-label="Close">
            ×
          </button>
        </div>
        <div className="connectdb-body searchfill-body">
          <div className="searchfill-meta">
            <div className="searchfill-source">
              <span className="searchfill-source__label">Source</span>
              <span className="searchfill-source__value">
                {dataSourceLabel || (dataSourceKind === 'none' ? 'None selected' : dataSourceKind.toUpperCase())}
              </span>
            </div>
            <div className="searchfill-source">
              <span className="searchfill-source__label">Records</span>
              <span className="searchfill-source__value">{dataSourceKind === 'sql' ? 'Live' : rows.length}</span>
            </div>
          </div>

          <div className="searchfill-controls">
            <div className="searchfill-field">
              <label className="searchfill-label" htmlFor="searchfill-key">
                Column
              </label>
              <select
                id="searchfill-key"
                value={searchKey}
                onChange={(event) => setSearchKey(event.target.value)}
                disabled={!hasData || searching}
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
                value={searchMode}
                onChange={(event) => setSearchMode(event.target.value as SearchMode)}
                disabled={!hasData || searching}
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
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="MRN, name, etc."
                disabled={!hasData || searching}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void runSearch();
                  }
                }}
              />
            </div>

            <button
              type="button"
              className="connectdb-button"
              onClick={() => void runSearch()}
              disabled={!hasData || searching}
            >
              {searching ? 'Searching…' : 'Search'}
            </button>
          </div>

          {localError ? <div className="connectdb-error">{localError}</div> : null}

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
              results.map((row, index) => {
                const preview = rowPreview(row, identifierKey);
                return (
                  <div key={index} className="searchfill-result">
                    <div className="searchfill-result__text">
                      <div className="searchfill-result__title">{preview.title}</div>
                      {preview.subtitle ? <div className="searchfill-result__subtitle">{preview.subtitle}</div> : null}
                    </div>
                    <button
                      type="button"
                      className="connectdb-button"
                      onClick={() => void handleFill(row)}
                      disabled={searching}
                    >
                      Fill PDF
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="connectdb-footer">
          <button className="connectdb-button-secondary" onClick={onClose} type="button">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
