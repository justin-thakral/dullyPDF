import { describe, expect, it } from 'vitest';

import type { PdfField } from '../../../src/types';
import {
  CONFIDENCE_THRESHOLDS,
  confidenceTierForConfidence,
  confidenceTierForField,
  effectiveConfidenceForField,
  fieldConfidenceForField,
  fieldConfidenceTierForField,
  hasAnyConfidence,
  nameConfidenceForField,
  nameConfidenceTierForField,
  parseConfidence,
} from '../../../src/utils/confidence';

const makeField = (overrides: Partial<PdfField> = {}): PdfField => ({
  id: 'field-1',
  name: 'sample',
  type: 'text',
  page: 0,
  rect: { x: 0, y: 0, width: 10, height: 10 },
  ...overrides,
});

describe('confidence utils', () => {
  describe('parseConfidence', () => {
    it('parses numbers and clamps to the [0, 1] range', () => {
      expect(parseConfidence(0)).toBe(0);
      expect(parseConfidence(0.72)).toBe(0.72);
      expect(parseConfidence(-0.5)).toBe(0);
      expect(parseConfidence(150)).toBe(1);
    });

    it('parses trimmed strings and percent-like values', () => {
      expect(parseConfidence(' 0.8 ')).toBe(0.8);
      expect(parseConfidence('80')).toBe(0.8);
      expect(parseConfidence('  250  ')).toBe(1);
    });

    it('clamps values between 1 and 2 to 1.0 instead of treating as percentages', () => {
      expect(parseConfidence(1.0)).toBe(1);
      expect(parseConfidence(1.2)).toBe(1);
      expect(parseConfidence(1.5)).toBe(1);
      expect(parseConfidence(1.99)).toBe(1);
    });

    it('returns undefined for nullish and non-numeric values', () => {
      expect(parseConfidence(null)).toBeUndefined();
      expect(parseConfidence(undefined)).toBeUndefined();
      expect(parseConfidence(Number.NaN)).toBeUndefined();
      expect(parseConfidence('not-a-number')).toBeUndefined();
      expect(parseConfidence({ value: 0.5 })).toBeUndefined();
    });
  });

  describe('confidence precedence helpers', () => {
    it('reads field confidence only from numeric fieldConfidence', () => {
      expect(fieldConfidenceForField(makeField({ fieldConfidence: 0.91 }))).toBe(0.91);
      expect(fieldConfidenceForField(makeField({ fieldConfidence: undefined }))).toBeUndefined();
    });

    it('prefers mapping confidence over rename confidence for name confidence', () => {
      expect(nameConfidenceForField(makeField({ mappingConfidence: 0.88, renameConfidence: 0.33 }))).toBe(
        0.88,
      );
      expect(nameConfidenceForField(makeField({ renameConfidence: 0.44 }))).toBe(0.44);
      expect(nameConfidenceForField(makeField())).toBeUndefined();
    });

    it('detects any confidence and picks effective confidence with field priority', () => {
      expect(hasAnyConfidence(makeField())).toBe(false);
      expect(hasAnyConfidence(makeField({ renameConfidence: 0.42 }))).toBe(true);
      expect(hasAnyConfidence(makeField({ fieldConfidence: 0.55 }))).toBe(true);

      expect(
        effectiveConfidenceForField(makeField({ fieldConfidence: 0.61, mappingConfidence: 0.99 })),
      ).toBe(0.61);
      expect(effectiveConfidenceForField(makeField({ mappingConfidence: 0.73 }))).toBe(0.73);
      expect(effectiveConfidenceForField(makeField())).toBeUndefined();
    });
  });

  describe('tier helpers', () => {
    it('uses configured thresholds for direct confidence values', () => {
      expect(CONFIDENCE_THRESHOLDS).toEqual({ high: 0.8, low: 0.65 });
      expect(confidenceTierForConfidence(0.8)).toBe('high');
      expect(confidenceTierForConfidence(0.7999)).toBe('medium');
      expect(confidenceTierForConfidence(0.65)).toBe('medium');
      expect(confidenceTierForConfidence(0.6499)).toBe('low');
    });

    it('returns high by default when effective or field confidence is missing', () => {
      expect(confidenceTierForField(makeField())).toBe('high');
      expect(fieldConfidenceTierForField(makeField())).toBe('high');
    });

    it('computes effective, field-only, and name-only tiers independently', () => {
      const field = makeField({
        fieldConfidence: 0.6,
        mappingConfidence: 0.95,
      });

      expect(confidenceTierForField(field)).toBe('low');
      expect(fieldConfidenceTierForField(field)).toBe('low');
      expect(nameConfidenceTierForField(field)).toBe('high');

      expect(nameConfidenceTierForField(makeField())).toBeNull();
      expect(nameConfidenceTierForField(makeField({ renameConfidence: 0.7 }))).toBe('medium');
    });
  });
});
