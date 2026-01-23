/**
 * Search & Fill modal for populating fields from data sources.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CheckboxRule, PdfField } from '../../types';
import type { DataSourceKind } from '../layout/HeaderBar';
import './SearchFillModal.css';
import { normaliseDataKey } from '../../utils/dataSource';
import { Alert } from '../ui/Alert';

type SearchMode = 'contains' | 'equals';

type SearchFillModalProps = {
  open: boolean;
  onClose: () => void;
  sessionId?: number;
  dataSourceKind: DataSourceKind;
  dataSourceLabel: string | null;
  columns: string[];
  identifierKey: string | null;
  rows: Array<Record<string, unknown>>;
  fields: PdfField[];
  checkboxRules?: CheckboxRule[];
  onFieldsChange: (next: PdfField[]) => void;
  onClearFields: () => void;
  onAfterFill: () => void;
  onError: (message: string) => void;
  onRequestDataSource?: (kind: 'csv' | 'excel' | 'json') => void;
  demoSearch?: {
    query: string;
    searchKey?: string;
    searchMode?: SearchMode;
    autoRun?: boolean;
    autoFillOnSearch?: boolean;
    highlightResult?: boolean;
    token?: number;
  } | null;
};

// Known alias sets help map checkbox fields to multiple schema variants.
const CHECKBOX_ALIASES: Record<string, string[]> = {
  allergies: ['allergy', 'has_allergies'],
  drug_use: ['substance_use', 'illicit_drug_use', 'has_drug_use'],
  alcohol_use: ['drinks_alcohol', 'etoh_use', 'has_alcohol_use'],
  tobacco_use: ['smoking', 'smoker', 'smoking_status', 'has_tobacco_use'],
  pregnant: ['pregnancy', 'pregnancy_status', 'is_pregnant'],
  medications: ['current_medications', 'takes_medications'],
};

function coerceValue(value: unknown): string | number | boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value);
}

function coerceBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const norm = value.trim().toLowerCase();
    if (['true', '1', 'yes', 'y', 'on', 'checked', 't'].includes(norm)) return true;
    if (['false', '0', 'no', 'n', 'off', 'unchecked', 'f'].includes(norm)) return false;
  }
  return null;
}

function parseDateFromUnknown(value: unknown): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === 'string') {
    const match = value.match(/\d{4}-\d{2}-\d{2}/);
    if (!match) return null;
    const parsed = new Date(`${match[0]}T00:00:00Z`);
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

type CheckboxGroup = {
  options: Map<string, PdfField>;
  optionAliases: Map<string, Set<string>>;
};

/**
 * Resolve checkbox group/option keys from metadata or naming.
 */
function resolveCheckboxMeta(field: PdfField): { groupKey: string; optionKey: string; optionLabel?: string } | null {
  if (field.type !== 'checkbox') return null;
  const optionLabel = typeof field.optionLabel === 'string' ? field.optionLabel : undefined;
  const storedGroup = field.groupKey ? normaliseDataKey(field.groupKey) : '';
  const storedOption = field.optionKey ? normaliseDataKey(field.optionKey) : '';
  if (storedGroup && storedOption) {
    return { groupKey: storedGroup, optionKey: storedOption, optionLabel };
  }

  const normalizedName = normaliseDataKey(field.name || '');
  const base = normalizedName.startsWith('i_') ? normalizedName.slice(2) : normalizedName;
  if (!base) return null;

  const optionFromLabel = optionLabel ? normaliseDataKey(optionLabel) : '';
  if (optionFromLabel && base.endsWith(`_${optionFromLabel}`)) {
    return {
      groupKey: base.slice(0, -(optionFromLabel.length + 1)),
      optionKey: optionFromLabel,
      optionLabel,
    };
  }

  const lastUnderscore = base.lastIndexOf('_');
  if (lastUnderscore > 0) {
    return {
      groupKey: base.slice(0, lastUnderscore),
      optionKey: base.slice(lastUnderscore + 1),
      optionLabel,
    };
  }

  return { groupKey: base, optionKey: 'yes', optionLabel };
}

/**
 * Build checkbox groups keyed by groupKey for faster rule application.
 */
