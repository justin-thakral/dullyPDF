/**
 * XLSX parsing helpers for local schema + Search & Fill data.
 */
import { dedupeColumnsByNormalizedKey, type HeaderRename } from './dataSource';

export type ParsedExcel = {
  columns: string[];
  rows: Array<Record<string, string>>;
  sheetName: string | null;
  headerRenames?: HeaderRename[];
};

type ParseExcelOptions = {
  sheetIndex?: number;
  maxRows?: number;
};

/**
 * Parse a 2D cell table (header row + rows) into columns and row records.
 *
 * Exported for unit tests so the normalization logic is exercised without relying on an XLSX generator.
 */
export function parseExcelTable(table: unknown[][], options: ParseExcelOptions = {}): Omit<ParsedExcel, 'sheetName'> {
  const maxRows = options.maxRows ?? 5000;
  const [rawHeader, ...rawRows] = Array.isArray(table) ? table : [];
  const seenHeaders = new Set<string>();
  const headerRenames: HeaderRename[] = [];
  const columnSpecs = (rawHeader || [])
    .map((cell, index) => {
      const base = String(cell ?? '').trim();
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

  const rows: Array<Record<string, string>> = [];
  for (const row of rawRows) {
    if (!row || row.every((val) => String(val ?? '').trim() === '')) continue;
    const record: Record<string, string> = {};
    for (const spec of columnSpecs) {
      record[spec.name] = String((row as any[])[spec.index] ?? '');
    }
    rows.push(record);
    if (rows.length >= maxRows) break;
  }

  const normalized = dedupeColumnsByNormalizedKey(columns, rows);
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

/**
 * Parse an Excel workbook buffer into columns and row records.
 */
export async function parseExcel(buffer: ArrayBuffer, options: ParseExcelOptions = {}): Promise<ParsedExcel> {
  const sheetIndex = options.sheetIndex ?? 0;
  const maxRows = options.maxRows ?? 5000;

  // Kept as a separate lazy-loaded chunk so the editor doesn't pay XLSX cost unless needed.
  const mod = await import('read-excel-file');
  const readXlsxFile: any = (mod as any).default || mod;

  let sheetName: string | null = null;
  let rows: unknown[][] = [];

  // Prefer fetching sheet metadata so we can report the selected sheet name.
  try {
    const sheets = await readXlsxFile(buffer, { getSheets: true });
    if (Array.isArray(sheets) && sheets.length) {
      const selected = sheets[sheetIndex] ?? sheets[0];
      if (selected && typeof selected === 'object') {
        const name = (selected as any).name;
        sheetName = typeof name === 'string' && name.trim() ? name.trim() : null;
        const sheetId = (selected as any).id ?? (sheetName || undefined);
        rows = await readXlsxFile(buffer, sheetId ? { sheet: sheetId } : undefined);
      }
    }
  } catch {
    // Fall back to loading the first sheet without metadata.
  }

  if (!rows.length) {
    rows = await readXlsxFile(buffer);
  }

  if (!Array.isArray(rows) || rows.length === 0) {
    return { columns: [], rows: [], sheetName };
  }

  const parsed = parseExcelTable(rows, { maxRows });
  return {
    ...parsed,
    sheetName,
  };
}
