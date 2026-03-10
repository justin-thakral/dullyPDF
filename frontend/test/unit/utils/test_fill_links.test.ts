import { describe, expect, it } from 'vitest';
import type { PdfField } from '../../../src/types';
import {
  buildFillLinkPublishFingerprint,
  buildFillLinkResponseRows,
  FILL_LINK_RESPONSE_ID_KEY,
  FILL_LINK_RESPONDENT_LABEL_KEY,
  FILL_LINK_RESPONDENT_SECONDARY_LABEL_KEY,
  FILL_LINK_SUBMITTED_AT_KEY,
  fillLinkRespondentPdfDownloadEnabled,
  fillLinkResponseDownloadEnabled,
} from '../../../src/utils/fillLinks';

function createField(name: string, x: number): PdfField {
  return {
    id: `${name}-${x}`,
    name,
    type: 'text',
    page: 1,
    rect: { x, y: 10, width: 120, height: 20 },
    value: null,
  };
}

describe('fillLinks utils', () => {
  it('stores internal response metadata under collision-safe keys', () => {
    const rows = buildFillLinkResponseRows([
      {
        id: 'resp-1',
        linkId: 'link-1',
        templateId: 'tpl-1',
        respondentLabel: 'Ada Lovelace',
        respondentSecondaryLabel: 'ada@example.com',
        submittedAt: '2026-03-10T12:00:00.000Z',
        answers: {
          __fill_link_response_id: 'user-value',
          __fill_link_respondent_label: 'custom label',
          submitted_at: 'user submitted at',
        },
      },
    ]);

    expect(rows).toEqual([
      expect.objectContaining({
        __fill_link_response_id: 'resp-1',
        __fill_link_respondent_label: 'Ada Lovelace',
        __fill_link_respondent_secondary_label: 'ada@example.com',
        __fill_link_submitted_at: '2026-03-10T12:00:00.000Z',
        submitted_at: 'user submitted at',
      }),
    ]);
    expect(rows[0][FILL_LINK_RESPONSE_ID_KEY]).toBe('resp-1');
    expect(rows[0][FILL_LINK_RESPONDENT_LABEL_KEY]).toBe('Ada Lovelace');
    expect(rows[0][FILL_LINK_RESPONDENT_SECONDARY_LABEL_KEY]).toBe('ada@example.com');
    expect(rows[0][FILL_LINK_SUBMITTED_AT_KEY]).toBe('2026-03-10T12:00:00.000Z');
  });

  it('builds a stable publish fingerprint regardless of field or rule order', () => {
    const firstFingerprint = buildFillLinkPublishFingerprint(
      [createField('last_name', 40), createField('first_name', 10)],
      [
        { groupKey: 'yes_no', databaseField: 'consent', operation: 'boolean', trueOption: 'yes' },
        { groupKey: 'subscribe', databaseField: 'subscribe', operation: 'list', valueMap: { y: 'Yes', n: 'No' } },
      ],
    );
    const secondFingerprint = buildFillLinkPublishFingerprint(
      [createField('first_name', 10), createField('last_name', 40)],
      [
        { groupKey: 'subscribe', databaseField: 'subscribe', operation: 'list', valueMap: { n: 'No', y: 'Yes' } },
        { groupKey: 'yes_no', databaseField: 'consent', operation: 'boolean', trueOption: 'yes' },
      ],
    );
    const changedFingerprint = buildFillLinkPublishFingerprint(
      [createField('first_name', 11), createField('last_name', 40)],
      [
        { groupKey: 'yes_no', databaseField: 'consent', operation: 'boolean', trueOption: 'yes' },
      ],
    );

    expect(firstFingerprint).toBe(secondFingerprint);
    expect(changedFingerprint).not.toBe(firstFingerprint);
  });

  it('normalizes respondent download availability from link and submit payload fallbacks', () => {
    expect(fillLinkRespondentPdfDownloadEnabled({
      allowRespondentPdfDownload: true,
    })).toBe(true);
    expect(fillLinkRespondentPdfDownloadEnabled({
      respondentPdfDownloadEnabled: true,
    })).toBe(true);
    expect(fillLinkRespondentPdfDownloadEnabled({
      allowRespondentPdfDownload: false,
      respondentPdfDownloadEnabled: true,
    })).toBe(true);

    expect(fillLinkResponseDownloadEnabled({
      responseDownloadAvailable: true,
      responseDownloadPath: null,
      link: { status: 'active' },
    })).toBe(true);
    expect(fillLinkResponseDownloadEnabled({
      responseDownloadAvailable: false,
      responseDownloadPath: '/download/path',
      link: { status: 'active' },
    })).toBe(true);
    expect(fillLinkResponseDownloadEnabled({
      responseDownloadAvailable: false,
      responseDownloadPath: null,
      link: { status: 'active', respondentPdfDownloadEnabled: true },
    })).toBe(true);
  });
});