function buildCheckboxGroups(fields: PdfField[]): Map<string, CheckboxGroup> {
  const groups = new Map<string, CheckboxGroup>();
  for (const field of fields) {
    if (field.type !== 'checkbox') continue;
    const meta = resolveCheckboxMeta(field);
    if (!meta) continue;
    const groupKey = meta.groupKey;
    const optionKey = meta.optionKey;
    const group = groups.get(groupKey) || { options: new Map(), optionAliases: new Map() };
    group.options.set(optionKey, field);
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

function splitListValue(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry).trim()).filter(Boolean);
  }
  if (typeof value !== 'string') return [String(value)];
  return value
    .split(/[,;|/]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

/**
 * Build a concise preview label for search results.
 */
function rowPreview(row: Record<string, unknown>, identifierKey: string | null): { title: string; subtitle: string } {
  const get = (key: string) => {
    const foundKey = Object.keys(row).find((candidate) => candidate.toLowerCase() === key.toLowerCase());
    return foundKey ? row[foundKey] : undefined;
  };
  const mrn = identifierKey ? row[identifierKey] : get('mrn');
  const fullName = get('full_name');
  const first = get('first_name');
  const last = get('last_name');
  const dob = get('dob') ?? get('date_of_birth');
  const titleParts = [];
  if (mrn) titleParts.push(String(mrn));
  if (fullName) titleParts.push(String(fullName));
  else if (first || last) titleParts.push([first, last].filter(Boolean).join(' '));
  const title = titleParts.join(' • ') || 'Record';
  const subtitleParts = [];
  if (dob) subtitleParts.push(`DOB ${String(dob)}`);
  const phone = get('phone') ?? get('mobile_phone') ?? get('home_phone');
  if (phone) subtitleParts.push(String(phone));
  const email = get('email') ?? get('email_address');
  if (email) subtitleParts.push(String(email));
  return { title, subtitle: subtitleParts.join(' • ') };
}

/**
 * Render the Search & Fill modal and apply data to fields.
 */
export default function SearchFillModal({
  open,
  onClose,
  sessionId,
  dataSourceKind,
  dataSourceLabel,
  columns,
  identifierKey,
  rows,
  fields,
  checkboxRules,
  onFieldsChange,
  onClearFields,
  onAfterFill,
  onError,
  onRequestDataSource,
  demoSearch,
}: SearchFillModalProps) {
  const [searchKey, setSearchKey] = useState<string>('');
  const [searchMode, setSearchMode] = useState<SearchMode>('contains');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Array<Record<string, unknown>>>([]);
  const [searching, setSearching] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const canSearchAnyColumn = true;
  const hasRows = rows.length > 0;
  const hasSource = dataSourceKind !== 'none';
  const canRequestSource = Boolean(onRequestDataSource);

  const availableKeys = useMemo(() => {
    const unique = new Set(columns.filter(Boolean));
    return Array.from(unique);
  }, [columns]);

  /**
   * Apply a selected row to all fields, including checkbox rules.
   */
  const handleFill = useCallback(
    async (row: Record<string, unknown>) => {
      setLocalError(null);

      const normalizedRow = new Map<string, unknown>();
      for (const [key, value] of Object.entries(row)) {
        normalizedRow.set(normaliseDataKey(key), value);
      }
      const normalizedRowKeys = Array.from(normalizedRow.keys());
      const checkboxGroups = buildCheckboxGroups(fields);
      const checkboxOverrides = new Map<string, boolean>();
      const checkboxMetaById = new Map<string, { groupKey: string; optionKey: string }>();
      const checkboxNameIndex = new Map<string, PdfField[]>();
      const checkboxOptionIndex = new Map<string, { groupKey: string; optionKey: string }>();
      const checkboxOptionConflicts = new Set<string>();
      const explicitGroupKeys = new Set<string>();
      const groupValueApplied = new Set<string>();
      const presenceFalseTokens = new Set(['', 'n/a', 'na', 'none', 'unknown', 'unsure']);

      for (const field of fields) {
        if (field.type !== 'checkbox') continue;
        const meta = resolveCheckboxMeta(field);
        if (meta) {
          checkboxMetaById.set(field.id, { groupKey: meta.groupKey, optionKey: meta.optionKey });
        }
        const normalizedName = normaliseDataKey(field.name || '');
        if (!normalizedName) continue;
        const existing = checkboxNameIndex.get(normalizedName);
        if (existing) {
          existing.push(field);
        } else {
          checkboxNameIndex.set(normalizedName, [field]);
        }
      }

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
        const option = group.options.get(normaliseDataKey(optionKey));
        if (!option) return false;
        checkboxOverrides.set(option.id, value);
        if (markExplicit) markExplicitGroup(normalizedGroup);
        return true;
      };

      const setCheckboxOverrideByField = (field: PdfField, value: boolean, markExplicit = false) => {
        checkboxOverrides.set(field.id, value);
        if (markExplicit) markExplicitField(field.id);
      };

      const coerceBooleanWithPresence = (value: unknown): boolean | null => {
        const direct = coerceBoolean(value);
        if (direct !== null) return direct;
        if (value === null || value === undefined) return null;
        if (typeof value === 'string') {
          const norm = value.trim().toLowerCase();
          if (!norm) return null;
          if (presenceFalseTokens.has(norm)) return false;
          return true;
        }
        if (typeof value === 'number') return value !== 0;
        if (Array.isArray(value)) return value.length > 0;
        return true;
      };

      const resolveOptionKey = (
        group: CheckboxGroup,
        rawValue: unknown,
        valueMap?: Record<string, string>,
      ): string | null => {
        const normalized = normaliseDataKey(String(rawValue ?? ''));
        if (!normalized) return null;
        if (valueMap) {
          const mapped =
            valueMap[normalized] ??
            valueMap[String(rawValue ?? '')] ??
            valueMap[normaliseDataKey(String(rawValue ?? '').trim())];
          if (mapped) return normaliseDataKey(mapped);
        }
        if (group.options.has(normalized)) return normalized;
        for (const [optionKey, aliases] of group.optionAliases.entries()) {
          if (aliases.has(normalized)) return optionKey;
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
        const normalizedValue = coerceBooleanWithPresence(value);
        if (normalizedValue === null) return false;
        const yesKey = group.options.has('yes')
          ? 'yes'
          : group.options.has('true')
            ? 'true'
            : group.options.has('y')
              ? 'y'
              : null;
        const noKey = group.options.has('no')
          ? 'no'
          : group.options.has('false')
            ? 'false'
            : group.options.has('n')
              ? 'n'
              : null;
        if (yesKey && noKey) {
          setCheckboxOverride(normalizedGroup, yesKey, normalizedValue);
          setCheckboxOverride(normalizedGroup, noKey, !normalizedValue);
          return true;
        }
        if (yesKey) {
          return setCheckboxOverride(normalizedGroup, yesKey, normalizedValue);
        }
        if (noKey) {
          return setCheckboxOverride(normalizedGroup, noKey, !normalizedValue);
        }
        const optionKey = normalizedValue ? 'yes' : 'no';
        if (group.options.has(optionKey)) {
          return setCheckboxOverride(normalizedGroup, optionKey, true);
        }
        if (!normalizedValue) return false;
        const fallbackOption = Array.from(group.options.keys())[0];
        if (fallbackOption) {
          return setCheckboxOverride(normalizedGroup, fallbackOption, true);
        }
        return false;
      };

      const applyDirectCheckboxMatch = (key: string, value: unknown): boolean => {
        const matches = checkboxNameIndex.get(key);
        if (!matches?.length) return false;
        const normalizedValue = coerceBooleanWithPresence(value);
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
        const normalizedValue = coerceBooleanWithPresence(value);
        if (normalizedValue === null) return false;
        return setCheckboxOverride(match.groupKey, match.optionKey, normalizedValue, true);
      };

      const applyGroupValue = (
        groupKey: string,
        value: unknown,
        valueMap?: Record<string, string>,
        allowBoolean = true,
      ) => {
        const normalizedGroup = normaliseDataKey(groupKey);
        if (!normalizedGroup) return;
        if (explicitGroupKeys.has(normalizedGroup) || groupValueApplied.has(normalizedGroup)) return;
        if (!checkboxGroups.has(normalizedGroup)) return;
        if (allowBoolean) {
          const directBoolean = coerceBoolean(value);
          if (directBoolean !== null) {
            if (resolveCheckboxGroupValue(normalizedGroup, directBoolean, valueMap)) {
              groupValueApplied.add(normalizedGroup);
            }
            return;
          }
        }
        const entries = splitListValue(value);
        if (!entries.length) return;
        let applied = false;
        for (const entry of entries) {
          if (pickCheckboxValue(normalizedGroup, entry, valueMap)) {
            applied = true;
          }
        }
        if (applied) groupValueApplied.add(normalizedGroup);
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

      for (const checkboxRule of checkboxRules ?? []) {
        const ruleKeyRaw =
          (checkboxRule as { databaseField?: string }).databaseField ??
          (checkboxRule as { key?: string }).key ??
          '';
        const ruleKey = normaliseDataKey(ruleKeyRaw);
        if (!ruleKey) continue;
        if (!normalizedRow.has(ruleKey)) continue;
        const groupKey = normaliseDataKey(checkboxRule.groupKey);
        if (!groupKey) continue;
        if (explicitGroupKeys.has(groupKey) || groupValueApplied.has(groupKey)) continue;
        const rawValue = normalizedRow.get(ruleKey);
        const operation = checkboxRule.operation || 'yes_no';
        const legacyTruthy = (checkboxRule as { truthyValue?: string }).truthyValue;
        const legacyFalsey = (checkboxRule as { falseyValue?: string }).falseyValue;
        if (operation === 'yes_no' || operation === 'presence') {
          const normalized = coerceBooleanWithPresence(rawValue);
          if (normalized === null) continue;
          const trueOption = checkboxRule.trueOption ?? legacyTruthy;
          const falseOption = checkboxRule.falseOption ?? legacyFalsey;
          let applied = false;
          if (normalized) {
            if (trueOption) {
              applied = setCheckboxOverride(groupKey, trueOption, true);
            }
          } else if (falseOption) {
            applied = setCheckboxOverride(groupKey, falseOption, true);
          }
          if (!applied && operation === 'yes_no') {
            applied = resolveCheckboxGroupValue(groupKey, normalized, checkboxRule.valueMap);
          } else if (!applied && operation === 'presence' && normalized) {
            applied = resolveCheckboxGroupValue(groupKey, true, checkboxRule.valueMap);
          }
          if (applied) groupValueApplied.add(groupKey);
          continue;
        }
        if (operation === 'list') {
          applyGroupValue(groupKey, rawValue, checkboxRule.valueMap, false);
          continue;
        }
        if (operation === 'enum') {
          applyGroupValue(groupKey, rawValue, checkboxRule.valueMap, false);
        }
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

      const fillCheckboxValues = new Set(checkboxOverrides.keys());

      const resolveValueForField = (field: PdfField): unknown => {
        if (field.type === 'checkbox') {
          if (checkboxOverrides.has(field.id)) {
            return checkboxOverrides.get(field.id);
          }
          if (fillCheckboxValues.has(field.id)) {
            return true;
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

        if (normalizedName.endsWith('_date') || normalizedName.includes('date')) {
          const value = normalizedRow.get(normalizedName);
          if (value !== undefined) return value;
        }

        if (normalizedName.endsWith('_phone')) {
          const value = normalizedRow.get(normalizedName);
          if (value !== undefined) return value;
        }

        if (normalizedName.endsWith('_name')) {
          const value = normalizedRow.get(normalizedName);
          if (value !== undefined) return value;
        }

        if (normalizedRowKeys.includes(normalizedName)) {
          return normalizedRow.get(normalizedName);
        }

        if (normalizedName.endsWith('_1')) {
          const base = normalizedName.replace(/_1$/, '');
          if (normalizedRow.has(base)) return normalizedRow.get(base);
        }

        const allergies = normalizedRow.get('allergies');
        if (allergies !== undefined && normalizedName.startsWith('allergy_')) {
          const entries = splitListValue(allergies);
          const index = Number(normalizedName.replace('allergy_', '')) - 1;
          if (!Number.isNaN(index) && entries[index]) return entries[index];
        }

        const medications = normalizedRow.get('medications');
        if (medications !== undefined && normalizedName.startsWith('medication_')) {
          const entries = splitListValue(medications);
          const index = Number(normalizedName.replace('medication_', '')) - 1;
          if (!Number.isNaN(index) && entries[index]) return entries[index];
        }

        const diagnoses = normalizedRow.get('diagnoses');
        if (diagnoses !== undefined && normalizedName.startsWith('diagnosis_')) {
          const entries = splitListValue(diagnoses);
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

        const suffixMatch = normalizedName.match(/^(.*)_\\d+$/);
        if (suffixMatch) {
          const base = suffixMatch[1];
          const baseValue = normalizedRow.get(base);
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

      const nextFields = fields.map((field) => {
        const matchValue = resolveValueForField(field);
        if (matchValue === undefined) return field;
        if (field.type === 'date') {
          const dateValue = formatDateValue(matchValue);
          if (dateValue === null) return field;
          return { ...field, value: dateValue };
        }
        return { ...field, value: coerceValue(matchValue) };
      });

      onFieldsChange(nextFields);
      try {
        onAfterFill();
        onClose();
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to fill PDF.';
        onError(message);
        setLocalError(message);
      }
    },
    [
      checkboxRules,
      fields,
      onAfterFill,
      onClose,
      onError,
      onFieldsChange,
    ],
  );

  /**
   * Execute a search against local rows.
   */
  const executeSearch = useCallback(
    async ({
      queryValue,
      searchKeyValue,
      searchModeValue,
    }: {
      queryValue: string;
      searchKeyValue: string;
      searchModeValue: SearchMode;
    }) => {
      if (!hasSource) {
        setLocalError('Choose a CSV, Excel, or JSON source first.');
        return;
      }
      if (!hasRows) {
        setLocalError('No record rows are available to search.');
        return;
      }
      if (!queryValue) {
        setLocalError('Enter a search value.');
        return;
      }
      if (!searchKeyValue || (!canSearchAnyColumn && searchKeyValue === '__any__')) {
        setLocalError('Choose a column to search.');
        return;
      }

      setLocalError(null);
      setHasSearched(true);
      setSearching(true);
      setResults([]);
      try {
        const q = queryValue.toLowerCase();
        const matches = (value: string) => (searchModeValue === 'equals' ? value === q : value.includes(q));
        const matched: Array<Record<string, unknown>> = [];
        for (const row of rows) {
          if (searchKeyValue === '__any__') {
            const keys = availableKeys.length ? availableKeys : Object.keys(row);
            const ok = keys.some((key) => matches(String(row[key] ?? '').toLowerCase()));
            if (!ok) continue;
          } else {
            const value = String(row[searchKeyValue] ?? '').toLowerCase();
            if (!matches(value)) continue;
          }
          matched.push(row);
          if (matched.length >= 25) break;
        }
        if (demoSearch?.autoFillOnSearch && matched.length > 0) {
          await handleFill(matched[0]);
          return;
        }
        setResults(matched);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Search failed.';
        setLocalError(message);
      } finally {
        setSearching(false);
      }
    },
    [availableKeys, canSearchAnyColumn, demoSearch?.autoFillOnSearch, handleFill, hasRows, hasSource, rows],
  );

  const runSearch = useCallback(
    async (override?: { query?: string; searchKey?: string; searchMode?: SearchMode }) => {
      const queryValue = (override?.query ?? query).trim();
      const searchKeyValue = override?.searchKey ?? searchKey;
      const searchModeValue = override?.searchMode ?? searchMode;
      await executeSearch({ queryValue, searchKeyValue, searchModeValue });
    },
    [executeSearch, query, searchKey, searchMode],
  );

  useEffect(() => {
    if (!open) return;
    const defaultKey = identifierKey || availableKeys[0] || '';
    const presetKey = demoSearch?.searchKey ?? defaultKey;
    const presetMode = demoSearch?.searchMode ?? 'contains';
    const presetQuery = demoSearch?.query ?? '';
    setSearchKey(presetKey);
    setQuery(presetQuery);
    setResults([]);
    setSearching(false);
    setLocalError(null);
    setSearchMode(presetMode);
    setHasSearched(false);
    if (demoSearch?.autoRun && presetQuery) {
      void executeSearch({
        queryValue: presetQuery.trim(),
        searchKeyValue: presetKey,
        searchModeValue: presetMode,
      });
    }
  }, [availableKeys, demoSearch?.token, demoSearch?.autoRun, demoSearch?.query, demoSearch?.searchKey, demoSearch?.searchMode, executeSearch, identifierKey, open, sessionId]);

  const canClearFields = useMemo(
    () =>
      fields.some((field) => {
        const value = field.value;
        if (value === null || value === undefined) return false;
        if (typeof value === 'string') return value.trim().length > 0;
        if (typeof value === 'boolean') return value;
        return true;
      }),
    [fields],
  );

  const handleClear = useCallback(() => {
    onClearFields();
    setLocalError(null);
  }, [onClearFields]);

  if (!open) return null;

  return (
    <div className="searchfill-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="searchfill-modal__card" onClick={(event) => event.stopPropagation()}>
        <div className="searchfill-modal__header">
          <div>
            <h2 className="searchfill-modal__title">Search, Fill &amp; Clear</h2>
            <p className="searchfill-modal__subtitle">
              Find a record locally and populate the current PDF.
            </p>
          </div>
          <button
            className="searchfill-modal__close"
            onClick={onClose}
            type="button"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="searchfill-modal__body">
          <div className="searchfill-meta">
            <div className="searchfill-source">
              <span className="searchfill-source__label">Source</span>
              <span className="searchfill-source__value">
                {dataSourceLabel || (dataSourceKind === 'none' ? 'None selected' : dataSourceKind.toUpperCase())}
              </span>
            </div>
            <div className="searchfill-source">
              <span className="searchfill-source__label">Records</span>
              <span className="searchfill-source__value">{rows.length}</span>
            </div>
          </div>

          {!hasRows ? (
            <div className="searchfill-alert searchfill-alert--empty">
              <Alert
                tone="info"
                variant="inline"
                size="sm"
                message={
                  hasSource
                    ? 'The connected source has no record rows to search.'
                    : 'No record rows are loaded yet. Upload a CSV, Excel, or JSON file to search and fill.'
                }
              />
              {canRequestSource ? (
                <div className="searchfill-actions searchfill-actions--empty">
                  <button
                    type="button"
                    className="ui-button ui-button--ghost ui-button--compact"
                    onClick={() => onRequestDataSource?.('csv')}
                  >
                    Upload CSV
                  </button>
                  <button
                    type="button"
                    className="ui-button ui-button--ghost ui-button--compact"
                    onClick={() => onRequestDataSource?.('excel')}
                  >
                    Upload Excel
                  </button>
                  <button
                    type="button"
                    className="ui-button ui-button--ghost ui-button--compact"
                    onClick={() => onRequestDataSource?.('json')}
                  >
                    Upload JSON
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="searchfill-controls">
            <div className="searchfill-field">
              <label className="searchfill-label" htmlFor="searchfill-key">
                Column
              </label>
              <select
                id="searchfill-key"
                value={searchKey}
                onChange={(event) => setSearchKey(event.target.value)}
                disabled={!hasRows || searching}
              >
                {canSearchAnyColumn ? (
                  <option value="__any__">Any column</option>
                ) : null}
                {availableKeys.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>

            <div className="searchfill-field">
              <label className="searchfill-label" htmlFor="searchfill-mode">
                Match
              </label>
              <select
                id="searchfill-mode"
                value={searchMode}
                onChange={(event) => setSearchMode(event.target.value as SearchMode)}
                disabled={!hasRows || searching}
              >
                <option value="contains">Contains</option>
                <option value="equals">Equals</option>
              </select>
            </div>

            <div className="searchfill-field searchfill-field--grow">
              <label className="searchfill-label" htmlFor="searchfill-query">
                Search
              </label>
              <input
                id="searchfill-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="MRN, name, etc."
                disabled={!hasRows || searching}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void runSearch();
                  }
                }}
              />
            </div>

            <div className="searchfill-actions">
              <button
                type="button"
                className="ui-button ui-button--primary ui-button--compact"
                data-demo-target={demoSearch?.autoFillOnSearch ? 'search-fill-search' : undefined}
                onClick={() => void runSearch()}
                disabled={!hasRows || searching}
              >
                {searching ? 'Searching…' : 'Search'}
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={handleClear}
                disabled={!canClearFields || searching}
              >
                Clear inputs
              </button>
            </div>
          </div>

          {localError ? (
            <div className="searchfill-alert">
              <Alert tone="error" variant="inline" size="sm" message={localError} />
            </div>
          ) : null}

          <div className="searchfill-results" aria-label="Search results">
            {results.length === 0 ? (
              <div
                className={[
                  'searchfill-results__empty',
                  hasSearched && !searching && !localError ? 'searchfill-results__empty--not-found' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                {hasSearched && !searching && !localError ? '(search) not found' : 'No results yet.'}
              </div>
            ) : (
              results.map((row, index) => {
                const preview = rowPreview(row, identifierKey);
                const demoTargetProps =
                  demoSearch?.highlightResult && index === 0
                    ? { 'data-demo-target': 'search-fill-result' }
                    : {};
                return (
                  <div key={index} className="searchfill-result">
                    <div className="searchfill-result__text">
                      <div className="searchfill-result__title">{preview.title}</div>
                      {preview.subtitle ? <div className="searchfill-result__subtitle">{preview.subtitle}</div> : null}
                    </div>
                    <button
                      type="button"
                      className="ui-button ui-button--primary ui-button--compact"
                      {...demoTargetProps}
                      onClick={() => void handleFill(row)}
                      disabled={searching}
                    >
                      Fill PDF
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
        <div className="searchfill-modal__footer">
          <button className="ui-button ui-button--ghost" onClick={onClose} type="button">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
