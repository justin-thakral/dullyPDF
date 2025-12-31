export type ParsedExcel = {
  columns: string[];
  rows: Array<Record<string, string>>;
  sheetName: string | null;
};

type ParseExcelOptions = {
  sheetIndex?: number;
  maxRows?: number;
};

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
  const columns = (rawHeader || [])
    .map((cell) => String(cell ?? '').trim())
    .filter((col) => col.length > 0);

  const rows: Array<Record<string, string>> = [];
  for (const row of rawRows) {
    if (!row || row.every((val) => String(val ?? '').trim() === '')) continue;
    const record: Record<string, string> = {};
    for (let idx = 0; idx < columns.length; idx += 1) {
      record[columns[idx]] = String((row as any[])[idx] ?? '');
    }
    rows.push(record);
    if (rows.length >= maxRows) break;
  }

  return { columns, rows, sheetName };
}
