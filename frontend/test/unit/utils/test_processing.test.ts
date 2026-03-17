import { describe, expect, it } from 'vitest';

import { resolveProcessingCopy } from '../../../src/utils/processing';

describe('resolveProcessingCopy', () => {
  it('returns case-specific headings and details for each workspace loading path', () => {
    expect(resolveProcessingCopy('detect')).toMatchObject({
      heading: 'Preparing your form…',
      detail: 'Detecting fields and building the editor.',
    });
    expect(resolveProcessingCopy('fillable')).toMatchObject({
      heading: 'Opening your fillable PDF…',
      detail: 'Opening your fillable PDF in the editor.',
    });
    expect(resolveProcessingCopy('saved-form')).toMatchObject({
      heading: 'Loading form…',
      detail: '',
    });
    expect(resolveProcessingCopy('saved-group')).toMatchObject({
      heading: 'Loading form…',
      detail: '',
    });
  });
});
