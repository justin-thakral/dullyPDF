/**
 * Confidence parsing and tiering helpers for detection and mapping.
 */
import type { ConfidenceTier, PdfField } from '../types';

export const CONFIDENCE_THRESHOLDS = {
  high: 0.6,
  low: 0.3,
} as const;

function clamp01(value: number) {
  if (Number.isNaN(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

export function parseConfidence(raw: unknown): number | undefined {
  if (raw === null || raw === undefined) return undefined;
  const value = typeof raw === 'number' ? raw : Number(String(raw).trim());
  if (Number.isNaN(value)) return undefined;
  if (value >= 2) {
    return clamp01(value / 100);
  }
  return clamp01(value);
}

export function fieldConfidenceForField(field: PdfField): number | undefined {
  return typeof field.fieldConfidence === 'number' ? field.fieldConfidence : undefined;
}

export function nameConfidenceForField(field: PdfField): number | undefined {
  if (typeof field.mappingConfidence === 'number') return field.mappingConfidence;
  if (typeof field.renameConfidence === 'number') return field.renameConfidence;
  return undefined;
}

export function hasAnyConfidence(field: PdfField): boolean {
  return fieldConfidenceForField(field) !== undefined || nameConfidenceForField(field) !== undefined;
}

export function effectiveConfidenceForField(field: PdfField): number | undefined {
  return fieldConfidenceForField(field) ?? nameConfidenceForField(field);
}

export function confidenceTierForConfidence(confidence: number): ConfidenceTier {
  if (confidence >= CONFIDENCE_THRESHOLDS.high) return 'high';
  if (confidence >= CONFIDENCE_THRESHOLDS.low) return 'medium';
  return 'low';
}

export function confidenceTierForField(field: PdfField): ConfidenceTier {
  const confidence = effectiveConfidenceForField(field);
  if (confidence === undefined) return 'high';
  return confidenceTierForConfidence(confidence);
}

export function fieldConfidenceTierForField(field: PdfField): ConfidenceTier {
  const confidence = fieldConfidenceForField(field);
  if (confidence === undefined) return 'high';
  return confidenceTierForConfidence(confidence);
}

export function nameConfidenceTierForField(field: PdfField): ConfidenceTier | null {
  const confidence = nameConfidenceForField(field);
  if (confidence === undefined) return null;
  return confidenceTierForConfidence(confidence);
}

/**
 * Estimate confidence for a rename mapping based on string similarity.
 */
export function deriveMappingConfidence(originalName: string, nextName: string): number {
  const normalise = (value: string) =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  const left = normalise(originalName);
  const right = normalise(nextName);
  if (!left || !right) return 0.7;
  if (left === right) return 0.95;
  if (left.includes(right) || right.includes(left)) return 0.85;
  return 0.7;
}
