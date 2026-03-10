import { describe, expect, it } from 'vitest';

import { resolveDetectionStatusMessage } from '../../../src/utils/detection';

describe('detection status messaging', () => {
  it('returns the standard CPU final-fields message for running light profile', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'running',
          detectionProfile: 'light',
          detectionServiceUrl: 'https://dullypdf-detector-light-abc.a.run.app',
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
          detectionServiceUrl: 'https://dullypdf-detector-heavy-abc.a.run.app',
        },
        15_000,
      ),
    ).toBe('Detecting fields on the high-capacity CPU...');
  });

  it('returns the GPU message when the active detector service is GPU-backed', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'running',
          detectionProfile: 'light',
          detectionServiceUrl: 'https://dullypdf-detector-light-gpu-abc.a.run.app',
        },
        15_000,
      ),
    ).toBe('Detecting fields on the GPU...');
  });

  it('shows queue wait text when detection has been queued beyond threshold', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'queued',
          detectionProfile: 'light',
          detectionQueuedAt: '2026-02-11T00:00:00Z',
          detectionServiceUrl: 'https://dullypdf-detector-light-abc.a.run.app',
        },
        1,
      ),
    ).toBe('Waiting for an available standard CPU...');
  });

  it('falls back to neutral detector messaging when runtime is still unknown', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'queued',
        },
        15_000,
      ),
    ).toBe('Waiting for detector to start...');
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'running',
          detectionProfile: 'light',
        },
        15_000,
      ),
    ).toBe('Detecting fields...');
  });

  it('prefers the sanitized detectionRuntime field when service URLs are not exposed', () => {
    expect(
      resolveDetectionStatusMessage(
        {
          status: 'running',
          detectionProfile: 'light',
          detectionRuntime: 'gpu',
        },
        15_000,
      ),
    ).toBe('Detecting fields on the GPU...');
  });
});
