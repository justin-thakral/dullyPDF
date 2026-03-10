import type {
  CheckboxHint,
  CheckboxRule,
  PageSize,
  PdfField,
  SavedFormEditorSnapshot,
  TextTransformRule,
} from '../types';

type FillRulesSource = {
  fillRules?: {
    checkboxRules?: Array<Record<string, unknown>>;
    checkboxHints?: Array<Record<string, unknown>>;
    textTransformRules?: Array<Record<string, unknown>>;
    templateRules?: Array<Record<string, unknown>>;
  };
  checkboxRules?: Array<Record<string, unknown>>;
  checkboxHints?: Array<Record<string, unknown>>;
  textTransformRules?: Array<Record<string, unknown>>;
  templateRules?: Array<Record<string, unknown>>;
};

export type SavedFormFillRuleState = {
  checkboxRules: CheckboxRule[];
  checkboxHints: CheckboxHint[];
  textTransformRules: TextTransformRule[];
};

function normalizeRect(value: unknown): PdfField['rect'] | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const x = Number(record.x);
  const y = Number(record.y);
  const width = Number(record.width);
  const height = Number(record.height);
  if (
    !Number.isFinite(x) ||
    !Number.isFinite(y) ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  ) {
    return null;
  }
  return { x, y, width, height };
}

function normalizeFieldValue(value: unknown): PdfField['value'] {
  if (
    value === null ||
    value === undefined ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }
  return String(value);
}

function normalizeField(value: unknown): PdfField | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const id = String(record.id || '').trim();
  const name = String(record.name || '').trim();
  const type = String(record.type || 'text').trim() as PdfField['type'];
  const page = Number(record.page);
  const rect = normalizeRect(record.rect);
  if (!id || !name || !rect || !Number.isInteger(page) || page < 1) {
    return null;
  }
  if (!['text', 'checkbox', 'signature', 'date'].includes(type)) {
    return null;
  }
  const field: PdfField = {
    id,
    name,
    type,
    page,
    rect,
    value: normalizeFieldValue(record.value),
  };
  for (const key of ['groupKey', 'optionKey', 'optionLabel', 'groupLabel'] as const) {
    const raw = record[key];
    if (raw === undefined || raw === null) {
      continue;
    }
    field[key] = String(raw);
  }
  for (const key of ['fieldConfidence', 'mappingConfidence', 'renameConfidence'] as const) {
    const raw = record[key];
    if (raw === undefined || raw === null) {
      continue;
    }
    const numeric = Number(raw);
    if (Number.isFinite(numeric)) {
      field[key] = numeric;
    }
  }
  return field;
}

function normalizePageSizes(
  value: unknown,
  pageCount: number,
): Record<number, PageSize> | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const normalized: Record<number, PageSize> = {};
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const raw = record[String(pageNumber)] ?? record[pageNumber];
    if (!raw || typeof raw !== 'object') {
      return null;
    }
    const size = raw as Record<string, unknown>;
    const width = Number(size.width);
    const height = Number(size.height);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      return null;
    }
    normalized[pageNumber] = { width, height };
  }
  return normalized;
}

export function buildSavedFormEditorSnapshot(params: {
  pageCount: number;
  pageSizes: Record<number, PageSize>;
  fields: PdfField[];
  hasRenamedFields: boolean;
  hasMappedSchema: boolean;
}): SavedFormEditorSnapshot {
  return {
    version: 1,
    pageCount: params.pageCount,
    pageSizes: Object.fromEntries(
      Object.entries(params.pageSizes).map(([page, size]) => [
        Number(page),
        { width: size.width, height: size.height },
      ]),
    ),
    fields: params.fields.map((field) => ({
      ...field,
      rect: { ...field.rect },
    })),
    hasRenamedFields: params.hasRenamedFields,
    hasMappedSchema: params.hasMappedSchema,
  };
}

export function normalizeSavedFormEditorSnapshot(
  value: unknown,
  options?: { expectedPageCount?: number },
): SavedFormEditorSnapshot | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const version = Number(record.version || 0);
  const pageCount = Number(record.pageCount);
  if (version !== 1 || !Number.isInteger(pageCount) || pageCount < 1) {
    return null;
  }
  if (options?.expectedPageCount && pageCount !== options.expectedPageCount) {
    return null;
  }
  const pageSizes = normalizePageSizes(record.pageSizes, pageCount);
  if (!pageSizes) {
    return null;
  }
  if (!Array.isArray(record.fields)) {
    return null;
  }
  const fields = record.fields
    .map((field) => normalizeField(field))
    .filter((field): field is PdfField => Boolean(field));
  if (fields.length !== record.fields.length) {
    return null;
  }
  return {
    version: 1,
    pageCount,
    pageSizes,
    fields,
    hasRenamedFields: Boolean(record.hasRenamedFields),
    hasMappedSchema: Boolean(record.hasMappedSchema),
  };
}

export function extractSavedFormFillRuleState(
  savedMeta: FillRulesSource | null | undefined,
): SavedFormFillRuleState {
  const savedFillRules = savedMeta?.fillRules && typeof savedMeta.fillRules === 'object'
    ? savedMeta.fillRules
    : null;
  const checkboxRules = Array.isArray(savedFillRules?.checkboxRules)
    ? (savedFillRules.checkboxRules as CheckboxRule[])
    : Array.isArray(savedMeta?.checkboxRules)
      ? (savedMeta.checkboxRules as CheckboxRule[])
      : [];
  const checkboxHints = Array.isArray(savedFillRules?.checkboxHints)
    ? (savedFillRules.checkboxHints as CheckboxHint[])
    : Array.isArray(savedMeta?.checkboxHints)
      ? (savedMeta.checkboxHints as CheckboxHint[])
      : [];
  const textTransformRules = Array.isArray(savedFillRules?.textTransformRules)
    ? (savedFillRules.textTransformRules as TextTransformRule[])
    : Array.isArray((savedFillRules as Record<string, unknown> | null)?.templateRules)
      ? ((savedFillRules as Record<string, unknown>).templateRules as TextTransformRule[])
      : Array.isArray(savedMeta?.textTransformRules)
        ? (savedMeta.textTransformRules as TextTransformRule[])
        : Array.isArray(savedMeta?.templateRules)
          ? (savedMeta.templateRules as TextTransformRule[])
          : [];
  return {
    checkboxRules,
    checkboxHints,
    textTransformRules,
  };
}
