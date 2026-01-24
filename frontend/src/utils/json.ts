/**
 * JSON parsing helpers for local schema + Search & Fill data.
 */
import {
  ALLOWED_SCHEMA_TYPES,
  inferSchemaFromRows,
  type SchemaFieldType,
  type SchemaMetadata,
} from './schema';
import { dedupeColumnsByNormalizedKey, type HeaderRename } from './dataSource';

export type ParsedJsonData = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  schema: SchemaMetadata;
  headerRenames?: HeaderRename[];
};

type ParseJsonOptions = {
  maxRows?: number;
  maxDepth?: number;
};

const DEFAULT_MAX_ROWS = 5000;
const DEFAULT_MAX_DEPTH = 6;
const ROW_CONTAINER_KEYS = ['rows', 'records', 'data', 'items', 'entries'];
const COLUMN_KEYS = ['columns', 'headers', 'header'];
const META_KEYS = new Set(['schema', 'fields', 'columns', 'headers', 'header', ...ROW_CONTAINER_KEYS]);

type SchemaFieldInput = {
  name: string;
  type?: SchemaFieldType;
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object') return false;
  if (Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function isPrimitive(value: unknown): boolean {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function normaliseSchemaType(raw: unknown): SchemaFieldType {
  const candidate = String(raw ?? '').trim().toLowerCase();
  if (ALLOWED_SCHEMA_TYPES.has(candidate as SchemaFieldType)) {
    return candidate as SchemaFieldType;
  }
  return 'string';
}

function buildColumns(raw: unknown[], fallbackPrefix = 'column'): string[] {
  const columns: string[] = [];
  const seen = new Set<string>();
  for (let idx = 0; idx < raw.length; idx += 1) {
    const base = String(raw[idx] ?? '').trim();
    let name = base || `${fallbackPrefix}_${idx + 1}`;
    if (seen.has(name)) {
      let suffix = 2;
      let candidate = `${name}_${suffix}`;
      while (seen.has(candidate)) {
        suffix += 1;
        candidate = `${name}_${suffix}`;
      }
      name = candidate;
    }
    seen.add(name);
    columns.push(name);
  }
  return columns;
}

function parseFieldList(value: unknown): SchemaFieldInput[] {
  const fields: SchemaFieldInput[] = [];
  const seen = new Set<string>();

  const pushField = (rawName: unknown, rawType?: unknown) => {
    const name = String(rawName ?? '').trim();
    if (!name || seen.has(name)) return;
    const type =
      rawType === undefined || rawType === null || String(rawType).trim().length === 0
        ? undefined
        : normaliseSchemaType(rawType);
    fields.push(type ? { name, type } : { name });
    seen.add(name);
  };

  if (Array.isArray(value)) {
    for (const entry of value) {
      if (typeof entry === 'string') {
        pushField(entry);
        continue;
      }
      if (!isPlainObject(entry)) continue;
      const name =
        entry.name ?? entry.field ?? entry.column ?? entry.fieldName ?? entry.columnName ?? entry.id ?? '';
      const rawType = entry.type ?? entry.dataType ?? entry.datatype ?? entry.kind;
      pushField(name, rawType);
    }
    return fields;
  }

  if (isPlainObject(value)) {
    for (const [key, rawType] of Object.entries(value)) {
      if (isPlainObject(rawType)) {
        const nestedType = rawType.type ?? rawType.dataType ?? rawType.datatype ?? rawType.kind;
        pushField(key, nestedType);
      } else {
        pushField(key, rawType);
      }
    }
  }

  return fields;
}

function flattenRecord(record: Record<string, unknown>, maxDepth: number): Record<string, unknown> {
  const flattened: Record<string, unknown> = {};

  const assignValue = (key: string, value: unknown) => {
    if (!key) return;
    if (Object.prototype.hasOwnProperty.call(flattened, key)) return;
    flattened[key] = value;
  };

  const walk = (value: unknown, prefix: string, depth: number) => {
    if (depth > maxDepth) {
      assignValue(prefix, safeStringify(value));
      return;
    }
    if (isPlainObject(value)) {
      const entries = Object.entries(value);
      if (!entries.length) {
        assignValue(prefix, null);
        return;
      }
      for (const [key, child] of entries) {
        const nextKey = prefix ? `${prefix}_${key}` : key;
        walk(child, nextKey, depth + 1);
      }
      return;
    }
    if (Array.isArray(value)) {
      if (value.every(isPrimitive)) {
        assignValue(prefix, value);
        return;
      }
      assignValue(prefix, safeStringify(value));
      return;
    }
    assignValue(prefix, value);
  };

  // Depth-first flattening keeps keys stable for Search & Fill; O(k) per row over total nested keys.
  for (const [key, value] of Object.entries(record)) {
    const trimmed = String(key ?? '').trim();
    if (!trimmed) continue;
    walk(value, trimmed, 0);
  }

  return flattened;
}

function mergeColumns(columnsHint: string[] | undefined, rows: Array<Record<string, unknown>>): string[] {
  const columns: string[] = [];
  const seen = new Set<string>();
  if (columnsHint?.length) {
    for (const col of columnsHint) {
      const name = String(col ?? '').trim();
      if (!name || seen.has(name)) continue;
      seen.add(name);
      columns.push(name);
    }
  }
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (seen.has(key)) continue;
      seen.add(key);
      columns.push(key);
    }
  }
  return columns;
}

function normalizeRows(
  rowsInput: unknown,
  options: { maxRows: number; maxDepth: number; columnsHint?: string[] },
): { rows: Array<Record<string, unknown>>; columns: string[] } {
  const { maxRows, maxDepth, columnsHint } = options;

  if (rowsInput === undefined || rowsInput === null) {
    return { rows: [], columns: columnsHint ?? [] };
  }

  if (Array.isArray(rowsInput)) {
    const rowsArray = rowsInput;
    if (!rowsArray.length) {
      return { rows: [], columns: columnsHint ?? [] };
    }

    const hasArrayEntries = rowsArray.some((entry) => Array.isArray(entry));
    if (hasArrayEntries) {
      if (rowsArray.some((entry) => !Array.isArray(entry))) {
        throw new Error('JSON rows must be arrays or objects, not a mix of both.');
      }
      let columns = columnsHint && columnsHint.length ? [...columnsHint] : [];
      let dataRows = rowsArray as unknown[][];
      if (!columns.length) {
        const headerCandidate = dataRows[0] ?? [];
        const headerLooksValid = headerCandidate.every(
          (cell) => cell === null || cell === undefined || typeof cell === 'string',
        );
        if (headerLooksValid) {
          columns = buildColumns(headerCandidate);
          dataRows = dataRows.slice(1);
        }
      }
      const maxLen = dataRows.reduce((max, row) => Math.max(max, row.length), columns.length);
      if (columns.length < maxLen) {
        const extras = Array.from({ length: maxLen - columns.length }, (_, idx) => `column_${columns.length + idx + 1}`);
        columns = [...columns, ...extras];
      }
      const rows = dataRows.slice(0, maxRows).map((row) => {
        const record: Record<string, unknown> = {};
        for (let idx = 0; idx < columns.length; idx += 1) {
          record[columns[idx]] = row[idx];
        }
        return record;
      });
      return { rows, columns };
    }

    const rows: Array<Record<string, unknown>> = [];
    for (const entry of rowsArray) {
      if (isPlainObject(entry)) {
        rows.push(flattenRecord(entry, maxDepth));
      } else {
        rows.push({ value: entry });
      }
      if (rows.length >= maxRows) break;
    }
    return { rows, columns: mergeColumns(columnsHint, rows) };
  }

  if (isPlainObject(rowsInput)) {
    const row = flattenRecord(rowsInput, maxDepth);
    return { rows: [row], columns: mergeColumns(columnsHint, [row]) };
  }

  return { rows: [{ value: rowsInput }], columns: mergeColumns(columnsHint, [{ value: rowsInput }]) };
}

function extractPayload(raw: unknown): {
  rowsInput?: unknown;
  columnsHint?: string[];
  explicitFields?: SchemaFieldInput[];
} {
  if (Array.isArray(raw)) {
    return { rowsInput: raw };
  }
  if (!isPlainObject(raw)) {
    return { rowsInput: raw };
  }

  let schemaValue: unknown = undefined;
  if (raw.schema !== undefined) {
    if (isPlainObject(raw.schema) && 'fields' in raw.schema) {
      schemaValue = (raw.schema as Record<string, unknown>).fields;
    } else {
      schemaValue = raw.schema;
    }
  } else if (raw.fields !== undefined) {
    schemaValue = raw.fields;
  }
  let explicitFields = schemaValue ? parseFieldList(schemaValue) : [];

  const columnsValue = COLUMN_KEYS.map((key) => raw[key]).find((entry) => Array.isArray(entry));
  const columnsHint = columnsValue ? buildColumns(columnsValue as unknown[]) : [];

  if (!explicitFields.length && columnsHint.length) {
    explicitFields = columnsHint.map((name) => ({ name }));
  }

  const rowsKey = ROW_CONTAINER_KEYS.find((key) => key in raw);
  const rowsInput = rowsKey ? raw[rowsKey] : undefined;

  if (rowsInput !== undefined) {
    return { rowsInput, columnsHint, explicitFields };
  }

  const dataKeys = Object.keys(raw).filter((key) => !META_KEYS.has(key));
  if (dataKeys.length) {
    return { rowsInput: raw, columnsHint, explicitFields };
  }

  return { rowsInput: undefined, columnsHint, explicitFields };
}

function parseJson(text: string): unknown {
  const cleaned = String(text ?? '').replace(/^\uFEFF/, '').trim();
  if (!cleaned) {
    throw new Error('JSON file is empty.');
  }
  try {
    return JSON.parse(cleaned);
  } catch {
    const lines = cleaned.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length > 1) {
      try {
        return lines.map((line) => JSON.parse(line));
      } catch {
        throw new Error('Invalid JSON file.');
      }
    }
    throw new Error('Invalid JSON file.');
  }
}

