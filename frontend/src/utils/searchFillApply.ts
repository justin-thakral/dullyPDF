import type {
  CheckboxHint,
  CheckboxRule,
  DataSourceKind,
  PdfField,
  TextTransformRule,
} from '../types';
import { normaliseDataKey } from './dataSource';
import { computeCheckboxMeta, type CheckboxMeta as CheckboxMetaType } from './checkboxMeta';
import {
  coerceCheckboxBoolean,
  coerceCheckboxPresence,
  getNumericSuffixBase,
  normalizeCheckboxValueMap,
  splitCheckboxListValue,
} from './searchFill';

const CHECKBOX_ALIASES: Record<string, string[]> = {
  allergies: ['allergy', 'has_allergies'],
  drug_use: ['substance_use', 'illicit_drug_use', 'has_drug_use'],
  alcohol_use: ['drinks_alcohol', 'etoh_use', 'has_alcohol_use'],
  tobacco_use: ['smoking', 'smoker', 'smoking_status', 'has_tobacco_use'],
  pregnant: ['pregnancy', 'pregnancy_status', 'is_pregnant'],
  medications: ['current_medications', 'takes_medications'],
};

const CHECKBOX_TRUE_ALIASES = ['yes', 'true', 'y', 't', 'on', 'checked', '1'];
const CHECKBOX_FALSE_ALIASES = ['no', 'false', 'n', 'f', 'off', 'unchecked', '0'];

type CheckboxGroup = {
  options: Map<string, PdfField[]>;
  optionAliases: Map<string, Set<string>>;
};

type CheckboxOptionLookup = {
  groupKey: string;
  optionKey: string;
};

type PreparedCheckboxLookup = {
  checkboxMetaById: Map<string, CheckboxMetaType>;
  checkboxGroups: Map<string, CheckboxGroup>;
  checkboxOptionIndex: Map<string, CheckboxOptionLookup>;
  checkboxOptionConflicts: Set<string>;
  checkboxNameIndex: Map<string, PdfField[]>;
};

export type ApplySearchFillRowOptions = {
  row: Record<string, unknown>;
  fields: PdfField[];
  checkboxRules?: CheckboxRule[];
  checkboxHints?: CheckboxHint[];
  textTransformRules?: TextTransformRule[];
  dataSourceKind: DataSourceKind;
};

function compactCheckboxToken(raw: string): string {
  return normaliseDataKey(raw).replace(/_/g, '');
}

function coerceValue(value: unknown): string | number | boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString().slice(0, 10);
  return String(value);
}

