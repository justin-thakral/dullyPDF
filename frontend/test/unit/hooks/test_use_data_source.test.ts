import { describe, expect, it } from 'vitest';

import { validateSchemaImportFileSize } from '../../../src/hooks/useDataSource';

const TEN_MB = 10 * 1024 * 1024;

function buildFile(size: number, name = 'schema.csv'): File {
  return new File([new Uint8Array(size)], name, { type: 'text/csv' });
}

describe('validateSchemaImportFileSize', () => {
  it('accepts files up to the 10MB structured import cap', () => {
    expect(() => validateSchemaImportFileSize(buildFile(TEN_MB))).not.toThrow();
  });

  it('rejects files larger than the 10MB structured import cap', () => {
    expect(() => validateSchemaImportFileSize(buildFile(TEN_MB + 1))).toThrow(
      'Schema import files must be 10MB or smaller.',
    );
  });
});
