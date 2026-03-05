/**
 * Side panel that lists fields and controls visibility/filtering.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import type { ConfidenceFilter, ConfidenceTier, FieldType, PdfField } from '../../types';
import {
  fieldConfidenceForField,
  fieldConfidenceTierForField,
  nameConfidenceForField,
  nameConfidenceTierForField,
  hasAnyConfidence,
} from '../../utils/confidence';
import { formatSize } from '../../utils/fields';
import { FIELD_TYPES, fieldTypeLabel } from '../../utils/fieldUi';

const MIN_PAGE = 1;

type SortMode = 'page' | 'name' | 'type' | 'confidence';
export type FieldListDisplayPreset = 'review' | 'edit' | 'fill' | 'custom';

type FieldListPanelProps = {
  fields: PdfField[];
  totalFieldCount: number;
  selectedFieldId: string | null;
  selectedField: PdfField | null;
  currentPage: number;
  pageCount: number;
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  displayPreset: FieldListDisplayPreset;
  onApplyDisplayPreset: (preset: Exclude<FieldListDisplayPreset, 'custom'>) => void;
  onShowFieldsChange: (enabled: boolean) => void;
  onShowFieldNamesChange: (enabled: boolean) => void;
  onShowFieldInfoChange: (enabled: boolean) => void;
  canClearInputs: boolean;
  onClearInputs: () => void;
  confidenceFilter: ConfidenceFilter;
  onConfidenceFilterChange: (tier: ConfidenceTier, enabled: boolean) => void;
  onResetConfidenceFilters: () => void;
  onSelectField: (fieldId: string) => void;
  onPageChange: (page: number) => void;
};

/**
 * Clamp requested page numbers into valid ranges.
 */
function clampPage(value: number, pageCount: number) {
  if (pageCount <= 0) return MIN_PAGE;
  return Math.min(Math.max(value, MIN_PAGE), pageCount);
}

/**
 * Return a sorted copy of fields according to the selected mode.
 */
function sortFields(items: PdfField[], mode: SortMode): PdfField[] {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (mode === 'name') {
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    }
    if (mode === 'type') {
      const byType = fieldTypeLabel(a.type).localeCompare(fieldTypeLabel(b.type), undefined, {
        sensitivity: 'base',
      });
      if (byType !== 0) return byType;
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    }
    if (mode === 'confidence') {
      const aConfidence = fieldConfidenceForField(a) ?? -1;
      const bConfidence = fieldConfidenceForField(b) ?? -1;
      if (aConfidence !== bConfidence) return bConfidence - aConfidence;
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    }

    if (a.page !== b.page) return a.page - b.page;
    if (a.rect.y !== b.rect.y) return a.rect.y - b.rect.y;
    if (a.rect.x !== b.rect.x) return a.rect.x - b.rect.x;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  });
  return sorted;
}

/**
 * Render the field list UI with filtering and selection.
 */
