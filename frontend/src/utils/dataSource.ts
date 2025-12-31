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

