/**
 * Field inspector panel for editing geometry and metadata.
 */
import { useEffect, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import type { FieldRect, FieldType, PdfField } from '../../types';
import { getMinFieldSize } from '../../utils/fields';
import {
  MAX_ARROW_KEY_MOVE_STEP,
  MIN_ARROW_KEY_MOVE_STEP,
  sanitizeArrowKeyMoveStep,
} from '../../utils/fieldMovement';
import { FIELD_TYPES, fieldTypeLabel } from '../../utils/fieldUi';

type InspectorDraft = {
  name: string;
  page: string;
  x: string;
  y: string;
  width: string;
  height: string;
};

type FieldInspectorPanelProps = {
  fields: PdfField[];
  selectedFieldId: string | null;
  selectedField?: PdfField | null;
  activeCreateTool: FieldType | null;
  arrowKeyMoveEnabled: boolean;
  arrowKeyMoveStep: number;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onSetFieldType: (fieldId: string, type: FieldType) => void;
  onUpdateFieldDraft: (fieldId: string, updates: Partial<PdfField>) => void;
  onDeleteField: (fieldId: string) => void;
  onCreateToolChange: (type: FieldType | null) => void;
  onArrowKeyMoveEnabledChange: (enabled: boolean) => void;
  onArrowKeyMoveStepChange: (step: number) => void;
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
  selectedField,
  activeCreateTool,
  arrowKeyMoveEnabled,
  arrowKeyMoveStep,
  onUpdateField,
  onSetFieldType,
  onDeleteField,
  onCreateToolChange,
  onArrowKeyMoveEnabledChange,
  onArrowKeyMoveStepChange,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onBeginFieldChange,
  onCommitFieldChange,
}: FieldInspectorPanelProps) {
  const selected = selectedField ?? fields.find((field) => field.id === selectedFieldId) ?? null;
  const selectedMinSize = selected ? getMinFieldSize(selected.type) : getMinFieldSize('text');
  const [draft, setDraft] = useState<InspectorDraft | null>(null);
  const [arrowKeyMoveStepDraft, setArrowKeyMoveStepDraft] = useState(String(arrowKeyMoveStep));

  useEffect(() => {
    if (!selected) {
      setDraft(null);
      return;
    }
    setDraft({
      name: selected.name,
      page: String(selected.page),
      x: String(Math.round(selected.rect.x)),
      y: String(Math.round(selected.rect.y)),
      width: String(Math.round(selected.rect.width)),
      height: String(Math.round(selected.rect.height)),
    });
  }, [
    selected?.id,
    selected?.name,
    selected?.page,
    selected?.rect.x,
    selected?.rect.y,
    selected?.rect.width,
    selected?.rect.height,
  ]);

  useEffect(() => {
    setArrowKeyMoveStepDraft(String(arrowKeyMoveStep));
  }, [arrowKeyMoveStep]);

  /**
   * Patch rect properties while keeping the rest of the geometry intact.
   */
  const updateDraftField = (key: keyof InspectorDraft, value: string) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const normalizeRect = (patch: Partial<FieldRect>) => {
    if (!selected) return null;
    return { ...selected.rect, ...patch };
  };

  const commitName = () => {
    if (!selected || !draft) return;
    if (draft.name !== selected.name) {
      onUpdateField(selected.id, { name: draft.name });
    }
  };

  const commitPage = () => {
    if (!selected || !draft) return;
    const nextPage = Math.max(1, Math.round(Number(draft.page) || 1));
    setDraft((prev) => (prev ? { ...prev, page: String(nextPage) } : prev));
    if (nextPage !== selected.page) {
      onUpdateField(selected.id, { page: nextPage });
    }
  };

  const commitRect = (axis: 'x' | 'y' | 'width' | 'height') => {
    if (!selected || !draft) return;
    let nextRect: FieldRect | null = null;
    if (axis === 'x') {
      nextRect = normalizeRect({ x: Number(draft.x) || 0 });
    } else if (axis === 'y') {
      nextRect = normalizeRect({ y: Number(draft.y) || 0 });
    } else if (axis === 'width') {
      nextRect = normalizeRect({ width: Math.max(selectedMinSize, Number(draft.width) || 0) });
    } else if (axis === 'height') {
      nextRect = normalizeRect({ height: Math.max(selectedMinSize, Number(draft.height) || 0) });
    }
    if (!nextRect) return;
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        x: String(Math.round(nextRect.x)),
        y: String(Math.round(nextRect.y)),
        width: String(Math.round(nextRect.width)),
        height: String(Math.round(nextRect.height)),
      };
    });
    if (
      nextRect.x !== selected.rect.x ||
      nextRect.y !== selected.rect.y ||
      nextRect.width !== selected.rect.width ||
      nextRect.height !== selected.rect.height
    ) {
      onUpdateField(selected.id, { rect: nextRect });
    }
  };

  const beginFieldEdit = () => {
    if (!selected) return;
    onBeginFieldChange();
  };

  const commitFieldEdit = (commit: () => void) => {
    if (!selected) return;
    commit();
    onCommitFieldChange();
  };

  const handleNumberInputKeyDown = (commit: () => void) => (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    commitFieldEdit(commit);
    event.currentTarget.blur();
  };

  const commitArrowKeyMoveStep = () => {
    const nextStep = sanitizeArrowKeyMoveStep(arrowKeyMoveStepDraft, arrowKeyMoveStep);
    setArrowKeyMoveStepDraft(String(nextStep));
    if (nextStep !== arrowKeyMoveStep) {
      onArrowKeyMoveStepChange(nextStep);
    }
  };

  const handleArrowKeyMoveStepKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      commitArrowKeyMoveStep();
      event.currentTarget.blur();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setArrowKeyMoveStepDraft(String(arrowKeyMoveStep));
      event.currentTarget.blur();
    }
  };

  return (
    <aside className="panel panel--inspector">
      <div className="panel__header">
        <div>
          <h2>Inspector</h2>
          <p className="panel__hint">
            {selected ? `Editing ${selected.name} (enter to confirm)` : 'Select a field to edit its details.'}
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
                value={draft?.name ?? selected.name}
                onFocus={beginFieldEdit}
                onBlur={() => commitFieldEdit(commitName)}
                onChange={(event) => updateDraftField('name', event.target.value)}
                onKeyDown={handleNumberInputKeyDown(commitName)}
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
                  value={draft?.page ?? String(selected.page)}
                  onWheel={(event) => event.currentTarget.blur()}
                  onFocus={beginFieldEdit}
                  onBlur={() => commitFieldEdit(commitPage)}
                  onChange={(event) => updateDraftField('page', event.target.value)}
                  onKeyDown={handleNumberInputKeyDown(commitPage)}
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
                    value={draft?.x ?? String(Math.round(selected.rect.x))}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(() => commitRect('x'))}
                    onChange={(event) => updateDraftField('x', event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(() => commitRect('x'))}
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
                    value={draft?.y ?? String(Math.round(selected.rect.y))}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(() => commitRect('y'))}
                    onChange={(event) => updateDraftField('y', event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(() => commitRect('y'))}
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
                    value={draft?.width ?? String(Math.round(selected.rect.width))}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(() => commitRect('width'))}
                    onChange={(event) => updateDraftField('width', event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(() => commitRect('width'))}
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
                    value={draft?.height ?? String(Math.round(selected.rect.height))}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(() => commitRect('height'))}
                    onChange={(event) => updateDraftField('height', event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(() => commitRect('height'))}
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
          <div className="panel__section panel__section--tight">
            <span className="panel__label">
              Keyboard Move
            </span>
            <label
              className={`panel-pill-toggle${arrowKeyMoveEnabled ? ' panel-pill-toggle--active' : ''}`}
              htmlFor="arrow-key-move-toggle"
            >
              <input
                id="arrow-key-move-toggle"
                type="checkbox"
                checked={arrowKeyMoveEnabled}
                onChange={(event) => onArrowKeyMoveEnabledChange(event.target.checked)}
              />
              <span>Arrow keys</span>
            </label>
            <div className="panel__inline-control">
              <label className="panel__label" htmlFor="arrow-key-move-step">
                Step (pt)
              </label>
              <input
                id="arrow-key-move-step"
                name="arrow-key-move-step"
                className="panel__input panel__input--inline"
                type="number"
                min={MIN_ARROW_KEY_MOVE_STEP}
                max={MAX_ARROW_KEY_MOVE_STEP}
                step={1}
                inputMode="numeric"
                value={arrowKeyMoveStepDraft}
                onChange={(event) => setArrowKeyMoveStepDraft(event.target.value)}
                onBlur={commitArrowKeyMoveStep}
                onKeyDown={handleArrowKeyMoveStepKeyDown}
              />
            </div>
            <p className="panel__micro">
              When enabled, Arrow keys move the selected field by the configured step. Alt+Arrow still nudges by 1
              point, and Shift+Alt+Arrow nudges by 10. Make sure you&apos;re in Edit mode.
            </p>
          </div>
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
            focus search, [ and ] change pages, Arrow moves the selected field by the configured step when Keyboard
            Move is enabled, Alt+Arrow nudges by 1 point (Shift+Alt for 10), and hold Shift during corner-resize to
            lock aspect ratio.
          </p>
        </div>
      </div>
    </aside>
  );
}
