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
 * Parse an Excel workbook buffer into columns and row records.
 */
export async function parseExcel(buffer: ArrayBuffer, options: ParseExcelOptions = {}): Promise<ParsedExcel> {
  // Kept as a separate lazy-loaded chunk so the editor doesn't pay XLSX cost unless needed.
  const XLSX = await import('xlsx');
  const sheetIndex = options.sheetIndex ?? 0;
  const maxRows = options.maxRows ?? 5000;

  const workbook = XLSX.read(buffer, { type: 'array' });
  const sheetName = workbook.SheetNames[sheetIndex] ?? workbook.SheetNames[0] ?? null;
  if (!sheetName) return { columns: [], rows: [], sheetName: null };
  const sheet = workbook.Sheets[sheetName];
  if (!sheet) return { columns: [], rows: [], sheetName };

  const table = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '' }) as unknown[][];
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
    sheetName,
    headerRenames: combinedRenames.length ? combinedRenames : undefined,
  };
}
