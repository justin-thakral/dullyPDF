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
}: SearchFillModalProps) {
  const [searchKey, setSearchKey] = useState<string>('');
  const [searchMode, setSearchMode] = useState<SearchMode>('contains');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Array<Record<string, unknown>>>([]);
  const [searching, setSearching] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const canSearchAnyColumn = true;
  const hasData = rows.length > 0;

  const availableKeys = useMemo(() => {
    const unique = new Set(columns.filter(Boolean));
    return Array.from(unique);
  }, [columns]);

  useEffect(() => {
    if (!open) return;
    const defaultKey = identifierKey || availableKeys[0] || '';
    setSearchKey(defaultKey);
    setQuery('');
    setResults([]);
    setSearching(false);
    setLocalError(null);
    setSearchMode('contains');
    setHasSearched(false);
  }, [availableKeys, identifierKey, open, sessionId]);

  /**
   * Execute a search against local rows.
   */
  const runSearch = useCallback(async () => {
    if (!hasData) {
      setLocalError('Choose a CSV or Excel source first.');
      return;
    }
    if (!query.trim()) {
      setLocalError('Enter a search value.');
      return;
    }
    if (!searchKey || (!canSearchAnyColumn && searchKey === '__any__')) {
      setLocalError('Choose a column to search.');
      return;
    }

    setLocalError(null);
    setHasSearched(true);
    setSearching(true);
    setResults([]);
    try {
      const q = query.trim().toLowerCase();
      const matches = (value: string) => (searchMode === 'equals' ? value === q : value.includes(q));
      const matched: Array<Record<string, unknown>> = [];
      for (const row of rows) {
        if (searchKey === '__any__') {
          const keys = availableKeys.length ? availableKeys : Object.keys(row);
          const ok = keys.some((key) => matches(String(row[key] ?? '').toLowerCase()));
          if (!ok) continue;
        } else {
          const value = String(row[searchKey] ?? '').toLowerCase();
          if (!matches(value)) continue;
        }
        matched.push(row);
        if (matched.length >= 25) break;
      }
      setResults(matched);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Search failed.';
      setLocalError(message);
    } finally {
      setSearching(false);
    }
  }, [availableKeys, canSearchAnyColumn, hasData, query, rows, searchKey, searchMode]);

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
      const presenceFalseTokens = new Set(['', 'n/a', 'na', 'none', 'unknown', 'unsure']);

      const setCheckboxOverride = (groupKey: string, optionKey: string, value: boolean) => {
        const group = checkboxGroups.get(normaliseDataKey(groupKey));
        if (!group) return false;
        const option = group.options.get(normaliseDataKey(optionKey));
        if (!option) return false;
        checkboxOverrides.set(option.id, value);
        return true;
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
        for (const [optionKey, aliases] of group.optionAliases) {
          if (aliases.has(normalized)) return optionKey;
        }
        const optionKeys = Array.from(group.options.keys());
        const prefixMatches = optionKeys.filter(
          (optionKey) => normalized.startsWith(optionKey) || optionKey.startsWith(normalized),
        );
        if (prefixMatches.length === 1) return prefixMatches[0];
        if (normalized.length > 0) {
          const initial = normalized[0];
          const initialMatches = optionKeys.filter((optionKey) => optionKey.length === 1 && optionKey === initial);
          if (initialMatches.length === 1) return initialMatches[0];
        }
        return null;
      };

      const resolveCheckboxValue = (
        baseName: string,
        groupKey?: string,
        options?: { allowPresence?: boolean },
      ): boolean | null => {
        const allowPresence = options?.allowPresence ?? false;
        const resolveValue = allowPresence ? coerceBooleanWithPresence : coerceBoolean;
        const bases = new Set<string>();
        const addBase = (value: string) => {
          const normalized = normaliseDataKey(value);
          if (normalized) bases.add(normalized);
        };
        addBase(baseName);
        if (groupKey) {
          addBase(`${groupKey}_${baseName}`);
        }
        if (baseName.endsWith('ies')) addBase(`${baseName.slice(0, -3)}y`);
        if (baseName.endsWith('s')) addBase(baseName.slice(0, -1));
        else addBase(`${baseName}s`);

        if (groupKey) {
          for (const base of Array.from(bases)) {
            if (!base.startsWith(`${groupKey}_`)) {
              bases.add(`${groupKey}_${base}`);
            }
          }
        }

        const aliases = CHECKBOX_ALIASES[baseName] || [];
        for (const alias of aliases) addBase(alias);

        const candidates = new Set<string>();
        for (const base of bases) {
          candidates.add(base);
          candidates.add(`has_${base}`);
          candidates.add(`is_${base}`);
          candidates.add(`takes_${base}`);
          candidates.add(`${base}_flag`);
          candidates.add(`${base}_status`);
          candidates.add(`${base}_use`);
          candidates.add(`${base}_text`);
          candidates.add(`${base}_description`);
        }

        for (const key of candidates) {
          const value = normalizedRow.get(key);
          if (value === undefined) continue;
          const boolValue = resolveValue(value);
          if (boolValue !== null) return boolValue;
        }

        for (const base of bases) {
          const pattern = new RegExp(`(^|_)${base}(_|$)`);
          const allowBroadMatch = allowPresence && base.length >= 4;
          for (const key of normalizedRowKeys) {
            if (!pattern.test(key)) continue;
            if (
              !allowBroadMatch &&
              key !== base &&
              !key.startsWith('has_') &&
              !key.startsWith('is_') &&
              !key.startsWith('takes_') &&
              !key.endsWith('_flag') &&
              !key.endsWith('_status')
            ) {
              continue;
            }
            const value = normalizedRow.get(key);
            if (value === undefined) continue;
            const boolValue = resolveValue(value);
            if (boolValue !== null) return boolValue;
          }
        }

        return null;
      };

      // Apply explicit checkbox rules before any heuristic defaults.
      const applyCheckboxRules = () => {
        const rules = checkboxRules || [];
        for (const rule of rules) {
          if (!rule?.groupKey || !rule?.databaseField || !rule?.operation) continue;
          const group = checkboxGroups.get(normaliseDataKey(rule.groupKey));
          if (!group) continue;
          const rowValue = normalizedRow.get(normaliseDataKey(rule.databaseField));
          if (rowValue === undefined) continue;

          if (rule.operation === 'yes_no') {
            const boolValue = coerceBooleanWithPresence(rowValue);
            if (boolValue === null) continue;
            const trueOption =
              (rule.trueOption && normaliseDataKey(rule.trueOption)) ||
              (group.options.has('yes') ? 'yes' : group.options.has('true') ? 'true' : null) ||
              (group.options.size === 1 ? Array.from(group.options.keys())[0] : null);
            const falseOption =
              (rule.falseOption && normaliseDataKey(rule.falseOption)) ||
              (group.options.has('no') ? 'no' : group.options.has('false') ? 'false' : null);
            if (boolValue && trueOption) {
              setCheckboxOverride(rule.groupKey, trueOption, true);
              if (falseOption) setCheckboxOverride(rule.groupKey, falseOption, false);
            }
            if (!boolValue && falseOption) {
              setCheckboxOverride(rule.groupKey, falseOption, true);
              if (trueOption) setCheckboxOverride(rule.groupKey, trueOption, false);
            }
            continue;
          }

          if (rule.operation === 'presence') {
            const hasValue = (() => {
              if (rowValue === null || rowValue === undefined) return false;
              if (typeof rowValue === 'string') return rowValue.trim().length > 0;
              if (typeof rowValue === 'number') return rowValue !== 0;
              if (typeof rowValue === 'boolean') return rowValue;
              return true;
            })();
            if (!hasValue) continue;
            const trueOption =
              (rule.trueOption && normaliseDataKey(rule.trueOption)) ||
              (group.options.has('yes') ? 'yes' : null) ||
              (group.options.size === 1 ? Array.from(group.options.keys())[0] : null);
            if (trueOption) setCheckboxOverride(rule.groupKey, trueOption, true);
            continue;
          }

          if (rule.operation === 'list') {
            const parts = splitListValue(rowValue);
            for (const part of parts) {
              const optionKey = resolveOptionKey(group, part, rule.valueMap);
              if (optionKey) setCheckboxOverride(rule.groupKey, optionKey, true);
            }
            continue;
          }

          if (rule.operation === 'enum') {
            const optionKey = resolveOptionKey(group, rowValue, rule.valueMap);
            if (optionKey) setCheckboxOverride(rule.groupKey, optionKey, true);
          }
        }
      };

      // Backfill yes/no checkbox groups when rules did not set overrides.
      const applyYesNoDefaults = () => {
        for (const [groupKey, group] of checkboxGroups) {
          const optionKeys = Array.from(group.options.keys());
          const yesOption =
            optionKeys.find((option) => option === 'yes') ||
            optionKeys.find((option) => option === 'true') ||
            optionKeys.find((option) => option === 'y');
          const noOption =
            optionKeys.find((option) => option === 'no') ||
            optionKeys.find((option) => option === 'false') ||
            optionKeys.find((option) => option === 'n');
          if (!yesOption || !noOption) continue;
          const hasOverride = optionKeys.some((optionKey) => {
            const field = group.options.get(optionKey);
            return field ? checkboxOverrides.has(field.id) : false;
          });
          if (hasOverride) continue;
          const resolved = resolveCheckboxValue(groupKey, undefined, { allowPresence: true });
          const boolValue = resolved === null ? false : resolved;
          setCheckboxOverride(groupKey, boolValue ? yesOption : noOption, true);
          setCheckboxOverride(groupKey, boolValue ? noOption : yesOption, false);
        }
      };

      applyCheckboxRules();
      applyYesNoDefaults();

      // Resolve a best-effort field value from the normalized row values.
      const resolveValueForField = (field: PdfField): unknown | undefined => {
        if (field.type === 'checkbox' && checkboxOverrides.has(field.id)) {
          return checkboxOverrides.get(field.id);
        }
        const normalizedName = normaliseDataKey(field.name);
        const getRowValue = (...keys: string[]): unknown | undefined => {
          for (const key of keys) {
            const value = normalizedRow.get(normaliseDataKey(key));
            if (value !== undefined) return value;
          }
          return undefined;
        };

        const resolveCompositeCheckboxValue = (field: PdfField): boolean | null => {
          const meta = resolveCheckboxMeta(field);
          const groupKey = meta?.groupKey;
          const rawLabel = String(field.optionLabel || field.optionKey || field.name || '').trim();
          if (!rawLabel) return null;
          const cleanedLabel = rawLabel.replace(/^i[_\\s]+/i, '');
          const lower = cleanedLabel.toLowerCase().replace(/_/g, ' ');
          const hasAndOr = lower.includes('and/or');
          const hasOr = hasAndOr || lower.includes(' or ');
          const hasAnd = lower.includes(' and ');
          if (!hasOr && !hasAnd) return null;
          const operator = hasOr ? 'or' : 'and';
          const splitter = hasOr ? /\s+or\s+/ : /\s+and\s+/;
          const parts = lower
            .replace(/[()]/g, ' ')
            .split(splitter)
            .map((part) => part.trim())
            .filter(Boolean);
          if (parts.length < 2) return null;
          const values = parts
            .map((part) => resolveCheckboxValue(part, groupKey))
            .filter((value): value is boolean => value !== null);
          if (!values.length) return null;
          if (operator === 'or') {
            if (values.some(Boolean)) return true;
            if (values.every((value) => value === false)) return false;
            return null;
          }
          if (values.every(Boolean)) return true;
          if (values.some((value) => value === false)) return false;
          return null;
        };

        const direct = normalizedRow.get(normalizedName);
        if (direct !== undefined) {
          if (field.type === 'checkbox') {
            const boolValue = coerceBoolean(direct);
            if (boolValue !== null) return boolValue;
          }
          return direct;
        }

        if (field.type === 'checkbox') {
          const checkboxName = normalizedName.startsWith('i_')
            ? normalizedName.slice(2)
            : normalizedName;
          const yesNoMatch = checkboxName.match(/^(.*)_(yes|no|true|false)$/);
          if (yesNoMatch) {
            const baseName = yesNoMatch[1];
            const desired = yesNoMatch[2] === 'yes' || yesNoMatch[2] === 'true';
            const boolValue = resolveCheckboxValue(baseName, resolveCheckboxMeta(field)?.groupKey, {
              allowPresence: true,
            });
            if (boolValue !== null) return boolValue === desired;
            if (!desired) return true;
            return false;
          }
          const compositeValue = resolveCompositeCheckboxValue(field);
          if (compositeValue !== null) return compositeValue;
          const boolValue = resolveCheckboxValue(checkboxName, resolveCheckboxMeta(field)?.groupKey);
          if (boolValue !== null) return boolValue;
        }

        const addressLine1 = getRowValue(
          'address_line_1',
          'address_line1',
          'address1',
          'street_address',
          'street',
          'mailing_address',
          'home_address',
          'address',
        );
        const addressLine2 = getRowValue(
          'address_line_2',
          'address_line2',
          'address2',
          'apt',
          'apartment',
          'suite',
          'unit',
        );
        const city = getRowValue('city', 'town');
        const state = getRowValue('state', 'province', 'region');
        const zip = getRowValue('zip', 'zip_code', 'postal_code', 'postcode');

        if (
          [
            'address_line_1',
            'address_line1',
            'address1',
            'street_address',
            'street',
            'mailing_address',
            'home_address',
          ].includes(
            normalizedName,
          )
        ) {
          if (addressLine1 !== undefined) return addressLine1;
        }
        if (
          ['address_line_2', 'address_line2', 'address2', 'apt', 'apartment', 'suite', 'unit'].includes(
            normalizedName,
          )
        ) {
          if (addressLine2 !== undefined) return addressLine2;
        }
        if (normalizedName === 'address' || normalizedName === 'full_address') {
          const parts = [addressLine1, addressLine2].filter(Boolean);
          if (parts.length) return parts.join(' ');
          const locality = [city, state, zip].filter(Boolean);
          if (locality.length) return locality.join(', ');
        }
        if (normalizedName === 'city' && city !== undefined) return city;
        if (normalizedName === 'state' && state !== undefined) return state;
        if (
          ['zip', 'zip_code', 'postal_code', 'postcode'].includes(normalizedName) &&
          zip !== undefined
        ) {
          return zip;
        }
        if (
          ['city_state_zip', 'city_state_zipcode', 'city_state_zip_code'].includes(normalizedName)
        ) {
          const locality = [city, state, zip].filter(Boolean);
          if (locality.length) return locality.join(', ');
        }

        const suffixMatch = normalizedName.match(/^(.*)_\d+$/);
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

          <div className="searchfill-controls">
            <div className="searchfill-field">
              <label className="searchfill-label" htmlFor="searchfill-key">
                Column
              </label>
              <select
                id="searchfill-key"
                value={searchKey}
                onChange={(event) => setSearchKey(event.target.value)}
                disabled={!hasData || searching}
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
                disabled={!hasData || searching}
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
                disabled={!hasData || searching}
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
                onClick={() => void runSearch()}
                disabled={!hasData || searching}
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
                return (
                  <div key={index} className="searchfill-result">
                    <div className="searchfill-result__text">
                      <div className="searchfill-result__title">{preview.title}</div>
                      {preview.subtitle ? <div className="searchfill-result__subtitle">{preview.subtitle}</div> : null}
                    </div>
                    <button
                      type="button"
                      className="ui-button ui-button--primary ui-button--compact"
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
