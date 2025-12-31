export type ParsedCsv = {
  columns: string[];
  rows: Array<Record<string, string>>;
};

type ParseCsvOptions = {
  delimiter?: string;
  maxRows?: number;
};

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
  const columns = (rawHeader || [])
    .map((col) => String(col ?? '').trim())
    .filter((col) => col.length > 0);

  const outRows: Array<Record<string, string>> = [];
  for (const row of dataRows) {
    if (!row || row.every((val) => String(val ?? '').trim() === '')) continue;
    const record: Record<string, string> = {};
    for (let idx = 0; idx < columns.length; idx += 1) {
      record[columns[idx]] = String(row[idx] ?? '');
    }
    outRows.push(record);
    if (outRows.length >= maxRows) break;
  }

  return { columns, rows: outRows };
}

