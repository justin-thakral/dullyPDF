/**
 * Field inspector panel for editing geometry and metadata.
 */
import { useEffect, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import type {
  CreateTool,
  FieldRect,
  FieldType,
  PdfField,
  RadioGroup,
  RadioGroupSuggestion,
  RadioToolDraft,
} from '../../types';
import { getMinFieldSize } from '../../utils/fields';
import {
  MAX_ARROW_KEY_MOVE_STEP,
  MIN_ARROW_KEY_MOVE_STEP,
  sanitizeArrowKeyMoveStep,
} from '../../utils/fieldMovement';
import { CREATE_TOOLS, FIELD_TYPES, createToolLabel, fieldTypeLabel } from '../../utils/fieldUi';

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
  radioGroups: RadioGroup[];
  selectedRadioSuggestion: RadioGroupSuggestion | null;
  activeCreateTool: CreateTool | null;
  radioToolDraft: RadioToolDraft | null;
  pendingQuickRadioFields: PdfField[];
  arrowKeyMoveEnabled: boolean;
  arrowKeyMoveStep: number;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onSetFieldType: (fieldId: string, type: FieldType) => void;
  onUpdateFieldDraft: (fieldId: string, updates: Partial<PdfField>) => void;
  onDeleteField: (fieldId: string) => void;
  onCreateToolChange: (type: CreateTool | null) => void;
  onUpdateRadioToolDraft: (updates: Partial<RadioToolDraft>) => void;
  onApplyPendingQuickRadioSelection: () => void;
  onCancelPendingQuickRadioSelection: () => void;
  onRemovePendingQuickRadioField: (fieldId: string) => void;
  onRenameRadioGroup: (groupId: string, updates: { label?: string; key?: string }) => void;
  onUpdateRadioFieldOption: (fieldId: string, updates: { label?: string; key?: string }) => void;
  onMoveRadioFieldToGroup: (fieldId: string, targetGroup: RadioGroup) => void;
  onReorderRadioField: (fieldId: string, direction: 'up' | 'down') => void;
  onDissolveRadioGroup: (groupId: string) => void;
  onApplyRadioSuggestion: (suggestion: RadioGroupSuggestion) => void;
  onDismissRadioSuggestion: (suggestionId: string) => void;
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
  radioGroups,
  selectedRadioSuggestion,
  activeCreateTool,
  radioToolDraft,
  pendingQuickRadioFields,
  arrowKeyMoveEnabled,
  arrowKeyMoveStep,
  onUpdateField,
  onSetFieldType,
  onDeleteField,
  onCreateToolChange,
  onUpdateRadioToolDraft,
  onApplyPendingQuickRadioSelection,
  onCancelPendingQuickRadioSelection,
  onRemovePendingQuickRadioField,
  onRenameRadioGroup,
  onUpdateRadioFieldOption,
  onMoveRadioFieldToGroup,
  onReorderRadioField,
  onDissolveRadioGroup,
  onApplyRadioSuggestion,
  onDismissRadioSuggestion,
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
  const [radioGroupLabelDraft, setRadioGroupLabelDraft] = useState('');
  const [radioGroupKeyDraft, setRadioGroupKeyDraft] = useState('');
  const [radioOptionLabelDraft, setRadioOptionLabelDraft] = useState('');
  const [radioOptionKeyDraft, setRadioOptionKeyDraft] = useState('');
  const [radioMoveGroupId, setRadioMoveGroupId] = useState('');

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

  const selectedRadioGroup =
    selected?.type === 'radio' && selected.radioGroupId
      ? radioGroups.find((group) => group.id === selected.radioGroupId) ?? null
      : null;
  const selectedRadioIndex = selectedRadioGroup
    ? selectedRadioGroup.options.findIndex((option) => option.fieldId === selected?.id)
    : -1;
  const otherRadioGroups = selectedRadioGroup
    ? radioGroups.filter((group) => group.id !== selectedRadioGroup.id)
    : radioGroups;

  useEffect(() => {
    if (!selectedRadioGroup || selected?.type !== 'radio') {
      setRadioGroupLabelDraft('');
      setRadioGroupKeyDraft('');
      setRadioOptionLabelDraft('');
      setRadioOptionKeyDraft('');
      setRadioMoveGroupId('');
      return;
    }
    setRadioGroupLabelDraft(selectedRadioGroup.label);
    setRadioGroupKeyDraft(selectedRadioGroup.key);
    setRadioOptionLabelDraft(selected.radioOptionLabel || selected.name);
    setRadioOptionKeyDraft(selected.radioOptionKey || selected.name);
    setRadioMoveGroupId('');
  }, [
    selected?.id,
    selected?.name,
    selected?.radioOptionKey,
    selected?.radioOptionLabel,
    selected?.type,
    selectedRadioGroup,
  ]);

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

  const commitRadioGroupDraft = () => {
    if (!selectedRadioGroup) return;
    const nextLabel = radioGroupLabelDraft.trim() || selectedRadioGroup.label;
    const nextKey = radioGroupKeyDraft.trim() || selectedRadioGroup.key;
    if (nextLabel === selectedRadioGroup.label && nextKey === selectedRadioGroup.key) {
      setRadioGroupLabelDraft(nextLabel);
      setRadioGroupKeyDraft(nextKey);
      return;
    }
    setRadioGroupLabelDraft(nextLabel);
    setRadioGroupKeyDraft(nextKey);
    onRenameRadioGroup(selectedRadioGroup.id, {
      label: nextLabel,
      key: nextKey,
    });
  };

  const commitRadioOptionDraft = () => {
    if (!selected || selected.type !== 'radio') return;
    const nextLabel = radioOptionLabelDraft.trim() || selected.radioOptionLabel || selected.name;
    const nextKey = radioOptionKeyDraft.trim() || selected.radioOptionKey || selected.name;
    if (nextLabel === selected.radioOptionLabel && nextKey === selected.radioOptionKey) {
      setRadioOptionLabelDraft(nextLabel);
      setRadioOptionKeyDraft(nextKey);
      return;
    }
    setRadioOptionLabelDraft(nextLabel);
    setRadioOptionKeyDraft(nextKey);
    onUpdateRadioFieldOption(selected.id, {
      label: nextLabel,
      key: nextKey,
    });
  };

  const handleMoveRadioGroup = (groupId: string) => {
    setRadioMoveGroupId(groupId);
    if (!selected || selected.type !== 'radio' || !groupId) {
      return;
    }
    const targetGroup = radioGroups.find((group) => group.id === groupId);
    if (!targetGroup) {
      return;
    }
    onMoveRadioFieldToGroup(selected.id, targetGroup);
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

              {selected.type === 'radio' && selectedRadioGroup ? (
                <div className="panel__section panel__section--divider">
                  <h3>Radio Group</h3>
                  <label className="panel__label" htmlFor="radio-group-label">
                    Group label
                  </label>
                  <input
                    id="radio-group-label"
                    name="radio-group-label"
                    className="panel__input"
                    value={radioGroupLabelDraft}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(commitRadioGroupDraft)}
                    onChange={(event) => setRadioGroupLabelDraft(event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(commitRadioGroupDraft)}
                  />
                  <label className="panel__label" htmlFor="radio-group-key">
                    Group key
                  </label>
                  <input
                    id="radio-group-key"
                    name="radio-group-key"
                    className="panel__input"
                    value={radioGroupKeyDraft}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(commitRadioGroupDraft)}
                    onChange={(event) => setRadioGroupKeyDraft(event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(commitRadioGroupDraft)}
                  />
                  <div className="panel__row">
                    <label className="panel__label" htmlFor="radio-move-group">
                      Move to group
                    </label>
                    <select
                      id="radio-move-group"
                      name="radio-move-group"
                      className="panel__select"
                      value={radioMoveGroupId}
                      onChange={(event) => handleMoveRadioGroup(event.target.value)}
                    >
                      <option value="">Current group</option>
                      {otherRadioGroups.map((group) => (
                        <option key={group.id} value={group.id}>
                          {group.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="panel__label" htmlFor="radio-option-label">
                    Option label
                  </label>
                  <input
                    id="radio-option-label"
                    name="radio-option-label"
                    className="panel__input"
                    value={radioOptionLabelDraft}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(commitRadioOptionDraft)}
                    onChange={(event) => setRadioOptionLabelDraft(event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(commitRadioOptionDraft)}
                  />
                  <label className="panel__label" htmlFor="radio-option-key">
                    Option key
                  </label>
                  <input
                    id="radio-option-key"
                    name="radio-option-key"
                    className="panel__input"
                    value={radioOptionKeyDraft}
                    onFocus={beginFieldEdit}
                    onBlur={() => commitFieldEdit(commitRadioOptionDraft)}
                    onChange={(event) => setRadioOptionKeyDraft(event.target.value)}
                    onKeyDown={handleNumberInputKeyDown(commitRadioOptionDraft)}
                  />
                  <div className="panel__action-grid">
                    <button
                      className="ui-button ui-button--ghost ui-button--compact"
                      type="button"
                      onClick={() => onReorderRadioField(selected.id, 'up')}
                      disabled={selectedRadioIndex <= 0}
                    >
                      Move up
                    </button>
                    <button
                      className="ui-button ui-button--ghost ui-button--compact"
                      type="button"
                      onClick={() => onReorderRadioField(selected.id, 'down')}
                      disabled={selectedRadioIndex < 0 || selectedRadioIndex >= selectedRadioGroup.options.length - 1}
                    >
                      Move down
                    </button>
                  </div>
                  <button
                    className="ui-button ui-button--danger ui-button--compact"
                    type="button"
                    onClick={() => onDissolveRadioGroup(selectedRadioGroup.id)}
                  >
                    Dissolve group to checkboxes
                  </button>
                </div>
              ) : null}

              {selectedRadioSuggestion ? (
                <div className="panel__section panel__section--divider">
                  <h3>OpenAI Radio Suggestion</h3>
                  <p className="panel__micro">
                    Suggested {selectedRadioSuggestion.groupLabel} radio group with {selectedRadioSuggestion.suggestedFields.length} options.
                  </p>
                  <div className="panel__list panel__list--compact">
                    {selectedRadioSuggestion.suggestedFields.map((option) => (
                      <div key={`${selectedRadioSuggestion.id}:${option.fieldId || option.fieldName}`} className="panel-selection-row">
                        <span>{option.optionLabel}</span>
                        <span className="panel__micro">{option.fieldName}</span>
                      </div>
                    ))}
                  </div>
                  {selectedRadioSuggestion.selectionReason ? (
                    <p className="panel__micro">
                      Pattern: {selectedRadioSuggestion.selectionReason}
                    </p>
                  ) : null}
                  {selectedRadioSuggestion.reasoning ? (
                    <p className="panel__micro">{selectedRadioSuggestion.reasoning}</p>
                  ) : null}
                  <div className="panel__action-grid">
                    <button
                      className="ui-button ui-button--primary ui-button--compact"
                      type="button"
                      onClick={() => onApplyRadioSuggestion(selectedRadioSuggestion)}
                    >
                      Apply suggestion
                    </button>
                    <button
                      className="ui-button ui-button--ghost ui-button--compact"
                      type="button"
                      onClick={() => onDismissRadioSuggestion(selectedRadioSuggestion.id)}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>

        <div className="panel__section panel__section--divider">
          <h3>Create field</h3>
          <span className="panel__label">Create tool</span>
          <div className="panel-display-modes" role="group" aria-label="Create tool">
            {CREATE_TOOLS.map((type) => (
              <button
                key={type}
                type="button"
                className={`panel-mode-chip${activeCreateTool === type ? ' panel-mode-chip--active' : ''}`}
                onClick={() => onCreateToolChange(activeCreateTool === type ? null : type)}
              >
                {createToolLabel(type)}
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
          {radioToolDraft && (activeCreateTool === 'radio' || activeCreateTool === 'quick-radio') ? (
            <div className="panel__section panel__section--tight panel__section--divider">
              <h3>{activeCreateTool === 'quick-radio' ? 'Quick Radio Group' : 'Radio Tool'}</h3>
              <label className="panel__label" htmlFor="radio-tool-group-label">
                Group label
              </label>
              <input
                id="radio-tool-group-label"
                name="radio-tool-group-label"
                className="panel__input"
                value={radioToolDraft.groupLabel}
                onChange={(event) => onUpdateRadioToolDraft({ groupLabel: event.target.value })}
              />
              <label className="panel__label" htmlFor="radio-tool-group-key">
                Group key
              </label>
              <input
                id="radio-tool-group-key"
                name="radio-tool-group-key"
                className="panel__input"
                value={radioToolDraft.groupKey}
                onChange={(event) => onUpdateRadioToolDraft({ groupKey: event.target.value })}
              />
              {activeCreateTool === 'radio' ? (
                <>
                  <label className="panel__label" htmlFor="radio-tool-option-label">
                    Next option label
                  </label>
                  <input
                    id="radio-tool-option-label"
                    name="radio-tool-option-label"
                    className="panel__input"
                    value={radioToolDraft.nextOptionLabel}
                    onChange={(event) => onUpdateRadioToolDraft({ nextOptionLabel: event.target.value })}
                  />
                  <label className="panel__label" htmlFor="radio-tool-option-key">
                    Next option key
                  </label>
                  <input
                    id="radio-tool-option-key"
                    name="radio-tool-option-key"
                    className="panel__input"
                    value={radioToolDraft.nextOptionKey}
                    onChange={(event) => onUpdateRadioToolDraft({ nextOptionKey: event.target.value })}
                  />
                  <p className="panel__micro">
                    Draw one radio option at a time. Each placement stays in this group until you switch tools or edit
                    the group draft.
                  </p>
                </>
              ) : (
                <>
                  <p className="panel__micro">
                    Drag a selection box that mostly encloses the checkbox fields you want on the active page, review
                    the selection here, and then convert them into one radio group. Hold Alt while dragging to include
                    any checkbox the marquee touches.
                  </p>
                  <div className="panel__list panel__list--compact">
                    {pendingQuickRadioFields.length ? (
                      pendingQuickRadioFields.map((field) => (
                        <div key={field.id} className="panel-selection-row">
                          <span>{field.name}</span>
                          <button
                            className="panel-selection-row__remove"
                            type="button"
                            onClick={() => onRemovePendingQuickRadioField(field.id)}
                          >
                            Remove
                          </button>
                        </div>
                      ))
                    ) : (
                      <p className="panel__micro">No checkbox fields selected yet.</p>
                    )}
                  </div>
                  <div className="panel__action-grid">
                    <button
                      className="ui-button ui-button--ghost ui-button--compact"
                      type="button"
                      onClick={onCancelPendingQuickRadioSelection}
                      disabled={pendingQuickRadioFields.length === 0}
                    >
                      Clear selection
                    </button>
                    <button
                      className="ui-button ui-button--primary ui-button--compact"
                      type="button"
                      onClick={onApplyPendingQuickRadioSelection}
                      disabled={pendingQuickRadioFields.length === 0}
                    >
                      Convert selection
                    </button>
                  </div>
                </>
              )}
            </div>
          ) : null}
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
          <span className="panel__label">History</span>
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
            Shortcuts: T/D/S/C/R/Q set create tool, Esc clears active create tool,
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
