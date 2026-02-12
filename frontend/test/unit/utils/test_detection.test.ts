import { describe, expect, it } from 'vitest';

import { resolveDetectionStatusMessage } from '../../../src/utils/detection';

describe('detection status messaging', () => {
  it('returns the standard CPU final-fields message for running light profile', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'running',
          detectionProfile: 'light',
        },
        15_000,
      ),
    ).toBe('Detecting fields on the standard CPU...');
  });

  it('returns the high-capacity CPU final-fields message for running heavy profile', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'running',
          detectionProfile: 'heavy',
        },
        15_000,
      ),
    ).toBe('Detecting fields on the high-capacity CPU...');
  });

  it('shows queue wait text when detection has been queued beyond threshold', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'queued',
          detectionProfile: 'light',
          detectionQueuedAt: '2026-02-11T00:00:00Z',
        },
        1,
      ),
    ).toBe('Waiting for an available standard CPU...');
  });
});