function parseDateFromUnknown(value: unknown): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === 'string') {
    const match = value.match(/\d{4}[-/]\d{2}[-/]\d{2}/);
    if (!match) return null;
    const normalized = match[0].replace(/\//g, '-');
    const parsed = new Date(`${normalized}T00:00:00Z`);
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

function buildCheckboxGroups(fields: PdfField[], metaById: Map<string, CheckboxMetaType>): Map<string, CheckboxGroup> {
  const groups = new Map<string, CheckboxGroup>();
  for (const field of fields) {
    if (field.type !== 'checkbox') continue;
    const meta = metaById.get(field.id);
    if (!meta) continue;
    const groupKey = meta.groupKey;
    const optionKey = meta.optionKey;
    const group = groups.get(groupKey) || { options: new Map(), optionAliases: new Map() };
    const existing = group.options.get(optionKey);
    if (existing) {
      existing.push(field);
    } else {
      group.options.set(optionKey, [field]);
    }
    const aliases = group.optionAliases.get(optionKey) || new Set<string>();
    aliases.add(optionKey);
    if (meta.optionLabel) {
      aliases.add(normaliseDataKey(meta.optionLabel));
    }
    group.optionAliases.set(optionKey, aliases);
    groups.set(groupKey, group);
  }
  return groups;
}

const checkboxNameIndexCache = new WeakMap<PdfField[], Map<string, PdfField[]>>();
const checkboxLookupCache = new WeakMap<PdfField[], Map<string, PreparedCheckboxLookup>>();
const checkboxHintsByFieldCache = new WeakMap<CheckboxHint[], Map<string, CheckboxHint>>();
const textTransformRulesByTargetCache = new WeakMap<TextTransformRule[], Map<string, TextTransformRule[]>>();

function getCheckboxNameIndex(fields: PdfField[]): Map<string, PdfField[]> {
  const cached = checkboxNameIndexCache.get(fields);
  if (cached) return cached;
  const checkboxNameIndex = new Map<string, PdfField[]>();
  for (const field of fields) {
    if (field.type !== 'checkbox') continue;
    const normalizedName = normaliseDataKey(field.name || '');
    if (!normalizedName) continue;
    const existing = checkboxNameIndex.get(normalizedName);
    if (existing) {
      existing.push(field);
    } else {
      checkboxNameIndex.set(normalizedName, [field]);
    }
  }
  checkboxNameIndexCache.set(fields, checkboxNameIndex);
  return checkboxNameIndex;
}

function getPreparedCheckboxLookup(fields: PdfField[], normalizedRowKeys: string[]): PreparedCheckboxLookup {
  const cacheKey = normalizedRowKeys.join('|');
  const cachedForFields = checkboxLookupCache.get(fields);
  const cached = cachedForFields?.get(cacheKey);
  if (cached) return cached;

  const checkboxMetaById = computeCheckboxMeta(fields, normalizedRowKeys);
  const checkboxGroups = buildCheckboxGroups(fields, checkboxMetaById);
  const checkboxOptionIndex = new Map<string, CheckboxOptionLookup>();
  const checkboxOptionConflicts = new Set<string>();

  for (const [groupKey, group] of checkboxGroups.entries()) {
    for (const [optionKey, aliases] of group.optionAliases.entries()) {
      for (const alias of aliases) {
        const combined = normaliseDataKey(`${groupKey}_${alias}`);
        if (!combined) continue;
        const existing = checkboxOptionIndex.get(combined);
        if (existing && existing.optionKey !== optionKey) {
          checkboxOptionConflicts.add(combined);
          checkboxOptionIndex.delete(combined);
          continue;
        }
        checkboxOptionIndex.set(combined, { groupKey, optionKey });
      }
    }
  }

  const prepared = {
    checkboxMetaById,
    checkboxGroups,
    checkboxOptionIndex,
    checkboxOptionConflicts,
    checkboxNameIndex: getCheckboxNameIndex(fields),
  };
  const nextCache = cachedForFields ?? new Map<string, PreparedCheckboxLookup>();
  nextCache.set(cacheKey, prepared);
  if (!cachedForFields) {
    checkboxLookupCache.set(fields, nextCache);
  }
  return prepared;
}

function getCheckboxHintsByField(checkboxHints?: CheckboxHint[]): Map<string, CheckboxHint> {
  if (!checkboxHints?.length) return new Map<string, CheckboxHint>();
  const cached = checkboxHintsByFieldCache.get(checkboxHints);
  if (cached) return cached;
  const checkboxHintsByField = new Map<string, CheckboxHint>();
  for (const hint of checkboxHints) {
    if (!hint || !hint.databaseField) continue;
    const key = normaliseDataKey(hint.databaseField);
    if (!key || checkboxHintsByField.has(key)) continue;
    checkboxHintsByField.set(key, hint);
  }
  checkboxHintsByFieldCache.set(checkboxHints, checkboxHintsByField);
  return checkboxHintsByField;
}

function getTextTransformRulesByTarget(
  textTransformRules?: TextTransformRule[],
): Map<string, TextTransformRule[]> {
  if (!textTransformRules?.length) return new Map<string, TextTransformRule[]>();
  const cached = textTransformRulesByTargetCache.get(textTransformRules);
  if (cached) return cached;
  const textTransformRulesByTarget = new Map<string, TextTransformRule[]>();
  for (const rawRule of textTransformRules) {
    if (!rawRule) continue;
    const target = normaliseDataKey(rawRule.targetField || '');
    if (!target) continue;
    const existing = textTransformRulesByTarget.get(target);
    if (existing) {
      existing.push(rawRule);
    } else {
      textTransformRulesByTarget.set(target, [rawRule]);
    }
  }
  for (const rules of textTransformRulesByTarget.values()) {
    rules.sort((left, right) => {
      const leftConfidence = typeof left.confidence === 'number' ? left.confidence : 0.0;
      const rightConfidence = typeof right.confidence === 'number' ? right.confidence : 0.0;
      return rightConfidence - leftConfidence;
    });
  }
  textTransformRulesByTargetCache.set(textTransformRules, textTransformRulesByTarget);
  return textTransformRulesByTarget;
}

export function applySearchFillRowToFields({
  row,
  fields,
  checkboxRules,
  checkboxHints,
  textTransformRules,
  dataSourceKind,
}: ApplySearchFillRowOptions): PdfField[] {
  const normalizedRow = new Map<string, unknown>();
  for (const [key, value] of Object.entries(row)) {
    normalizedRow.set(normaliseDataKey(key), value);
  }
  const normalizedRowKeys = Array.from(normalizedRow.keys());
  const {
    checkboxMetaById,
    checkboxGroups,
    checkboxOptionIndex,
    checkboxOptionConflicts,
    checkboxNameIndex,
  } = getPreparedCheckboxLookup(fields, normalizedRowKeys);
  const checkboxOverrides = new Map<string, boolean>();
  const checkboxHintsByField = getCheckboxHintsByField(checkboxHints);
  const explicitGroupKeys = new Set<string>();
  const groupValueApplied = new Set<string>();
  const clearedGroups = new Set<string>();
  const valueMapCache = new Map<Record<string, string>, Record<string, string>>();

  const markExplicitGroup = (groupKey: string) => {
    const normalizedGroup = normaliseDataKey(groupKey);
    if (normalizedGroup) explicitGroupKeys.add(normalizedGroup);
  };

  const markExplicitField = (fieldId: string) => {
    const meta = checkboxMetaById.get(fieldId);
    if (meta) markExplicitGroup(meta.groupKey);
  };

  const setCheckboxOverride = (
    groupKey: string,
    optionKey: string,
    value: boolean,
    markExplicit = false,
  ) => {
    const normalizedGroup = normaliseDataKey(groupKey);
    if (!normalizedGroup) return false;
    const group = checkboxGroups.get(normalizedGroup);
    if (!group) return false;
    const options = group.options.get(normaliseDataKey(optionKey));
    if (!options?.length) return false;
    for (const option of options) {
      checkboxOverrides.set(option.id, value);
    }
    if (markExplicit) markExplicitGroup(normalizedGroup);
    return true;
  };

  const clearCheckboxGroup = (groupKey: string) => {
    const normalizedGroup = normaliseDataKey(groupKey);
    if (!normalizedGroup || clearedGroups.has(normalizedGroup)) return;
    const group = checkboxGroups.get(normalizedGroup);
    if (!group) return;
    for (const options of group.options.values()) {
      for (const option of options) {
        checkboxOverrides.set(option.id, false);
      }
    }
    clearedGroups.add(normalizedGroup);
  };

  const setCheckboxOverrideByField = (field: PdfField, value: boolean, markExplicit = false) => {
    checkboxOverrides.set(field.id, value);
    if (markExplicit) markExplicitField(field.id);
  };

  const normalizeValueMap = (valueMap?: Record<string, string>): Record<string, string> | undefined => {
    if (!valueMap) return undefined;
    const cached = valueMapCache.get(valueMap);
    if (cached) return cached;
    const normalized = normalizeCheckboxValueMap(valueMap);
    if (normalized) valueMapCache.set(valueMap, normalized);
    return normalized;
  };

  const resolveOptionKey = (
    group: CheckboxGroup,
    rawValue: unknown,
    valueMap?: Record<string, string>,
  ): string | null => {
    const normalized = normaliseDataKey(String(rawValue ?? ''));
    if (!normalized) return null;
    const compact = compactCheckboxToken(normalized);
    if (valueMap) {
      const normalizedMap = normalizeValueMap(valueMap);
      const rawString = String(rawValue ?? '');
      const trimmedRaw = rawString.trim();
      const normalizedTrimmed = normaliseDataKey(trimmedRaw);
      const compactTrimmed = compactCheckboxToken(trimmedRaw);
      const mapped =
        normalizedMap?.[normalized] ??
        normalizedMap?.[compact] ??
        normalizedMap?.[normalizedTrimmed] ??
        normalizedMap?.[compactTrimmed] ??
        valueMap[rawString] ??
        valueMap[trimmedRaw] ??
        valueMap[normalized] ??
        valueMap[normalizedTrimmed];
      if (mapped !== undefined && mapped !== null && String(mapped).trim() !== '') {
        return normaliseDataKey(String(mapped));
      }
    }
    if (group.options.has(normalized)) return normalized;
    for (const [optionKey, aliases] of group.optionAliases.entries()) {
      for (const alias of aliases) {
        if (alias === normalized || compactCheckboxToken(alias) === compact) return optionKey;
      }
    }
    return null;
  };

  const resolveBooleanOptionKey = (group: CheckboxGroup, aliases: string[]): string | null => {
    for (const [optionKey, optionAliases] of group.optionAliases.entries()) {
      for (const alias of aliases) {
        if (optionAliases.has(alias)) return optionKey;
      }
    }
    return null;
  };

  const pickCheckboxValue = (
    groupKey: string,
    value: unknown,
    valueMap?: Record<string, string>,
  ): boolean => {
    const normalizedGroup = normaliseDataKey(groupKey);
    if (!normalizedGroup) return false;
    const group = checkboxGroups.get(normalizedGroup);
    if (!group) return false;
    const resolvedKey = resolveOptionKey(group, value, valueMap);
    if (!resolvedKey) return false;
    return setCheckboxOverride(normalizedGroup, resolvedKey, true);
  };

  const resolveCheckboxGroupValue = (
    groupKey: string,
    value: unknown,
    valueMap?: Record<string, string>,
  ): boolean => {
    const normalizedGroup = normaliseDataKey(groupKey);
    if (!normalizedGroup) return false;
    const group = checkboxGroups.get(normalizedGroup);
    if (!group) return false;
    const mappedOption = resolveOptionKey(group, value, valueMap);
    if (mappedOption) {
      clearCheckboxGroup(normalizedGroup);
      return setCheckboxOverride(normalizedGroup, mappedOption, true);
    }
    const normalizedValue = coerceCheckboxPresence(value);
    if (normalizedValue === null) return false;
    const yesKey = resolveBooleanOptionKey(group, CHECKBOX_TRUE_ALIASES);
    const noKey = resolveBooleanOptionKey(group, CHECKBOX_FALSE_ALIASES);
    if (yesKey && noKey) {
      clearCheckboxGroup(normalizedGroup);
      setCheckboxOverride(normalizedGroup, yesKey, normalizedValue);
      setCheckboxOverride(normalizedGroup, noKey, !normalizedValue);
      return true;
    }
    if (yesKey) {
      clearCheckboxGroup(normalizedGroup);
      return setCheckboxOverride(normalizedGroup, yesKey, normalizedValue);
    }
    if (noKey) {
      clearCheckboxGroup(normalizedGroup);
      return setCheckboxOverride(normalizedGroup, noKey, !normalizedValue);
    }
    if (!normalizedValue) return false;
    const fallbackOption = Array.from(group.options.keys())[0];
    if (fallbackOption) {
      clearCheckboxGroup(normalizedGroup);
      return setCheckboxOverride(normalizedGroup, fallbackOption, true);
    }
    return false;
  };

  const applyDirectCheckboxMatch = (key: string, value: unknown): boolean => {
    const matches = checkboxNameIndex.get(key);
    if (!matches?.length) return false;
    const normalizedValue = coerceCheckboxBoolean(value);
    if (normalizedValue === null) return false;
    for (const field of matches) {
      setCheckboxOverrideByField(field, normalizedValue, true);
    }
    return true;
  };

  const applyOptionKey = (key: string, value: unknown): boolean => {
    if (!key || checkboxOptionConflicts.has(key)) return false;
    const match = checkboxOptionIndex.get(key);
    if (!match) return false;
    const normalizedValue = coerceCheckboxBoolean(value);
    if (normalizedValue === null) return false;
    return setCheckboxOverride(match.groupKey, match.optionKey, normalizedValue, true);
  };

  const applyGroupValue = (
    groupKey: string,
    value: unknown,
    valueMap?: Record<string, string>,
    allowBoolean = true,
    mode: 'list' | 'enum' = 'list',
  ) => {
    const normalizedGroup = normaliseDataKey(groupKey);
    if (!normalizedGroup) return;
    if (explicitGroupKeys.has(normalizedGroup) || groupValueApplied.has(normalizedGroup)) return;
    if (!checkboxGroups.has(normalizedGroup)) return;
    if (allowBoolean) {
      const directBoolean = coerceCheckboxBoolean(value);
      if (directBoolean !== null) {
        if (resolveCheckboxGroupValue(normalizedGroup, directBoolean, valueMap)) {
          groupValueApplied.add(normalizedGroup);
        }
        return;
      }
    }
    const entries = splitCheckboxListValue(value);
    if (!entries.length) return;
    clearCheckboxGroup(normalizedGroup);
    if (mode === 'enum') {
      for (const entry of entries) {
        if (pickCheckboxValue(normalizedGroup, entry, valueMap)) {
          groupValueApplied.add(normalizedGroup);
          return;
        }
        if (resolveCheckboxGroupValue(normalizedGroup, entry, valueMap)) {
          groupValueApplied.add(normalizedGroup);
          return;
        }
      }
      return;
    }
    let applied = false;
    for (const entry of entries) {
      if (pickCheckboxValue(normalizedGroup, entry, valueMap)) {
        applied = true;
      }
    }
    if (!applied && entries.length === 1) {
      applied = resolveCheckboxGroupValue(normalizedGroup, entries[0], valueMap);
    }
    if (applied) groupValueApplied.add(normalizedGroup);
  };

  const applyHintedBooleanGroup = (hint: CheckboxHint, value: unknown): boolean => {
    if (!hint?.directBooleanPossible) return false;
    const normalizedGroup = normaliseDataKey(hint.groupKey || '');
    if (!normalizedGroup) return false;
    if (explicitGroupKeys.has(normalizedGroup) || groupValueApplied.has(normalizedGroup)) return false;
    if (!checkboxGroups.has(normalizedGroup)) return false;
    const normalizedValue = coerceCheckboxBoolean(value);
    if (normalizedValue === null) return false;
    clearCheckboxGroup(normalizedGroup);
    const applied = resolveCheckboxGroupValue(normalizedGroup, normalizedValue);
    if (applied) {
      explicitGroupKeys.add(normalizedGroup);
      groupValueApplied.add(normalizedGroup);
    }
    return applied;
  };

  const getRowValueForKey = (key: string): unknown => {
    const normalizedKey = normaliseDataKey(key);
    if (!normalizedKey) return undefined;
    const candidates = new Set<string>([
      normalizedKey,
      `patient_${normalizedKey}`,
      `responsible_party_${normalizedKey}`,
    ]);
    if (normalizedKey.startsWith('patient_')) {
      candidates.add(normalizedKey.slice('patient_'.length));
    }
    if (normalizedKey.startsWith('responsible_party_')) {
      candidates.add(normalizedKey.slice('responsible_party_'.length));
    }
    for (const candidate of candidates) {
      if (!candidate) continue;
      if (normalizedRow.has(candidate)) return normalizedRow.get(candidate);
    }
    return undefined;
  };

  const textTransformRulesByTarget = getTextTransformRulesByTarget(textTransformRules);

  const resolveTransformRuleValue = (rule: TextTransformRule): unknown => {
    const operation = rule.operation || 'copy';
    const sources = Array.isArray(rule.sources) ? rule.sources : [];
    if (!sources.length) return undefined;
    const sourceValues = sources.map((source) => getRowValueForKey(source));
    const sourceAsStrings = sourceValues.map((value) =>
      value === null || value === undefined ? '' : String(value).trim(),
    );

    if (operation === 'copy') {
      return sourceValues[0];
    }

    if (operation === 'concat') {
      const separator = rule.separator ?? ' ';
      const parts = sourceAsStrings.filter((value) => value.length > 0);
      if (!parts.length) return undefined;
      return parts.join(separator);
    }

    if (operation === 'split_name_first_rest') {
      const source = sourceAsStrings[0];
      if (!source) return undefined;
      const tokens = source.split(/\s+/).filter(Boolean);
      if (!tokens.length) return undefined;
      if (rule.part === 'first') return tokens[0];
      const rest = tokens.slice(1).join(' ');
      return rest || tokens[0];
    }

    if (operation === 'split_delimiter') {
      const source = sourceAsStrings[0];
      if (!source) return undefined;
      const delimiter = rule.delimiter || rule.separator;
      if (!delimiter) return undefined;
      const entries = source.split(delimiter).map((entry) => entry.trim());
      if (!entries.length) return undefined;
      if (typeof rule.index === 'number') {
        return entries[rule.index];
      }
      if (rule.part === 'first') return entries[0];
      if (rule.part === 'last') return entries[entries.length - 1];
      if (rule.part === 'rest') {
        const rest = entries.slice(1).join(' ').trim();
        return rest || entries[0];
      }
    }

    return undefined;
  };

  const resolveTextTransformValue = (normalizedTarget: string): unknown => {
    const rules = textTransformRulesByTarget.get(normalizedTarget);
    if (!rules?.length) return undefined;
    for (const rule of rules) {
      const value = resolveTransformRuleValue(rule);
      if (value === undefined || value === null) continue;
      if (typeof value === 'string' && !value.trim()) continue;
      return value;
    }
    return undefined;
  };

  for (const [key, value] of normalizedRow) {
    applyDirectCheckboxMatch(key, value);
  }

  for (const [key, value] of normalizedRow) {
    const strippedKey = key.startsWith('i_')
      ? key.slice(2)
      : key.startsWith('checkbox_')
        ? key.replace(/^checkbox_/, '')
        : key;
    if (!strippedKey) continue;
    applyOptionKey(strippedKey, value);
  }

  for (const [key, value] of normalizedRow) {
    if (key.startsWith('i_')) {
      const stripped = key.slice(2);
      if (!stripped) continue;
      applyGroupValue(stripped, value);
      continue;
    }
    if (key.startsWith('checkbox_')) {
      const stripped = key.replace(/^checkbox_/, '');
      if (!stripped) continue;
      applyGroupValue(stripped, value);
    }
  }

  for (const [key, value] of normalizedRow) {
    if (key.startsWith('i_') || key.startsWith('checkbox_')) continue;
    if (!checkboxGroups.has(key)) continue;
    applyGroupValue(key, value);
  }

  const ruleAppliedGroups = new Set<string>();
  for (const checkboxRule of checkboxRules ?? []) {
    const ruleKeyRaw =
      (checkboxRule as { databaseField?: string }).databaseField ??
      (checkboxRule as { key?: string }).key ??
      '';
    const ruleKey = normaliseDataKey(ruleKeyRaw);
    if (!ruleKey) continue;
    const rawValue = getRowValueForKey(ruleKey);
    if (rawValue === undefined) continue;
    const groupKey = normaliseDataKey(checkboxRule.groupKey);
    if (!groupKey) continue;
    if (explicitGroupKeys.has(groupKey) || groupValueApplied.has(groupKey)) continue;
    const operation = checkboxRule.operation || 'yes_no';
    const legacyTruthy = (checkboxRule as { truthyValue?: string }).truthyValue;
    const legacyFalsey = (checkboxRule as { falseyValue?: string }).falseyValue;
    if (operation === 'yes_no' || operation === 'presence') {
      const normalized = coerceCheckboxPresence(rawValue);
      if (normalized === null) continue;
      const trueOption = checkboxRule.trueOption ?? legacyTruthy;
      const falseOption = checkboxRule.falseOption ?? legacyFalsey;
      let applied = false;
      if (normalized) {
        if (trueOption) {
          clearCheckboxGroup(groupKey);
          applied = setCheckboxOverride(groupKey, trueOption, true);
        }
      } else if (falseOption) {
        clearCheckboxGroup(groupKey);
        applied = setCheckboxOverride(groupKey, falseOption, true);
      }
      if (!applied && operation === 'yes_no') {
        applied = resolveCheckboxGroupValue(groupKey, normalized, checkboxRule.valueMap);
      } else if (!applied && operation === 'presence' && normalized) {
        applied = resolveCheckboxGroupValue(groupKey, true, checkboxRule.valueMap);
      }
      if (applied) ruleAppliedGroups.add(groupKey);
      continue;
    }
    if (operation === 'list') {
      applyGroupValue(groupKey, rawValue, checkboxRule.valueMap, false, 'list');
      continue;
    }
    if (operation === 'enum') {
      applyGroupValue(groupKey, rawValue, checkboxRule.valueMap, false, 'enum');
    }
  }
  for (const key of ruleAppliedGroups) groupValueApplied.add(key);

  for (const [key, hint] of checkboxHintsByField.entries()) {
    const rowValue = getRowValueForKey(key);
    if (rowValue === undefined) continue;
    applyHintedBooleanGroup(hint, rowValue);
  }

  for (const [groupKey, aliases] of Object.entries(CHECKBOX_ALIASES)) {
    if (explicitGroupKeys.has(normaliseDataKey(groupKey)) || groupValueApplied.has(normaliseDataKey(groupKey))) {
      continue;
    }
    if (!normalizedRow.has(groupKey)) {
      for (const alias of aliases) {
        if (normalizedRow.has(alias)) {
          applyGroupValue(groupKey, normalizedRow.get(alias));
          break;
        }
      }
      continue;
    }
    applyGroupValue(groupKey, normalizedRow.get(groupKey));
  }

  const resolveValueForField = (field: PdfField): unknown => {
    if (field.type === 'checkbox') {
      if (checkboxOverrides.has(field.id)) {
        return checkboxOverrides.get(field.id);
      }
      return undefined;
    }

    const normalizedName = normaliseDataKey(field.name || '');
    if (!normalizedName) return undefined;

    if (normalizedRow.has(normalizedName)) {
      return normalizedRow.get(normalizedName);
    }

    if (normalizedRow.has(`patient_${normalizedName}`)) {
      return normalizedRow.get(`patient_${normalizedName}`);
    }

    if (normalizedRow.has(`responsible_party_${normalizedName}`)) {
      return normalizedRow.get(`responsible_party_${normalizedName}`);
    }

    const textTransformValue = resolveTextTransformValue(normalizedName);
    if (textTransformValue !== undefined) {
      return textTransformValue;
    }

    if (normalizedName.endsWith('_1')) {
      const base = normalizedName.replace(/_1$/, '');
      if (normalizedRow.has(base)) return normalizedRow.get(base);
    }

    const allergies = normalizedRow.get('allergies');
    if (allergies !== undefined && normalizedName.startsWith('allergy_')) {
      const entries = splitCheckboxListValue(allergies);
      const index = Number(normalizedName.replace('allergy_', '')) - 1;
      if (!Number.isNaN(index) && entries[index]) return entries[index];
    }

    const medications = normalizedRow.get('medications');
    if (medications !== undefined && normalizedName.startsWith('medication_')) {
      const entries = splitCheckboxListValue(medications);
      const index = Number(normalizedName.replace('medication_', '')) - 1;
      if (!Number.isNaN(index) && entries[index]) return entries[index];
    }

    const diagnoses = normalizedRow.get('diagnoses');
    if (diagnoses !== undefined && normalizedName.startsWith('diagnosis_')) {
      const entries = splitCheckboxListValue(diagnoses);
      const index = Number(normalizedName.replace('diagnosis_', '')) - 1;
      if (!Number.isNaN(index) && entries[index]) return entries[index];
    }

    if (normalizedName.endsWith('_street_address')) {
      const base = normalizedName.replace('_street_address', '');
      const street = normalizedRow.get(`${base}_street`) ?? normalizedRow.get(`${base}_address`);
      if (street !== undefined) return street;
    }

    if (normalizedName.endsWith('_address')) {
      const base = normalizedName.replace('_address', '');
      const address = normalizedRow.get(`${base}_street_address`) ?? normalizedRow.get(`${base}_street`);
      if (address !== undefined) return address;
    }

    if (normalizedName === 'city_state_zip') {
      const city = normalizedRow.get('city');
      const state = normalizedRow.get('state');
      const zip = normalizedRow.get('zip');
      const locality = [city, state, zip].filter(Boolean);
      if (locality.length) return locality.join(', ');
    }

    const suffixBase = getNumericSuffixBase(normalizedName);
    if (suffixBase) {
      const baseValue = normalizedRow.get(suffixBase);
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

  return fields.map((field) => {
    const matchValue = resolveValueForField(field);
    if (matchValue === undefined) {
      if (dataSourceKind !== 'respondent') return field;
      if (field.value === null || field.value === undefined) return field;
      return { ...field, value: null };
    }
    if (field.type === 'date') {
      const dateValue = formatDateValue(matchValue);
      if (dateValue === null) return field;
      return { ...field, value: dateValue };
    }
    return { ...field, value: coerceValue(matchValue) };
  });
}
