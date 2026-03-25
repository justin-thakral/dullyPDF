import type { PdfField } from '../types';
import { rectToBox } from './coords';
import { normaliseFieldType } from './detection';
import { ensureUniqueFieldName } from './fields';
import { parseConfidence } from './confidence';

const HTML_FALLBACK_RE = /^\s*(<!doctype html|<html|<head|<body)\b/i;
function expectedAssetLabel(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.pdf')) return 'a PDF';
  if (lower.endsWith('.json')) return 'JSON';
  if (lower.endsWith('.csv')) return 'CSV';
  return 'the expected asset payload';
}

async function readBlobText(blob: Blob): Promise<string> {
  const candidate = blob as Blob & { text?: () => Promise<string> };
  if (typeof candidate.text === 'function') {
    return await candidate.text();
  }
  if (typeof FileReader !== 'undefined') {
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error || new Error('Failed to read blob text.'));
      reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
      reader.readAsText(blob);
    });
  }
  if (typeof Response !== 'undefined') {
    return await new Response(blob).text();
  }
  throw new Error('Blob text reading is not supported in this environment.');
}

function buildFieldId(raw: Record<string, unknown>, index: number, usedIds: Set<string>): string {
  const baseId = String(raw.id || raw.candidateId || raw.name || `demo_field_${index + 1}`).trim() || `demo_field_${index + 1}`;
  let candidate = baseId;
  let suffix = 2;
  while (usedIds.has(candidate)) {
    candidate = `${baseId}_${suffix}`;
    suffix += 1;
  }
  usedIds.add(candidate);
  return candidate;
}

export async function validateDemoAssetBlob(filename: string, blob: Blob): Promise<void> {
  const rawText = await readBlobText(blob);
  const preview = rawText.slice(0, 512);
  const lowerPreview = preview.toLowerCase();
  if (
    HTML_FALLBACK_RE.test(preview) ||
    lowerPreview.includes('<!doctype html') ||
    lowerPreview.includes('<html') ||
    lowerPreview.includes('<head') ||
    lowerPreview.includes('<body')
  ) {
    throw new Error(`Demo asset returned HTML instead of ${expectedAssetLabel(filename)}: ${filename}`);
  }

  const lower = filename.toLowerCase();
  if (lower.endsWith('.pdf')) {
    const header = rawText.slice(0, 8);
    if (!header.startsWith('%PDF-')) {
      throw new Error(`Demo asset is not a valid PDF: ${filename}`);
    }
    return;
  }

  if (lower.endsWith('.json')) {
    const trimmed = preview.trimStart();
    if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) {
      throw new Error(`Demo asset is not valid JSON: ${filename}`);
    }
  }
}

export function parseDemoFieldFixture(rawFixture: unknown, filename = 'demo field fixture'): PdfField[] {
  const rawFields = Array.isArray(rawFixture)
    ? rawFixture
    : Array.isArray((rawFixture as { fields?: unknown[] } | null | undefined)?.fields)
      ? (rawFixture as { fields: unknown[] }).fields
      : null;
  if (!rawFields) {
    throw new Error(`Invalid demo field fixture: ${filename}`);
  }

  const usedNames = new Set<string>();
  const usedIds = new Set<string>();

  return rawFields.map((entry, index) => {
    if (!entry || typeof entry !== 'object') {
      throw new Error(`Invalid demo field entry at index ${index} in ${filename}`);
    }

    const rawField = entry as Record<string, unknown>;
    const rect = rectToBox(rawField.rect || rawField.bbox);
    if (!rect || rect.width <= 0 || rect.height <= 0) {
      throw new Error(`Invalid demo field rect at index ${index} in ${filename}`);
    }

    const baseName = String(rawField.name || `demo_field_${index + 1}`).trim() || `demo_field_${index + 1}`;
    const name = ensureUniqueFieldName(baseName, usedNames);

    return {
      id: buildFieldId(rawField, index, usedIds),
      name,
      type: normaliseFieldType(rawField.type),
      page: Math.max(1, Number(rawField.page) || 1),
      rect,
      fieldConfidence: parseConfidence(rawField.fieldConfidence ?? rawField.confidence),
      renameConfidence: parseConfidence(rawField.renameConfidence),
      mappingConfidence: parseConfidence(rawField.mappingConfidence),
      groupKey: typeof rawField.groupKey === 'string' ? rawField.groupKey : undefined,
      optionKey: typeof rawField.optionKey === 'string' ? rawField.optionKey : undefined,
      optionLabel: typeof rawField.optionLabel === 'string' ? rawField.optionLabel : undefined,
      groupLabel: typeof rawField.groupLabel === 'string' ? rawField.groupLabel : undefined,
      radioGroupId: typeof rawField.radioGroupId === 'string' ? rawField.radioGroupId : undefined,
      radioGroupKey: typeof rawField.radioGroupKey === 'string' ? rawField.radioGroupKey : undefined,
      radioGroupLabel: typeof rawField.radioGroupLabel === 'string' ? rawField.radioGroupLabel : undefined,
      radioOptionKey: typeof rawField.radioOptionKey === 'string' ? rawField.radioOptionKey : undefined,
      radioOptionLabel: typeof rawField.radioOptionLabel === 'string' ? rawField.radioOptionLabel : undefined,
      radioOptionOrder: typeof rawField.radioOptionOrder === 'number' ? rawField.radioOptionOrder : undefined,
      radioGroupSource: typeof rawField.radioGroupSource === 'string' ? rawField.radioGroupSource as PdfField['radioGroupSource'] : undefined,
    } satisfies PdfField;
  });
}
