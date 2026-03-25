import type { PageSize, PdfField, RadioGroup, RadioToolDraft } from '../types';
import { normaliseDataKey } from './dataSource';
import { ensureUniqueFieldName, makeId, normalizeRectForFieldType } from './fields';

function compareRadioFields(left: PdfField, right: PdfField) {
  const leftOrder = Number.isFinite(left.radioOptionOrder) ? Number(left.radioOptionOrder) : Number.MAX_SAFE_INTEGER;
  const rightOrder = Number.isFinite(right.radioOptionOrder) ? Number(right.radioOptionOrder) : Number.MAX_SAFE_INTEGER;
  if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  if (left.page !== right.page) return left.page - right.page;
  if (left.rect.y !== right.rect.y) return left.rect.y - right.rect.y;
  if (left.rect.x !== right.rect.x) return left.rect.x - right.rect.x;
  return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
}

function fallbackRadioGroupLabel(index: number) {
  return `Radio Group ${index}`;
}

function fallbackRadioOptionLabel(index: number) {
  return `Option ${index}`;
}

export function normalizeRadioKey(raw: string, fallback: string) {
  return normaliseDataKey(raw) || fallback;
}

export function buildRadioGroups(fields: PdfField[]): RadioGroup[] {
  const grouped = new Map<string, PdfField[]>();
  for (const field of fields) {
    if (field.type !== 'radio') continue;
    const groupId = String(field.radioGroupId || '').trim();
    if (!groupId) continue;
    const groupFields = grouped.get(groupId);
    if (groupFields) {
      groupFields.push(field);
    } else {
      grouped.set(groupId, [field]);
    }
  }

  return Array.from(grouped.entries())
    .map(([groupId, groupFields]) => {
      const sorted = [...groupFields].sort(compareRadioFields);
      const first = sorted[0];
      const optionOrder = sorted.map((field) => String(field.radioOptionKey || field.name || field.id));
      const options = sorted.map((field) => ({
        fieldId: field.id,
        optionKey: String(field.radioOptionKey || field.name || field.id),
        optionLabel: String(field.radioOptionLabel || field.name || field.radioOptionKey || field.id),
      }));
      const singlePage = sorted.every((field) => field.page === first.page) ? first.page : undefined;
      return {
        id: groupId,
        key: String(first.radioGroupKey || ''),
        label: String(first.radioGroupLabel || first.radioGroupKey || groupId),
        page: singlePage,
        optionOrder,
        options,
        source: first.radioGroupSource || 'manual',
      } as RadioGroup;
    })
    .sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: 'base' }));
}

export function buildNextRadioToolDraft(fields: PdfField[], preferredLabel?: string | null): RadioToolDraft {
  const groups = buildRadioGroups(fields);
  const nextIndex = groups.length + 1;
  const groupLabel = String(preferredLabel || '').trim() || fallbackRadioGroupLabel(nextIndex);
  return {
    groupId: makeId(),
    groupKey: normalizeRadioKey(groupLabel, `radio_group_${nextIndex}`),
    groupLabel,
    nextOptionKey: 'option_1',
    nextOptionLabel: fallbackRadioOptionLabel(1),
  };
}

export function buildRadioToolDraftForExistingGroup(
  fields: PdfField[],
  groupId: string,
): RadioToolDraft | null {
  const group = buildRadioGroups(fields).find((entry) => entry.id === groupId);
  if (!group) return null;
  const nextIndex = group.options.length + 1;
  return {
    groupId: group.id,
    groupKey: group.key,
    groupLabel: group.label,
    nextOptionKey: `option_${nextIndex}`,
    nextOptionLabel: fallbackRadioOptionLabel(nextIndex),
  };
}

function nextRadioOptionIdentity(
  fields: PdfField[],
  draft: RadioToolDraft,
): { optionKey: string; optionLabel: string; optionOrder: number } {
  const groupMembers = fields
    .filter((field) => field.type === 'radio' && field.radioGroupId === draft.groupId)
    .sort(compareRadioFields);
  const nextIndex = groupMembers.length + 1;
  const fallbackLabel = fallbackRadioOptionLabel(nextIndex);
  const optionLabel = String(draft.nextOptionLabel || '').trim() || fallbackLabel;
  const baseKey = normalizeRadioKey(
    String(draft.nextOptionKey || '').trim() || optionLabel,
    `option_${nextIndex}`,
  );
  let optionKey = baseKey;
  const used = new Set(groupMembers.map((field) => String(field.radioOptionKey || '').trim()).filter(Boolean));
  let suffix = 2;
  while (used.has(optionKey)) {
    optionKey = `${baseKey}_${suffix}`;
    suffix += 1;
  }
  return {
    optionKey,
    optionLabel,
    optionOrder: nextIndex,
  };
}

