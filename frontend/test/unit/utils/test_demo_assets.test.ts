import { describe, expect, it } from 'vitest';

import { parseDemoFieldFixture, validateDemoAssetBlob } from '../../../src/utils/demoAssets';

describe('demoAssets', () => {
  it('parses a committed demo field fixture payload', () => {
    const fields = parseDemoFieldFixture({
      fields: [
        {
          id: 'commonforms_1_1',
          name: 'commonforms_text_p1_1',
          type: 'text',
          page: 1,
          rect: { x: 10, y: 20, width: 120, height: 24 },
          fieldConfidence: 0.91,
        },
      ],
    }, 'demo.json');

    expect(fields).toEqual([
      expect.objectContaining({
        id: 'commonforms_1_1',
        name: 'commonforms_text_p1_1',
        type: 'text',
        fieldConfidence: 0.91,
      }),
    ]);
  });

  it('rejects invalid fixture rows without geometry', () => {
    expect(() => parseDemoFieldFixture([{ id: 'bad', name: 'bad' }], 'broken.json')).toThrow(
      'Invalid demo field rect',
    );
  });

  it('rejects html fallback responses for PDF assets', async () => {
    const blob = new Blob(['<!doctype html><html><body>missing</body></html>'], { type: 'text/html' });
    await expect(validateDemoAssetBlob('broken.pdf', blob)).rejects.toThrow(
      'Demo asset returned HTML instead of a PDF',
    );
  });

  it('rejects invalid JSON payloads', async () => {
    const blob = new Blob(['not-json'], { type: 'application/json' });
    await expect(validateDemoAssetBlob('broken.json', blob)).rejects.toThrow(
      'Demo asset is not valid JSON',
    );
  });
});
