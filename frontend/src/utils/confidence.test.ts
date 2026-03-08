import { describe, expect, it } from 'vitest';

import {
  CONFIDENCE_THRESHOLDS,
  confidenceTierForConfidence,
} from './confidence';

describe('confidence thresholds', () => {
  it('uses the lowered confidence cutoffs', () => {
    expect(CONFIDENCE_THRESHOLDS.high).toBe(0.6);
    expect(CONFIDENCE_THRESHOLDS.low).toBe(0.3);
  });

  it('maps values at the new boundaries into the expected tiers', () => {
    expect(confidenceTierForConfidence(0.6)).toBe('high');
    expect(confidenceTierForConfidence(0.599)).toBe('medium');
    expect(confidenceTierForConfidence(0.3)).toBe('medium');
    expect(confidenceTierForConfidence(0.299)).toBe('low');
  });
});
