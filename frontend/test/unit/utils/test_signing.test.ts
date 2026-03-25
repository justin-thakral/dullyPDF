import { describe, expect, it } from 'vitest';
import { buildSigningAnchorsFromFields, hashSourcePdfSha256 } from '../../../src/utils/signing';


describe('buildSigningAnchorsFromFields', () => {
  it('returns signature and signed-date anchors from supported fields', () => {
    const anchors = buildSigningAnchorsFromFields([
      {
        id: 'sig-1',
        name: 'signature_primary',
        type: 'signature',
        page: 2,
        rect: { x: 10, y: 20, width: 100, height: 30 },
      },
      {
        id: 'date-1',
        name: 'sign_date',
        type: 'date',
        page: 2,
        rect: { x: 130, y: 20, width: 90, height: 24 },
      },
      {
        id: 'text-1',
        name: 'client_name',
        type: 'text',
        page: 1,
        rect: { x: 10, y: 60, width: 180, height: 24 },
      },
    ]);

    expect(anchors).toEqual([
      {
        kind: 'signature',
        page: 2,
        rect: { x: 10, y: 20, width: 100, height: 30 },
        fieldId: 'sig-1',
        fieldName: 'signature_primary',
      },
      {
        kind: 'signed_date',
        page: 2,
        rect: { x: 130, y: 20, width: 90, height: 24 },
        fieldId: 'date-1',
        fieldName: 'sign_date',
      },
    ]);
  });
});

describe('hashSourcePdfSha256', () => {
  it('returns a lowercase hex digest for PDF bytes', async () => {
    const digest = await hashSourcePdfSha256(new Uint8Array([1, 2, 3, 4]));

    expect(digest).toBe('9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a');
  });
});
