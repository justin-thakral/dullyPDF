import type { PdfField, RadioGroupSuggestion } from '../types';
import { normalizeRadioKey } from './radioGroups';

type ResolvedRadioSuggestionTarget = {
  field: PdfField;
  optionKey: string;
  optionLabel: string;
};

function compareFields(left: PdfField, right: PdfField) {
  if (left.page !== right.page) return left.page - right.page;
  if (left.rect.y !== right.rect.y) return left.rect.y - right.rect.y;
  if (left.rect.x !== right.rect.x) return left.rect.x - right.rect.x;
  return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
}

export function resolveRadioGroupSuggestionTargets(
  fields: PdfField[],
  suggestion: RadioGroupSuggestion,
): ResolvedRadioSuggestionTarget[] {
  const byId = new Map(fields.map((field) => [field.id, field] as const));
  const byName = new Map<string, PdfField[]>();
  for (const field of [...fields].sort(compareFields)) {
    const bucket = byName.get(field.name);
    if (bucket) {
      bucket.push(field);
    } else {
      byName.set(field.name, [field]);
    }
  }

  const consumed = new Set<string>();
  const resolved: ResolvedRadioSuggestionTarget[] = [];
  for (const entry of suggestion.suggestedFields) {
    let field = entry.fieldId ? byId.get(entry.fieldId) ?? null : null;
    if (!field) {
      const matches = byName.get(entry.fieldName) ?? [];
      field = matches.find((candidate) => !consumed.has(candidate.id)) ?? null;
    }
    if (!field || consumed.has(field.id)) {
      continue;
    }
    if (field.type !== 'checkbox' && field.type !== 'radio') {
      continue;
    }
    consumed.add(field.id);
    const optionLabel = String(entry.optionLabel || field.optionLabel || field.radioOptionLabel || field.name).trim();
    if (!optionLabel) {
      continue;
    }
    const optionKey = normalizeRadioKey(
      String(entry.optionKey || field.optionKey || field.radioOptionKey || optionLabel).trim(),
      `option_${resolved.length + 1}`,
    );
    resolved.push({
      field,
      optionKey,
      optionLabel,
    });
  }

  return resolved;
}

export function buildRadioSuggestionFieldMap(
  fields: PdfField[],
  suggestions: RadioGroupSuggestion[],
): Map<string, RadioGroupSuggestion> {
  const nextMap = new Map<string, RadioGroupSuggestion>();
  for (const suggestion of suggestions) {
    for (const target of resolveRadioGroupSuggestionTargets(fields, suggestion)) {
      const current = nextMap.get(target.field.id);
      const currentConfidence = Number(current?.confidence ?? 0);
      const nextConfidence = Number(suggestion.confidence ?? 0);
      if (!current || nextConfidence >= currentConfidence) {
        nextMap.set(target.field.id, suggestion);
      }
    }
  }
  return nextMap;
}

export function isRadioGroupSuggestionApplied(
  fields: PdfField[],
  suggestion: RadioGroupSuggestion,
): boolean {
  const targets = resolveRadioGroupSuggestionTargets(fields, suggestion);
  if (targets.length < 2) {
    return false;
  }
  const expectedGroupKey = normalizeRadioKey(
    suggestion.sourceField || suggestion.groupKey,
    suggestion.sourceField || suggestion.groupKey,
  );
  const groupId = targets[0].field.radioGroupId;
  if (!groupId) {
    return false;
  }
  return targets.every(({ field, optionKey }) => (
    field.type === 'radio' &&
    field.radioGroupId === groupId &&
    normalizeRadioKey(String(field.radioGroupKey || ''), '') === expectedGroupKey &&
    String(field.radioOptionKey || '').trim() === optionKey
  ));
}

export function applyRadioGroupSuggestion(
  fields: PdfField[],
  suggestion: RadioGroupSuggestion,
): PdfField[] {
  const targets = resolveRadioGroupSuggestionTargets(fields, suggestion);
  if (targets.length < 2) {
    return fields;
  }
  const targetById = new Map(targets.map((target) => [target.field.id, target] as const));
  const persistedGroupKey = suggestion.sourceField || suggestion.groupKey;
  return fields.map((field) => {
    const target = targetById.get(field.id);
    if (!target) {
      return field;
    }
    const nextValue = field.type === 'radio' && field.value === field.radioOptionKey
      ? target.optionKey
      : null;
    return {
      ...field,
      type: 'radio',
      value: nextValue,
      groupKey: undefined,
      optionKey: undefined,
      optionLabel: undefined,
      groupLabel: undefined,
      radioGroupId: suggestion.id,
      radioGroupKey: persistedGroupKey,
      radioGroupLabel: suggestion.groupLabel,
      radioOptionKey: target.optionKey,
      radioOptionLabel: target.optionLabel,
      radioOptionOrder: targets.findIndex((entry) => entry.field.id === field.id) + 1,
      radioGroupSource: 'ai_suggestion',
    };
  });
}
