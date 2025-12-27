import { useMemo, useState, type ChangeEvent } from 'react';
import type { FieldType, PdfField } from '../../types';
import { formatSize } from '../../utils/fields';
import { FIELD_TYPES, fieldTypeLabel } from '../../utils/fieldUi';

const MIN_PAGE = 1;

type FieldListPanelProps = {
  fields: PdfField[];
  selectedFieldId: string | null;
  currentPage: number;
  pageCount: number;
  onSelectField: (fieldId: string) => void;
  onPageChange: (page: number) => void;
};

function clampPage(value: number, pageCount: number) {
  if (pageCount <= 0) return MIN_PAGE;
  return Math.min(Math.max(value, MIN_PAGE), pageCount);
}

export function FieldListPanel({
  fields,
  selectedFieldId,
  currentPage,
  pageCount,
  onSelectField,
  onPageChange,
}: FieldListPanelProps) {
  const [query, setQuery] = useState('');
  const [filterType, setFilterType] = useState<FieldType | 'all'>('all');
  const [showAllPages, setShowAllPages] = useState(false);

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
          <div className="panel__row panel__row--space">
            <label className="panel__toggle">
              <input
                className="panel__toggle-input"
                type="checkbox"
                checked={showAllPages}
                onChange={(event) => setShowAllPages(event.target.checked)}
              />
              <span className="panel__toggle-track" aria-hidden="true" />
              <span className="panel__toggle-text">Show all pages</span>
            </label>
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
              filtered.map((field) => (
                <button
                  key={field.id}
                  className={field.id === selectedFieldId ? 'field-row field-row--active' : 'field-row'}
                  type="button"
                  onClick={() => onSelectField(field.id)}
                >
                  <div className="field-row__main">
                    <span className="field-row__name">{field.name}</span>
                    <span className="field-row__meta">
                      <span className={`field-row__type field-row__type--${field.type}`}>
                        {fieldTypeLabel(field.type)}
                      </span>
                      <span className="field-row__page">Page {field.page}</span>
                    </span>
                  </div>
                  <span className="field-row__size">{formatSize(field.rect)}</span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
