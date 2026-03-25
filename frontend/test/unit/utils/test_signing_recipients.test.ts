import { describe, expect, it } from 'vitest';

import {
  buildFallbackRecipientName,
  mergeSigningRecipients,
  parseSigningRecipientsFromFile,
  parseSigningRecipientsFromText,
} from '../../../src/utils/signingRecipients';

describe('signingRecipients', () => {
  it('derives a readable fallback name from the email local part', () => {
    expect(buildFallbackRecipientName('ada_lovelace@example.com')).toBe('Ada Lovelace');
    expect(buildFallbackRecipientName('grace-hopper@example.com')).toBe('Grace Hopper');
  });

  it('parses mixed pasted recipient formats and de-dupes by email', () => {
    const result = parseSigningRecipientsFromText(
      [
        'Ada Lovelace <ada@example.com>',
        'Taylor Example,taylor@example.com',
        'grace_hopper@example.com',
        'Taylor Example,taylor@example.com',
        'not-an-email',
      ].join('\n'),
      { source: 'paste' },
    );

    expect(result.recipients).toEqual([
      { name: 'Ada Lovelace', email: 'ada@example.com', source: 'paste' },
      { name: 'Taylor Example', email: 'taylor@example.com', source: 'paste' },
      { name: 'Grace Hopper', email: 'grace_hopper@example.com', source: 'paste' },
    ]);
    expect(result.rejected).toEqual(['not-an-email']);
  });

  it('parses csv files, skips the email header row, and preserves file source labels', async () => {
    const file = new File(
      [
        'name,email\n'
        + 'Ada Lovelace,ada@example.com\n'
        + 'grace_hopper@example.com,Grace Hopper\n',
      ],
      'signers.csv',
      { type: 'text/csv' },
    );
    Object.defineProperty(file, 'text', {
      configurable: true,
      value: () => Promise.resolve(
        'name,email\n'
        + 'Ada Lovelace,ada@example.com\n'
        + 'grace_hopper@example.com,Grace Hopper\n',
      ),
    });

    const result = await parseSigningRecipientsFromFile(file);

    expect(result.recipients).toEqual([
      { name: 'Ada Lovelace', email: 'ada@example.com', source: 'file' },
      { name: 'Grace Hopper', email: 'grace_hopper@example.com', source: 'file' },
    ]);
    expect(result.rejected).toEqual([]);
  });

  it('merges recipients without duplicating the same email', () => {
    const merged = mergeSigningRecipients(
      [{ name: 'Ada Lovelace', email: 'ada@example.com', source: 'manual' }],
      [
        { name: '', email: 'ADA@example.com', source: 'paste' },
        { name: 'Grace Hopper', email: 'grace@example.com', source: 'paste' },
      ],
    );

    expect(merged).toEqual([
      { name: 'Ada Lovelace', email: 'ada@example.com', source: 'manual' },
      { name: 'Grace Hopper', email: 'grace@example.com', source: 'paste' },
    ]);
  });
});
