/**
 * Field inspector panel for editing geometry and metadata.
 */
import type { FieldRect, FieldType, PdfField } from '../../types';
import { FIELD_TYPES, fieldTypeLabel } from '../../utils/fieldUi';

const MIN_FIELD_SIZE = 6;

type FieldInspectorPanelProps = {
  fields: PdfField[];
  selectedFieldId: string | null;
  currentPage: number;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onDeleteField: (fieldId: string) => void;
  onCreateField: (type: FieldType) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
};

/**
 * Render editable metadata and geometry controls for the selected field.
 */
export function FieldInspectorPanel({
  fields,
  selectedFieldId,
  currentPage,
  onUpdateField,
  onDeleteField,
  onCreateField,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}: FieldInspectorPanelProps) {
  const selected = fields.find((field) => field.id === selectedFieldId) || null;

  /**
   * Patch rect properties while keeping the rest of the geometry intact.
   */
  const updateRect = (fieldId: string, patch: Partial<FieldRect>) => {
    const field = fields.find((entry) => entry.id === fieldId);
    if (!field) return;
    onUpdateField(fieldId, {
      rect: { ...field.rect, ...patch },
    });
  };

  return (
    <aside className="panel panel--inspector">
      <div className="panel__header">
        <div>
          <h2>Inspector</h2>
          <p className="panel__hint">
            {selected ? `Editing ${selected.name}.` : 'Select a field to edit its details.'}
          </p>
        </div>
      </div>

      <div className="panel__body">
        <div className="panel__section">
          {!selected ? (
            <p className="panel__empty">No field selected.</p>
          ) : (
            <div className="inspector">
              <label className="panel__label" htmlFor="field-name">
                Name
              </label>
              <input
                id="field-name"
                className="panel__input"
                value={selected.name}
                onChange={(event) => onUpdateField(selected.id, { name: event.target.value })}
              />

              <div className="panel__row">
                <label className="panel__label" htmlFor="field-type">
                  Type
                </label>
                <select
                  id="field-type"
                  className="panel__select"
                  value={selected.type}
                  onChange={(event) => onUpdateField(selected.id, { type: event.target.value as FieldType })}
                >
                  {FIELD_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {fieldTypeLabel(type)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="panel__row">
                <label className="panel__label" htmlFor="field-page">
                  Page
                </label>
                <input
                  id="field-page"
                  className="panel__input"
                  type="number"
                  min={1}
                  value={selected.page}
                  onChange={(event) => onUpdateField(selected.id, { page: Number(event.target.value) || 1 })}
                />
              </div>

              <div className="panel__grid">
                <div>
                  <label className="panel__label" htmlFor="field-x">
                    X
                  </label>
                  <input
                    id="field-x"
                    className="panel__input"
                    type="number"
                    value={Math.round(selected.rect.x)}
                    onChange={(event) => updateRect(selected.id, { x: Number(event.target.value) || 0 })}
                  />
                </div>
                <div>
                  <label className="panel__label" htmlFor="field-y">
                    Y
                  </label>
                  <input
                    id="field-y"
                    className="panel__input"
                    type="number"
                    value={Math.round(selected.rect.y)}
                    onChange={(event) => updateRect(selected.id, { y: Number(event.target.value) || 0 })}
                  />
                </div>
                <div>
                  <label className="panel__label" htmlFor="field-width">
                    Width
                  </label>
                  <input
                    id="field-width"
                    className="panel__input"
                    type="number"
                    value={Math.round(selected.rect.width)}
                    onChange={(event) =>
                      updateRect(selected.id, { width: Math.max(MIN_FIELD_SIZE, Number(event.target.value) || 0) })
                    }
                  />
                </div>
                <div>
                  <label className="panel__label" htmlFor="field-height">
                    Height
                  </label>
                  <input
                    id="field-height"
                    className="panel__input"
                    type="number"
                    value={Math.round(selected.rect.height)}
                    onChange={(event) =>
                      updateRect(selected.id, { height: Math.max(MIN_FIELD_SIZE, Number(event.target.value) || 0) })
                    }
                  />
                </div>
              </div>

              <button
                className="ui-button ui-button--danger ui-button--compact"
                type="button"
                onClick={() => onDeleteField(selected.id)}
              >
                Delete field
              </button>
            </div>
          )}
        </div>

        <div className="panel__section panel__section--divider">
          <h3>Create field</h3>
          <div className="panel__action-grid">
            {FIELD_TYPES.map((type) => (
              <button
                key={type}
                className="ui-button ui-button--ghost ui-button--compact"
                type="button"
                onClick={() => onCreateField(type)}
              >
                Add {fieldTypeLabel(type)}
              </button>
            ))}
          </div>
          <p className="panel__micro">New fields are placed on page {currentPage}.</p>
        </div>

        <div className="panel__section panel__section--divider">
          <h3>Actions</h3>
          <div className="panel__action-grid">
            <button
              className="ui-button ui-button--ghost ui-button--compact"
              type="button"
              onClick={onUndo}
              disabled={!canUndo}
            >
              Undo
            </button>
            <button
              className="ui-button ui-button--ghost ui-button--compact"
              type="button"
              onClick={onRedo}
              disabled={!canRedo}
            >
              Redo
            </button>
          </div>
          <p className="panel__micro">Undo or redo the last 10 field edits.</p>
        </div>
      </div>
    </aside>
  );
}