/**
 * Parse JSON text into schema metadata and rows for Search & Fill.
 */
export function parseJsonDataSource(text: string, options: ParseJsonOptions = {}): ParsedJsonData {
  const maxRows = options.maxRows ?? DEFAULT_MAX_ROWS;
  const maxDepth = options.maxDepth ?? DEFAULT_MAX_DEPTH;
  const raw = parseJson(text);
  const { rowsInput, columnsHint, explicitFields } = extractPayload(raw);
  const { rows, columns } = normalizeRows(rowsInput, { maxRows, maxDepth, columnsHint });

  const resolvedColumns = explicitFields?.length ? explicitFields.map((field) => field.name) : columns;
  if (!resolvedColumns.length) {
    throw new Error('JSON schema has no field names.');
  }

  const trimmedRows = explicitFields?.length
    ? rows.map((row) => {
        const filtered: Record<string, unknown> = {};
        for (const key of resolvedColumns) {
          if (Object.prototype.hasOwnProperty.call(row, key)) {
            filtered[key] = row[key];
          }
        }
        return filtered;
      })
    : rows;

  const normalized = dedupeColumnsByNormalizedKey(resolvedColumns, trimmedRows);

  const inferred =
    normalized.rows.length > 0
      ? inferSchemaFromRows(normalized.columns, normalized.rows)
      : { fields: [], sampleCount: 0 };

  const schemaFields =
    explicitFields?.length
      ? explicitFields.map((field, index) => {
          const inferredField = inferred.fields[index];
          return {
            name: normalized.columns[index] ?? field.name,
            type: field.type ?? inferredField?.type ?? 'string',
          };
        })
      : inferred.fields;

  return {
    columns: normalized.columns,
    rows: normalized.rows,
    schema: {
      fields: schemaFields,
      sampleCount: inferred.sampleCount,
    },
    headerRenames: normalized.headerRenames,
  };
}