function clearCheckboxMetadata(field: PdfField): PdfField {
  return {
    ...field,
    groupKey: undefined,
    optionKey: undefined,
    optionLabel: undefined,
    groupLabel: undefined,
  };
}

function clearRadioMetadata(field: PdfField): PdfField {
  return {
    ...field,
    radioGroupId: undefined,
    radioGroupKey: undefined,
    radioGroupLabel: undefined,
    radioOptionKey: undefined,
    radioOptionLabel: undefined,
    radioOptionOrder: undefined,
    radioGroupSource: undefined,
  };
}

export function createRadioFieldFromRect(
  fields: PdfField[],
  page: number,
  pageSize: PageSize,
  rect: PdfField['rect'],
  draft: RadioToolDraft,
): PdfField {
  const normalizedRect = normalizeRectForFieldType(rect, 'radio', pageSize);
  const option = nextRadioOptionIdentity(fields, draft);
  const existingNames = new Set(fields.map((field) => field.name));
  const name = ensureUniqueFieldName(`${draft.groupKey}_${option.optionKey}`, existingNames);
  return {
    id: makeId(),
    name,
    type: 'radio',
    page,
    rect: normalizedRect,
    radioGroupId: draft.groupId,
    radioGroupKey: draft.groupKey,
    radioGroupLabel: draft.groupLabel,
    radioOptionKey: option.optionKey,
    radioOptionLabel: option.optionLabel,
    radioOptionOrder: option.optionOrder,
    radioGroupSource: 'manual',
    value: null,
  };
}

export function advanceRadioToolDraft(fields: PdfField[], draft: RadioToolDraft): RadioToolDraft {
  const groupMembers = fields.filter((field) => field.type === 'radio' && field.radioGroupId === draft.groupId);
  const nextIndex = groupMembers.length + 1;
  return {
    ...draft,
    nextOptionKey: `option_${nextIndex}`,
    nextOptionLabel: fallbackRadioOptionLabel(nextIndex),
  };
}

function deriveConvertedOptionLabel(field: PdfField, index: number) {
  const explicit = String(field.optionLabel || field.radioOptionLabel || '').trim();
  if (explicit) return explicit;
  return fallbackRadioOptionLabel(index);
}

function deriveConvertedOptionKey(field: PdfField, label: string, index: number) {
  const explicit = String(field.optionKey || field.radioOptionKey || '').trim();
  if (explicit) {
    return normalizeRadioKey(explicit, `option_${index}`);
  }
  return normalizeRadioKey(label, `option_${index}`);
}

export function convertFieldsToRadioGroup(
  fields: PdfField[],
  fieldIds: string[],
  draft: RadioToolDraft,
): PdfField[] {
  if (!fieldIds.length) return fields;
  const targetSet = new Set(fieldIds);
  const existingGroupMembers = fields
    .filter((field) => field.type === 'radio' && field.radioGroupId === draft.groupId && !targetSet.has(field.id))
    .sort(compareRadioFields);
  const usedOptionKeys = new Set(
    existingGroupMembers.map((field) => String(field.radioOptionKey || '').trim()).filter(Boolean),
  );

  let nextOrder = existingGroupMembers.length + 1;
  return fields.map((field) => {
    if (!targetSet.has(field.id)) return field;
    const optionLabel = deriveConvertedOptionLabel(field, nextOrder);
    const baseOptionKey = deriveConvertedOptionKey(field, optionLabel, nextOrder);
    let optionKey = baseOptionKey;
    let suffix = 2;
    while (usedOptionKeys.has(optionKey)) {
      optionKey = `${baseOptionKey}_${suffix}`;
      suffix += 1;
    }
    usedOptionKeys.add(optionKey);
    const nextField = clearCheckboxMetadata({
      ...field,
      type: 'radio',
      rect: { ...field.rect },
      radioGroupId: draft.groupId,
      radioGroupKey: draft.groupKey,
      radioGroupLabel: draft.groupLabel,
      radioOptionKey: optionKey,
      radioOptionLabel: optionLabel,
      radioOptionOrder: nextOrder,
      radioGroupSource: 'manual',
      value: null,
    });
    nextOrder += 1;
    return nextField;
  });
}

