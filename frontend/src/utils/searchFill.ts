import { normaliseDataKey } from './dataSource';

const BOOLEAN_TRUE_TOKENS = new Set([
  'true',
  '1',
  'yes',
  'y',
  'on',
  'checked',
  't',
  'x',
  'selected',
]);
const BOOLEAN_FALSE_TOKENS = new Set([
  'false',
  '0',
  'no',
  'n',
  'off',
  'unchecked',
  'f',
  'unselected',
]);
const AMBIGUOUS_BOOLEAN_TOKENS = new Set(['yn', 'yesno', 'truefalse', 'tf', '01', '10']);
const PRESENCE_FALSE_TOKENS = new Set([
  'na',
  'none',
  'unknown',
  'unsure',
  'nil',
  'null',
  'empty',
  'blank',
  'absent',
  'notpresent',
  'noneknown',
  'nonereported',
  'notapplicable',
  'notavailable',
]);

function normalizeCheckboxToken(raw: string): string {
  return normaliseDataKey(raw).replace(/_/g, '');
}

export function coerceCheckboxBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value !== 0 : null;
  if (typeof value === 'string') {
    const normalized = normalizeCheckboxToken(value);
    if (!normalized || AMBIGUOUS_BOOLEAN_TOKENS.has(normalized)) return null;
    if (BOOLEAN_TRUE_TOKENS.has(normalized)) return true;
    if (BOOLEAN_FALSE_TOKENS.has(normalized)) return false;
  }
  return null;
}

export function coerceCheckboxPresence(value: unknown): boolean | null {
  const direct = coerceCheckboxBoolean(value);
  if (direct !== null) return direct;
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') {
    const normalized = normalizeCheckboxToken(value);
    if (!normalized) return null;
    if (AMBIGUOUS_BOOLEAN_TOKENS.has(normalized)) return null;
    if (PRESENCE_FALSE_TOKENS.has(normalized)) return false;
    return true;
  }
  if (typeof value === 'number') return Number.isFinite(value) ? value !== 0 : null;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

export function splitCheckboxListValue(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry).trim()).filter(Boolean);
  }
  if (typeof value !== 'string') return [String(value)];
  const raw = value.trim();
  if (!raw) return [];
  const normalized = normalizeCheckboxToken(raw);
  if (AMBIGUOUS_BOOLEAN_TOKENS.has(normalized) || PRESENCE_FALSE_TOKENS.has(normalized)) {
    return [raw];
  }
  return raw
    .split(/[,;|/]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function normalizeCheckboxValueMap(
  valueMap?: Record<string, string>,
): Record<string, string> | undefined {
  if (!valueMap) return undefined;
  const normalized: Record<string, string> = {};
  for (const [key, mappedValue] of Object.entries(valueMap)) {
    const normalizedKey = normaliseDataKey(key);
    if (!normalizedKey) continue;
    const normalizedValue = normaliseDataKey(String(mappedValue ?? ''));
    const resolvedValue = normalizedValue || String(mappedValue ?? '');
    normalized[normalizedKey] = resolvedValue;
    const compactKey = normalizedKey.replace(/_/g, '');
    if (compactKey && !(compactKey in normalized)) {
      normalized[compactKey] = resolvedValue;
    }
  }
  return normalized;
}

export function getNumericSuffixBase(name: string): string | null {
  const match = name.match(/^(.*)_\d+$/);
  return match?.[1] ?? null;
}