export function FieldListPanel({
  fields,
  totalFieldCount,
  selectedFieldId,
  selectedField,
  currentPage,
  pageCount,
  showFields,
  showFieldNames,
  showFieldInfo,
  displayPreset,
  onApplyDisplayPreset,
  onShowFieldsChange,
  onShowFieldNamesChange,
  onShowFieldInfoChange,
  canClearInputs,
  onClearInputs,
  confidenceFilter,
  onConfidenceFilterChange,
  onResetConfidenceFilters,
  onSelectField,
  onPageChange,
}: FieldListPanelProps) {
  const [query, setQuery] = useState('');
  const [filterType, setFilterType] = useState<FieldType | 'all'>('all');
  const [sortMode, setSortMode] = useState<SortMode>('page');
  const [showAllPages, setShowAllPages] = useState(false);
  const rowRefs = useRef(new Map<string, HTMLButtonElement | null>());

  const baseFields = useMemo(
    () => (showAllPages ? fields : fields.filter((field) => field.page === currentPage)),
    [currentPage, fields, showAllPages],
  );

  const filtered = useMemo(() => {
    const lowered = query.trim().toLowerCase();
    return baseFields.filter((field) => {
      if (filterType !== 'all' && field.type !== filterType) return false;
      if (!lowered) return true;
      return field.name.toLowerCase().includes(lowered);
    });
  }, [baseFields, filterType, query]);

  const sorted = useMemo(() => sortFields(filtered, sortMode), [filtered, sortMode]);

  const headerScopeCount = baseFields.length;
  const visibleCount = sorted.length;
  const emptyMessage =
    baseFields.length === 0
      ? showAllPages
        ? 'No fields detected yet.'
        : `No fields on page ${currentPage}.`
      : 'No fields match the current filter.';

  const inputValue = pageCount === 0 ? '' : String(currentPage);

  const selectedOutsideFilters = useMemo(() => {
    if (!selectedField) return null;
    if (sorted.some((field) => field.id === selectedField.id)) return null;
    return selectedField;
  }, [selectedField, sorted]);

  const confidenceChipLabel = useMemo(() => {
    const enabled = (['high', 'medium', 'low'] as const).filter((tier) => confidenceFilter[tier]);
    if (enabled.length === 3) return null;
    if (enabled.length === 0) return 'Confidence: none';
    return `Confidence: ${enabled.join(', ')}`;
  }, [confidenceFilter]);

  const hasActiveFilters =
    query.trim().length > 0 ||
    filterType !== 'all' ||
    sortMode !== 'page' ||
    showAllPages ||
    Boolean(confidenceChipLabel);

  useEffect(() => {
    if (!selectedFieldId) return;
    const node = rowRefs.current.get(selectedFieldId);
    if (!node) return;
    requestAnimationFrame(() => {
      node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }, [selectedFieldId, sorted]);

  const handlePageInput = (event: ChangeEvent<HTMLInputElement>) => {
    const raw = Number(event.target.value);
    if (Number.isNaN(raw)) return;
    onPageChange(clampPage(Math.round(raw), pageCount));
  };

  const handlePrev = () => onPageChange(clampPage(currentPage - 1, pageCount));
  const handleNext = () => onPageChange(clampPage(currentPage + 1, pageCount));

  const clearFilters = useCallback(() => {
    setQuery('');
    setFilterType('all');
    setSortMode('page');
    setShowAllPages(false);
    onResetConfidenceFilters();
  }, [onResetConfidenceFilters]);

  const handleRevealSelected = useCallback(() => {
    if (!selectedOutsideFilters) return;
    setQuery('');
    setFilterType('all');
    setSortMode('page');
    setShowAllPages(true);
    onResetConfidenceFilters();
    if (selectedOutsideFilters.page !== currentPage) {
      onPageChange(selectedOutsideFilters.page);
    }
    onSelectField(selectedOutsideFilters.id);
  }, [currentPage, onPageChange, onResetConfidenceFilters, onSelectField, selectedOutsideFilters]);

  const isNavDisabled = pageCount === 0;
  const canGoBack = currentPage > MIN_PAGE;
  const canGoForward = currentPage < pageCount;

  return (
    <aside className="panel panel--field-list">
      <div className="panel__header">
        <div>
          <h2>Fields</h2>
          <p className="panel__hint">Filter, sort, and jump to fields fast.</p>
        </div>
        <div className="panel__meta panel__meta--counts" title={`Visible ${visibleCount} of ${headerScopeCount} in scope; ${fields.length} of ${totalFieldCount} after confidence filter.`}>
          <span className="panel__meta-primary">{visibleCount} / {headerScopeCount}</span>
          <span className="panel__meta-secondary">of {totalFieldCount}</span>
        </div>
      </div>

      <div className="panel__body">
        <div className="panel__section panel__section--page">
          <label className="panel__label" htmlFor="page-input">
            Page
          </label>
          <div className="page-bar">
            <button
              className="page-bar__button"
              type="button"
              onClick={handlePrev}
              disabled={isNavDisabled || !canGoBack}
              aria-label="Previous page"
            >
              {'<'}
            </button>
            <div className="page-bar__input-wrap">
              <input
                id="page-input"
                name="page-input"
                className="page-bar__input"
                type="number"
                min={MIN_PAGE}
                max={pageCount || MIN_PAGE}
                inputMode="numeric"
                value={inputValue}
                onChange={handlePageInput}
                disabled={isNavDisabled}
              />
              <span className="page-bar__total">/ {pageCount || '--'}</span>
            </div>
            <button
              className="page-bar__button"
              type="button"
              onClick={handleNext}
              disabled={isNavDisabled || !canGoForward}
              aria-label="Next page"
            >
              {'>'}
            </button>
          </div>
        </div>

        <div className="panel__section panel__section--tight">
          <div>
            <span className="panel__label">Display mode</span>
            <div className="panel-display-modes" role="group" aria-label="Display mode presets">
              {([
                { key: 'review', label: 'Review' },
                { key: 'edit', label: 'Edit' },
                { key: 'fill', label: 'Fill' },
              ] as const).map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  className={`panel-mode-chip${displayPreset === preset.key ? ' panel-mode-chip--active' : ''}`}
                  onClick={() => onApplyDisplayPreset(preset.key)}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            {displayPreset === 'custom' ? (
              <p className="panel__micro">Custom mode active from manual visibility toggles.</p>
            ) : null}
          </div>

          <div className="panel__toggle-row" role="group" aria-label="Field display controls">
            <label
              className={`panel-pill-toggle${showFields ? ' panel-pill-toggle--active' : ''}`}
              title="Show field overlays on the PDF"
            >
              <input
                id="panel-toggle-fields"
                name="panel-toggle-fields"
                type="checkbox"
                checked={showFields}
                onChange={(event) => onShowFieldsChange(event.target.checked)}
              />
              <span>Fields</span>
            </label>
            <label
              className={`panel-pill-toggle${showFieldNames ? ' panel-pill-toggle--active' : ''}`}
              title="Show field names on the PDF overlay"
            >
              <input
                id="panel-toggle-names"
                name="panel-toggle-names"
                type="checkbox"
                checked={showFieldNames}
                onChange={(event) => onShowFieldNamesChange(event.target.checked)}
              />
              <span>Names</span>
            </label>
            <label
              className={`panel-pill-toggle${showAllPages ? ' panel-pill-toggle--active' : ''}`}
              title="Show fields from every page in the list"
            >
              <input
                id="panel-toggle-all"
                name="panel-toggle-all"
                type="checkbox"
                checked={showAllPages}
                onChange={(event) => setShowAllPages(event.target.checked)}
              />
              <span>All</span>
            </label>
            <label
              className={`panel-pill-toggle${showFieldInfo ? ' panel-pill-toggle--active' : ''}`}
              title="Fill values for fields (data entry mode)"
            >
              <input
                id="panel-toggle-info"
                name="panel-toggle-info"
                type="checkbox"
                checked={showFieldInfo}
                onChange={(event) => onShowFieldInfoChange(event.target.checked)}
              />
              <span>Info</span>
            </label>
            <button
              className="panel-pill-toggle panel-pill-toggle--action"
              type="button"
              onClick={onClearInputs}
              disabled={!canClearInputs}
              title="Clear all field inputs"
            >
              Clear
            </button>
          </div>

          <div>
            <span className="panel__label">Confidence</span>
            <div className="confidence-filter confidence-filter--compact" role="group" aria-label="Filter by confidence">
              {(['high', 'medium', 'low'] as const).map((tier) => (
                <label
                  key={tier}
                  className={`confidence-filter__option confidence-filter__option--${tier}`}
                >
                  <input
                    id={`confidence-filter-${tier}`}
                    name={`confidence-filter-${tier}`}
                    type="checkbox"
                    checked={confidenceFilter[tier]}
                    onChange={(event) => onConfidenceFilterChange(tier, event.target.checked)}
                  />
                  <span>{tier.charAt(0).toUpperCase() + tier.slice(1)}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="panel__controls">
            <div>
              <label className="panel__label" htmlFor="field-search">
                Search
              </label>
              <input
                id="field-search"
                name="field-search"
                className="panel__input"
                placeholder="Search by name"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div>
              <label className="panel__label" htmlFor="field-filter">
                Filter
              </label>
              <select
                id="field-filter"
                name="field-filter"
                className="panel__select"
                value={filterType}
                onChange={(event) => setFilterType(event.target.value as FieldType | 'all')}
              >
                <option value="all">All types</option>
                {FIELD_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {fieldTypeLabel(type)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="panel__label" htmlFor="field-sort">
                Sort
              </label>
              <select
                id="field-sort"
                name="field-sort"
                className="panel__select"
                value={sortMode}
                onChange={(event) => setSortMode(event.target.value as SortMode)}
              >
                <option value="page">Page order</option>
                <option value="name">Name</option>
                <option value="type">Type</option>
                <option value="confidence">Confidence</option>
              </select>
            </div>
          </div>

          {hasActiveFilters ? (
            <div className="panel-filter-summary">
              {query.trim().length > 0 ? <span className="panel-filter-chip">Search: {query.trim()}</span> : null}
              {filterType !== 'all' ? <span className="panel-filter-chip">Type: {fieldTypeLabel(filterType)}</span> : null}
              {showAllPages ? <span className="panel-filter-chip">Scope: all pages</span> : null}
              {sortMode !== 'page' ? <span className="panel-filter-chip">Sort: {sortMode}</span> : null}
              {confidenceChipLabel ? <span className="panel-filter-chip">{confidenceChipLabel}</span> : null}
              <button
                type="button"
                className="panel-filter-reset"
                onClick={clearFilters}
              >
                Reset filters
              </button>
            </div>
          ) : null}
        </div>

        <div className="panel__list">
          {selectedOutsideFilters ? (
            <div className="panel-selected-outside">
              <p className="panel-selected-outside__text">
                Selected field is outside the current filters.
              </p>
              <button
                type="button"
                className="panel-selected-outside__action"
                onClick={handleRevealSelected}
              >
                Reveal selected
              </button>
            </div>
          ) : null}

          <div className="field-list">
            {sorted.length === 0 ? (
              <p className="panel__empty">{emptyMessage}</p>
            ) : (
              sorted.map((field) => {
                const fieldConfidence = fieldConfidenceForField(field);
                const nameConfidence = nameConfidenceForField(field);
                const fieldTier = fieldConfidenceTierForField(field);
                const nameTier = nameConfidenceTierForField(field);
                const showConfidence = hasAnyConfidence(field);
                const fieldConfidenceText =
                  typeof fieldConfidence === 'number'
                    ? `${Math.round(fieldConfidence * 100)}% field`
                    : null;
                const nameLabel = typeof field.mappingConfidence === 'number' ? 'field remap' : 'name';
                const nameConfidenceText =
                  typeof nameConfidence === 'number'
                    ? `${Math.round(nameConfidence * 100)}% ${nameLabel}`
                    : null;
                const nameClassName =
                  nameTier && nameTier !== 'high' ? `field-row__name--conf-${nameTier}` : '';
                const rowClassName = [
                  'field-row',
                  field.id === selectedFieldId ? 'field-row--active' : '',
                  `field-row--conf-${fieldTier}`,
                ]
                  .filter(Boolean)
                  .join(' ');

                return (
                  <button
                    key={field.id}
                    className={rowClassName}
                    type="button"
                    ref={(node) => {
                      if (node) {
                        rowRefs.current.set(field.id, node);
                      } else {
                        rowRefs.current.delete(field.id);
                      }
                    }}
                    onClick={() => {
                      if (showAllPages && field.page !== currentPage) {
                        onPageChange(field.page);
                      }
                      onSelectField(field.id);
                    }}
                  >
                    <div className="field-row__main">
                      <span className={['field-row__name', nameClassName].filter(Boolean).join(' ')}>
                        {field.name}
                      </span>
                      <span className="field-row__meta">
                        <span className={`field-row__type field-row__type--${field.type}`}>
                          {fieldTypeLabel(field.type)}
                        </span>
                        <span className="field-row__page">Page {field.page}</span>
                        {showConfidence ? (
                          <span className="field-row__confidence-group">
                            {fieldConfidenceText ? (
                              <span className={`field-row__confidence field-row__confidence--${fieldTier}`}>
                                {fieldConfidenceText}
                              </span>
                            ) : null}
                            {nameConfidenceText ? (
                              <span
                                className={`field-row__confidence field-row__confidence--${
                                  nameTier || 'high'
                                }`}
                              >
                                {nameConfidenceText}
                              </span>
                            ) : null}
                          </span>
                        ) : null}
                      </span>
                    </div>
                    <span className="field-row__size">{formatSize(field.rect)}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
