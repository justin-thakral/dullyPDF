/**
 * Field helpers for creation, naming, and formatting.
 */
import type { FieldRect, FieldType, PageSize, PdfField } from '../types';
import { clampRectToPage } from './coords';

// Defaults mirror common form dimensions so new fields feel usable immediately.
const DEFAULT_SIZES: Record<FieldType, FieldRect> = {
  text: { x: 0, y: 0, width: 180, height: 22 },
  date: { x: 0, y: 0, width: 120, height: 22 },
  signature: { x: 0, y: 0, width: 220, height: 32 },
  checkbox: { x: 0, y: 0, width: 14, height: 14 },
};

const MIN_SIZES: Record<FieldType, number> = {
  text: 12,
  date: 12,
  signature: 16,
  checkbox: 12,
};

// Base naming keeps field lists readable while still ensuring unique identifiers.
const NAME_BASES: Record<FieldType, string> = {
  text: 'text_field',
  date: 'date_field',
  signature: 'signature',
  checkbox: 'i_checkbox',
};

function nextName(base: string, existing: Set<string>) {
  let index = 1;
  while (existing.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

export function ensureUniqueFieldName(baseName: string, existing: Set<string>) {
  const normalized = baseName.trim() || 'field';
  if (!existing.has(normalized)) {
    existing.add(normalized);
    return normalized;
  }
  const unique = nextName(normalized, existing);
  existing.add(unique);
  return unique;
}

export function getDefaultFieldRect(type: FieldType): FieldRect {
  const template = DEFAULT_SIZES[type] ?? DEFAULT_SIZES.text;
  return { ...template };
}

export function getMinFieldSize(type: FieldType): number {
  return MIN_SIZES[type] ?? MIN_SIZES.text;
}

export function normalizeRectForFieldType(rect: FieldRect, type: FieldType, pageSize: PageSize): FieldRect {
  const minSize = getMinFieldSize(type);
  if (type === 'checkbox') {
    const side = Math.max(rect.width, rect.height, getDefaultFieldRect('checkbox').width, minSize);
    return clampRectToPage(
      {
        x: rect.x,
        y: rect.y,
        width: side,
        height: side,
      },
      pageSize,
      minSize,
    );
  }

  return clampRectToPage(
    {
      x: rect.x,
      y: rect.y,
      width: Math.max(rect.width, minSize),
      height: Math.max(rect.height, minSize),
    },
    pageSize,
    minSize,
  );
}

export function createFieldWithRect(
  type: FieldType,
  page: number,
  pageSize: PageSize,
  existingFields: PdfField[],
  rect: FieldRect,
): PdfField {
  const existingNames = new Set(existingFields.map((field) => field.name));
  const base = NAME_BASES[type] || 'field';
  const name = ensureUniqueFieldName(base, existingNames);
  const normalizedRect = normalizeRectForFieldType(rect, type, pageSize);

  return {
    id: makeId(),
    name,
    type,
    page,
    rect: normalizedRect,
  };
}

export function createField(
  type: FieldType,
  page: number,
  pageSize: PageSize,
  existingFields: PdfField[],
): PdfField {
  const template = getDefaultFieldRect(type);
  // Start fields near the page center and clamp to the page bounds to avoid off-page geometry.
  const centeredRect = clampRectToPage(
    {
      x: Math.max(0, pageSize.width / 2 - template.width / 2),
      y: Math.max(0, pageSize.height / 2 - template.height / 2),
      width: template.width,
      height: template.height,
    },
    pageSize,
  );
  return createFieldWithRect(type, page, pageSize, existingFields, centeredRect);
}

export function makeId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `field_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function formatSize(rect: FieldRect) {
  return `${Math.round(rect.width)} x ${Math.round(rect.height)}`;
}

/**
 * Convert raw filenames into a display-friendly saved form name.
 */
export function normaliseFormName(raw: string | null | undefined): string {
  const trimmed = String(raw || '').trim();
  if (!trimmed.length) return 'Saved form';
  return trimmed.replace(/\.pdf$/i, '');
}

/**
 * Normalize values so fillable PDFs receive consistent defaults.
 */
function normaliseFieldValueForMaterialize(field: PdfField): PdfField['value'] {
  const value = field.value;
  if (field.type === 'checkbox') {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string' && value.trim().length === 0) return false;
    return value;
  }
  if (value === null || value === undefined) return '';
  if (typeof value === 'string' && value.trim().length === 0) return '';
  return value;
}

/**
 * Build the minimal template-field payload sent to the backend for session
 * registration and OpenAI rename / mapping calls.
 */
export function buildTemplateFields(sourceFields: PdfField[]) {
  return sourceFields.map((field) => ({
    name: field.name, type: field.type, page: field.page, rect: field.rect,
    groupKey: field.groupKey, optionKey: field.optionKey,
    optionLabel: field.optionLabel, groupLabel: field.groupLabel,
  }));
}

/**
 * Apply value normalization across all fields before materialization.
 */
export function prepareFieldsForMaterialize(fields: PdfField[]): PdfField[] {
  return fields.map((field) => {
    const value = normaliseFieldValueForMaterialize(field);
    return value === field.value ? field : { ...field, value };
  });
}
