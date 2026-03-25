import type { PdfField } from '../types';
import type { SigningAnchorPayload, SigningRequestSourceType } from '../services/api';

export type ReviewedFillContext = {
  sourceType: SigningRequestSourceType;
  sourceId?: string | null;
  sourceLinkId?: string | null;
  sourceRecordLabel?: string | null;
  reviewedAt: string;
  sourceLabel?: string | null;
};

function looksLikeSignedDateField(field: PdfField): boolean {
  const normalizedName = String(field.name || '').trim().toLowerCase();
  if (field.type !== 'date') return false;
  return normalizedName.includes('sign') && normalizedName.includes('date');
}

export function buildSigningAnchorsFromFields(fields: PdfField[]): SigningAnchorPayload[] {
  return fields.flatMap<SigningAnchorPayload>((field) => {
    if (field.type === 'signature') {
      return [{
        kind: 'signature',
        page: field.page,
        rect: field.rect,
        fieldId: field.id,
        fieldName: field.name,
      }];
    }
    if (looksLikeSignedDateField(field)) {
      return [{
        kind: 'signed_date',
        page: field.page,
        rect: field.rect,
        fieldId: field.id,
        fieldName: field.name,
      }];
    }
    return [];
  });
}

function fieldValueIsMeaningful(field: PdfField): boolean {
  if (field.type === 'checkbox') {
    return field.value === true || field.value === 'true';
  }
  if (field.value === null || field.value === undefined) {
    return false;
  }
  const normalized = String(field.value).trim();
  return normalized.length > 0;
}

export function hasMeaningfulFillValues(fields: PdfField[]): boolean {
  return fields.some((field) => fieldValueIsMeaningful(field));
}

export async function hashSourcePdfSha256(bytes: Uint8Array | ArrayBuffer): Promise<string> {
  const sourceBytes = bytes instanceof Uint8Array
    ? new Uint8Array(bytes)
    : new Uint8Array(bytes);
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error('Web Crypto is unavailable in this browser context.');
  }
  const digest = await subtle.digest('SHA-256', sourceBytes);
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');
}
