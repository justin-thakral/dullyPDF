/**
 * Field inspector panel for editing geometry and metadata.
 */
import type { FieldRect, FieldType, PdfField } from '../../types';
import { getMinFieldSize } from '../../utils/fields';
import { FIELD_TYPES, fieldTypeLabel } from '../../utils/fieldUi';

type FieldInspectorPanelProps = {
  fields: PdfField[];
  selectedFieldId: string | null;
  activeCreateTool: FieldType | null;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onSetFieldType: (fieldId: string, type: FieldType) => void;
  onUpdateFieldDraft: (fieldId: string, updates: Partial<PdfField>) => void;
  onDeleteField: (fieldId: string) => void;
  onCreateToolChange: (type: FieldType | null) => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onBeginFieldChange: () => void;
  onCommitFieldChange: () => void;
};

/**
 * Render editable metadata and geometry controls for the selected field.
 */
export function FieldInspectorPanel({
  fields,
  selectedFieldId,
  activeCreateTool,
  onUpdateField,
  onSetFieldType,
  onUpdateFieldDraft,
  onDeleteField,
  onCreateToolChange,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onBeginFieldChange,
  onCommitFieldChange,
}: FieldInspectorPanelProps) {
  const selected = fields.find((field) => field.id === selectedFieldId) || null;
  const selectedMinSize = selected ? getMinFieldSize(selected.type) : getMinFieldSize('text');

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
                name="field-name"
                className="panel__input"
                value={selected.name}
                onFocus={onBeginFieldChange}
                onBlur={onCommitFieldChange}
                onChange={(event) => onUpdateFieldDraft(selected.id, { name: event.target.value })}
              />

              <div className="panel__row">
                <label className="panel__label" htmlFor="field-type">
                  Type
                </label>
                <select
                  id="field-type"
                  name="field-type"
                  className="panel__select"
                  value={selected.type}
                  onChange={(event) => onSetFieldType(selected.id, event.target.value as FieldType)}
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
                  name="field-page"
                  className="panel__input"
                  type="number"
                  min={1}
                  value={selected.page}
                  onWheel={(event) => event.currentTarget.blur()}
                  onChange={(event) => onUpdateField(selected.id, { page: Math.max(1, Math.round(Number(event.target.value) || 1)) })}
                />
              </div>

              <div className="panel__grid">
                <div>
                  <label className="panel__label" htmlFor="field-x">
                    X
                  </label>
                  <input
                    id="field-x"
                    name="field-x"
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
                    name="field-y"
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
                    name="field-width"
                    className="panel__input"
                    type="number"
                    value={Math.round(selected.rect.width)}
                    onChange={(event) =>
                      updateRect(selected.id, { width: Math.max(selectedMinSize, Number(event.target.value) || 0) })
                    }
                  />
                </div>
                <div>
                  <label className="panel__label" htmlFor="field-height">
                    Height
                  </label>
                  <input
                    id="field-height"
                    name="field-height"
                    className="panel__input"
                    type="number"
                    value={Math.round(selected.rect.height)}
                    onChange={(event) =>
                      updateRect(selected.id, { height: Math.max(selectedMinSize, Number(event.target.value) || 0) })
                    }
                  />
                </div>
              </div>

              <button
                className="ui-button ui-button--danger ui-button--compact"
                type="button"
                onClick={() => onDeleteField(selected.id)}
                title="Delete selected field (Delete/Backspace)"
              >
                Delete field
              </button>
            </div>
          )}
        </div>

        <div className="panel__section panel__section--divider">
          <h3>Create field</h3>
          <label className="panel__label">Create tool</label>
          <div className="panel-display-modes" role="group" aria-label="Create tool">
            {FIELD_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                className={`panel-mode-chip${activeCreateTool === type ? ' panel-mode-chip--active' : ''}`}
                onClick={() => onCreateToolChange(activeCreateTool === type ? null : type)}
              >
                {fieldTypeLabel(type)}
              </button>
            ))}
            <button
              type="button"
              className={`panel-mode-chip${activeCreateTool === null ? ' panel-mode-chip--active' : ''}`}
              onClick={() => onCreateToolChange(null)}
            >
              Off
            </button>
          </div>
          <p className="panel__micro">
            Draw fields on the page while a tool is active. Press Esc to exit the active tool.
          </p>
          <label className="panel__label">History</label>
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

        <div className="panel__section panel__section--divider">
          <h3>Shortcuts</h3>
          <p className="panel__micro">
            Shortcuts: T/D/S/C set create tool, Esc clears active create tool,
            Delete/Backspace delete selected, Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y redo, Ctrl/Cmd+F or /
            focus search, [ and ] change pages, Alt+Arrow nudge (Shift+Alt for 10), and hold Shift during corner-resize
            to lock aspect ratio.
          </p>
        </div>
      </div>
    </aside>
  );
}
