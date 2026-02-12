/**
 * Pick a likely identifier column from a list using common heuristics.
 */
export function pickIdentifierKey(columns: string[]): string | null {
  if (!columns.length) return null;
  const lowerToOriginal = new Map(columns.map((col) => [col.toLowerCase(), col]));
  for (const pref of ['mrn', 'patient_id', 'enterprise_patient_id', 'external_mrn', 'id']) {
    const match = lowerToOriginal.get(pref);
    if (match) return match;
  }
  for (const col of columns) {
    if (col.toLowerCase().includes('mrn')) return col;
  }
  for (const col of columns) {
    const lower = col.toLowerCase();
    if (lower.endsWith('_id') || lower === 'id') return col;
  }
  return columns[0] ?? null;
}

export function normaliseDataKey(raw: string): string {
  return String(raw || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
    .replace(/[^a-z0-9_]/g, '');
}

export type HeaderRename = {
  original: string;
  renamed: string;
};

export function resolveIdentifierKey(candidate: unknown, columns: string[]): string | null {
  if (!candidate || !columns.length) return null;
  const raw = String(candidate || '').trim();
  if (!raw) return null;
  if (columns.includes(raw)) return raw;
  const normalized = normaliseDataKey(raw);
  if (!normalized) return null;
  const match = columns.find((col) => normaliseDataKey(col) === normalized);
  return match ?? null;
}

export function dedupeColumnsByNormalizedKey(
  columns: string[],
  rows: Array<Record<string, unknown>>,
): { columns: string[]; rows: Array<Record<string, unknown>>; headerRenames?: HeaderRename[] } {
  const resolvedColumns: string[] = [];
  const headerRenames: HeaderRename[] = [];
  const usedNormalized = new Set<string>();

  columns.forEach((raw, index) => {
    const originalName = String(raw ?? '').trim();
    let name = originalName || `column_${index + 1}`;
    let normalized = normaliseDataKey(name) || `column_${index + 1}`;

    if (usedNormalized.has(normalized)) {
      let suffix = 2;
      let candidate = `${name}_${suffix}`;
      let candidateNormalized = normaliseDataKey(candidate);
      while (!candidateNormalized || usedNormalized.has(candidateNormalized)) {
        suffix += 1;
        candidate = `${name}_${suffix}`;
        candidateNormalized = normaliseDataKey(candidate);
      }
      headerRenames.push({ original: originalName || name, renamed: candidate });
      name = candidate;
      normalized = candidateNormalized || `column_${index + 1}_${suffix}`;
    } else if (name !== originalName) {
      headerRenames.push({ original: originalName, renamed: name });
    }

    usedNormalized.add(normalized);
    resolvedColumns.push(name);
  });

  if (!headerRenames.length) {
    return { columns: resolvedColumns, rows };
  }

  const originalSet = new Set(columns);
  const nextRows = rows.map((row) => {
    const next: Record<string, unknown> = {};
    for (let idx = 0; idx < columns.length; idx += 1) {
      const original = columns[idx];
      const renamed = resolvedColumns[idx];
      if (Object.prototype.hasOwnProperty.call(row, original)) {
        next[renamed] = row[original];
      }
    }
    for (const key of Object.keys(row)) {
      if (!originalSet.has(key)) {
        next[key] = row[key];
      }
    }
    return next;
  });

  return {
    columns: resolvedColumns,
    rows: nextRows,
    headerRenames,
  };
}
