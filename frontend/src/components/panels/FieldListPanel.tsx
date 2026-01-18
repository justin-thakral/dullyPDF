/**
 * Side panel that lists fields and controls visibility/filtering.
 */
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
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

type FieldListPanelProps = {
  fields: PdfField[];
  selectedFieldId: string | null;
  currentPage: number;
  pageCount: number;
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  onShowFieldsChange: (enabled: boolean) => void;
  onShowFieldNamesChange: (enabled: boolean) => void;
  onShowFieldInfoChange: (enabled: boolean) => void;
  canClearInputs: boolean;
  onClearInputs: () => void;
  confidenceFilter: ConfidenceFilter;
  onConfidenceFilterChange: (tier: ConfidenceTier, enabled: boolean) => void;
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
 * Render the field list UI with filtering and selection.
 */
export function FieldListPanel({
  fields,
  selectedFieldId,
  currentPage,
  pageCount,
  showFields,
  showFieldNames,
  showFieldInfo,
  onShowFieldsChange,
  onShowFieldNamesChange,
  onShowFieldInfoChange,
  canClearInputs,
  onClearInputs,
  confidenceFilter,
  onConfidenceFilterChange,
  onSelectField,
  onPageChange,
}: FieldListPanelProps) {
  const [query, setQuery] = useState('');
  const [filterType, setFilterType] = useState<FieldType | 'all'>('all');
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

  const headerCount = showAllPages ? fields.length : baseFields.length;
  const emptyMessage =
    baseFields.length === 0
      ? showAllPages
        ? 'No fields detected yet.'
        : `No fields on page ${currentPage}.`
      : 'No fields match the current filter.';

  const inputValue = pageCount === 0 ? '' : String(currentPage);

  useEffect(() => {
    if (!selectedFieldId) return;
    const node = rowRefs.current.get(selectedFieldId);
    if (!node) return;
    requestAnimationFrame(() => {
      node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }, [filtered, selectedFieldId]);

  const handlePageInput = (event: ChangeEvent<HTMLInputElement>) => {
    const raw = Number(event.target.value);
    if (Number.isNaN(raw)) return;
    onPageChange(clampPage(raw, pageCount));
  };

  const handlePrev = () => onPageChange(clampPage(currentPage - 1, pageCount));
  const handleNext = () => onPageChange(clampPage(currentPage + 1, pageCount));

  const isNavDisabled = pageCount === 0;
  const canGoBack = currentPage > MIN_PAGE;
  const canGoForward = currentPage < pageCount;

  return (
    <aside className="panel panel--field-list">
      <div className="panel__header">
        <div>
          <h2>Fields</h2>
          <p className="panel__hint">Filter and select fields.</p>
        </div>
        <div className="panel__meta">{headerCount}</div>
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
          <div className="panel__toggle-row" role="group" aria-label="Field display controls">
            <label
              className={`panel-pill-toggle${showFields ? ' panel-pill-toggle--active' : ''}`}
              title="Show field overlays on the PDF"
            >
              <input
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
          </div>
        </div>

        <div className="panel__list">
          <div className="field-list">
            {filtered.length === 0 ? (
              <p className="panel__empty">{emptyMessage}</p>
            ) : (
              filtered.map((field) => {
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