export function renameRadioGroup(
  fields: PdfField[],
  groupId: string,
  updates: { label?: string; key?: string },
): PdfField[] {
  return fields.map((field) => {
    if (field.type !== 'radio' || field.radioGroupId !== groupId) return field;
    return {
      ...field,
      radioGroupLabel: updates.label ?? field.radioGroupLabel,
      radioGroupKey: updates.key ?? field.radioGroupKey,
    };
  });
}

export function updateRadioFieldOption(
  fields: PdfField[],
  fieldId: string,
  updates: { label?: string; key?: string },
): PdfField[] {
  return fields.map((field) => {
    if (field.id !== fieldId || field.type !== 'radio') return field;
    const nextKey = updates.key ?? field.radioOptionKey;
    const nextValue = field.value;
    return {
      ...field,
      radioOptionLabel: updates.label ?? field.radioOptionLabel,
      radioOptionKey: nextKey,
      value:
        typeof nextValue === 'string' && field.radioOptionKey && nextValue === field.radioOptionKey
          ? nextKey
          : nextValue,
    };
  });
}

export function moveRadioFieldToGroup(
  fields: PdfField[],
  fieldId: string,
  targetGroup: RadioGroup,
): PdfField[] {
  const nextOrder = targetGroup.options.length + 1;
  return fields.map((field) => {
    if (field.id !== fieldId || field.type !== 'radio') return field;
    const optionLabel = String(field.radioOptionLabel || field.name || fallbackRadioOptionLabel(nextOrder));
    const optionKey = normalizeRadioKey(String(field.radioOptionKey || optionLabel), `option_${nextOrder}`);
    return {
      ...field,
      radioGroupId: targetGroup.id,
      radioGroupKey: targetGroup.key,
      radioGroupLabel: targetGroup.label,
      radioOptionOrder: nextOrder,
      radioOptionKey: optionKey,
      radioOptionLabel: optionLabel,
      radioGroupSource: targetGroup.source,
      value: null,
    };
  });
}

export function reorderRadioField(
  fields: PdfField[],
  fieldId: string,
  direction: 'up' | 'down',
): PdfField[] {
  const selectedField = fields.find((field) => field.id === fieldId && field.type === 'radio');
  if (!selectedField?.radioGroupId) return fields;
  const groupMembers = fields
    .filter((field) => field.type === 'radio' && field.radioGroupId === selectedField.radioGroupId)
    .sort(compareRadioFields);
  const currentIndex = groupMembers.findIndex((field) => field.id === fieldId);
  if (currentIndex === -1) return fields;
  const swapIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
  if (swapIndex < 0 || swapIndex >= groupMembers.length) return fields;
  const reordered = [...groupMembers];
  const [moved] = reordered.splice(currentIndex, 1);
  reordered.splice(swapIndex, 0, moved);
  const orderById = new Map(reordered.map((field, index) => [field.id, index + 1]));
  return fields.map((field) => {
    if (field.type !== 'radio' || field.radioGroupId !== selectedField.radioGroupId) return field;
    return {
      ...field,
      radioOptionOrder: orderById.get(field.id) ?? field.radioOptionOrder,
    };
  });
}

export function dissolveRadioGroup(fields: PdfField[], groupId: string): PdfField[] {
  return fields.map((field) => {
    if (field.type !== 'radio' || field.radioGroupId !== groupId) return field;
    return {
      ...clearRadioMetadata(field),
      type: 'checkbox',
      value: field.value === null || field.value === undefined ? null : Boolean(field.value),
    };
  });
}

export function convertRadioFieldToType(field: PdfField, type: Exclude<PdfField['type'], 'radio'>): PdfField {
  const cleared = clearRadioMetadata(field);
  if (type === 'checkbox') {
    return {
      ...cleared,
      type,
      value: field.value === null || field.value === undefined ? null : Boolean(field.value),
    };
  }
  return {
    ...cleared,
    type,
    value: type === 'signature' || type === 'text' || type === 'date'
      ? (typeof field.value === 'string' ? field.value : null)
      : field.value,
  };
}

export function setRadioGroupSelectedValue(fields: PdfField[], fieldId: string): PdfField[] {
  const selectedField = fields.find((field) => field.id === fieldId && field.type === 'radio');
  if (!selectedField?.radioGroupId || !selectedField.radioOptionKey) return fields;
  return fields.map((field) => {
    if (field.type !== 'radio' || field.radioGroupId !== selectedField.radioGroupId) return field;
    return {
      ...field,
      value: field.id === selectedField.id ? selectedField.radioOptionKey : null,
    };
  });
}
