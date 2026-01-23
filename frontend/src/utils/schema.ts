/**
 * Schema inference utilities for CSV/Excel/JSON/TXT uploads.
 */

export type SchemaFieldType = 'string' | 'int' | 'date' | 'bool';

export type SchemaField = {
  name: string;
  type: SchemaFieldType;
};

export type SchemaMetadata = {
  fields: SchemaField[];
  sampleCount: number;
};

const BOOL_TRUE = new Set(['true', '1', 'yes', 'y', 't']);
const BOOL_FALSE = new Set(['false', '0', 'no', 'n', 'f']);

function isBooleanValue(value: string): boolean {
  const norm = value.trim().toLowerCase();
  return BOOL_TRUE.has(norm) || BOOL_FALSE.has(norm);
}

function isIntegerValue(value: string): boolean {
  return /^-?\d+$/.test(value.trim());
}

function isDateValue(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  if (/^(19|20)\d{2}[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])$/.test(trimmed)) {
    return true;
  }
  if (/^(0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])[-/](19|20)\d{2}$/.test(trimmed)) {
    return true;
  }
  return false;
}

function inferColumnType(values: string[]): SchemaFieldType {
  const nonEmpty = values.map((value) => value.trim()).filter((value) => value.length > 0);
  if (!nonEmpty.length) return 'string';
  if (nonEmpty.every(isBooleanValue)) return 'bool';
  if (nonEmpty.every(isIntegerValue)) return 'int';
  if (nonEmpty.every(isDateValue)) return 'date';
  return 'string';
}

/**
 * Infer schema fields and types from a set of rows.
 */
export function inferSchemaFromRows(
  columns: string[],
  rows: Array<Record<string, unknown>>,
  options: { sampleSize?: number } = {},
): SchemaMetadata {
  const sampleSize = options.sampleSize ?? 200;
  const sample = rows.slice(0, sampleSize);

  const fields = columns.map((name) => {
    const values = sample.map((row) => String(row[name] ?? ''));
    return {
      name,
      type: inferColumnType(values),
    } as SchemaField;
  });

  return { fields, sampleCount: sample.length };
}

/**
 * Parse a TXT schema file with one field per line.
 *
 * Format: field_name[:type]
 */
export function parseSchemaText(text: string): SchemaMetadata {
  const fields: SchemaField[] = [];
  const seen = new Set<string>();
  const lines = text.split(/\r?\n/);
  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const [rawName, rawType] = trimmed.split(':', 2);
    const name = rawName.trim();
    if (!name || seen.has(name)) continue;
    let type = (rawType || '').trim().toLowerCase() as SchemaFieldType;
    if (!ALLOWED_SCHEMA_TYPES.has(type)) {
      type = 'string';
    }
    seen.add(name);
    fields.push({ name, type });
  }
  return { fields, sampleCount: 0 };
}

export const ALLOWED_SCHEMA_TYPES: Set<SchemaFieldType> = new Set([
  'string',
  'int',
  'date',
  'bool',
]);
