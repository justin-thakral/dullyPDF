/**
 * CSV parsing helpers for local schema + Search & Fill data.
 */
import { dedupeColumnsByNormalizedKey, type HeaderRename } from './dataSource';

export type ParsedCsv = {
  columns: string[];
  rows: Array<Record<string, string>>;
  headerRenames?: HeaderRename[];
};

type ParseCsvOptions = {
  delimiter?: string;
  maxRows?: number;
};

/**
 * Parse CSV text into columns and row records.
 */
export function parseCsv(text: string, options: ParseCsvOptions = {}): ParsedCsv {
  const delimiter = options.delimiter ?? ',';
  const maxRows = options.maxRows ?? 5000;
  const input = String(text ?? '').replace(/^\uFEFF/, '');

  const rows: string[][] = [];
  let currentField = '';
  let currentRow: string[] = [];
  let inQuotes = false;

  const pushField = () => {
    currentRow.push(currentField);
    currentField = '';
  };

  const pushRow = () => {
    rows.push(currentRow);
    currentRow = [];
  };

  for (let index = 0; index < input.length; index += 1) {
    const ch = input[index];

    if (ch === '"') {
      const next = input[index + 1];
      if (inQuotes && next === '"') {
        currentField += '"';
        index += 1;
        continue;
      }
      inQuotes = !inQuotes;
      continue;
    }

    if (!inQuotes && ch === delimiter) {
      pushField();
      continue;
    }

    if (!inQuotes && (ch === '\n' || ch === '\r')) {
      if (ch === '\r' && input[index + 1] === '\n') {
        index += 1;
      }
      pushField();
      pushRow();
      if (rows.length > maxRows) break;
      continue;
    }

    currentField += ch;
  }

  if (currentField.length || currentRow.length) {
    pushField();
    pushRow();
  }

  const [rawHeader, ...dataRows] = rows;
  const seenHeaders = new Set<string>();
  const headerRenames: HeaderRename[] = [];
  const columnSpecs = (rawHeader || [])
    .map((col, index) => {
      const base = String(col ?? '').trim();
      if (!base) return null;
      let name = base;
      if (seenHeaders.has(name)) {
        let suffix = 2;
        let candidate = `${name}_${suffix}`;
        while (seenHeaders.has(candidate)) {
          suffix += 1;
          candidate = `${name}_${suffix}`;
        }
        name = candidate;
        headerRenames.push({ original: base, renamed: name });
      }
      seenHeaders.add(name);
      return { name, index };
    })
    .filter((spec): spec is { name: string; index: number } => Boolean(spec));
  const columns = columnSpecs.map((spec) => spec.name);

  const outRows: Array<Record<string, string>> = [];
  for (const row of dataRows) {
    if (!row || row.every((val) => String(val ?? '').trim() === '')) continue;
    const record: Record<string, string> = {};
    for (const spec of columnSpecs) {
      record[spec.name] = String(row[spec.index] ?? '');
    }
    outRows.push(record);
    if (outRows.length >= maxRows) break;
  }

  const normalized = dedupeColumnsByNormalizedKey(columns, outRows);
  const combinedRenames = [
    ...headerRenames,
    ...(normalized.headerRenames ?? []),
  ];

  return {
    columns: normalized.columns,
    rows: normalized.rows as Array<Record<string, string>>,
    headerRenames: combinedRenames.length ? combinedRenames : undefined,
  };
}
