import type { CheckboxRule, PdfField } from '../types';
import type { FillLinkResponse, FillLinkSummary, PublicFillLinkSubmitResult } from '../services/api';

export const FILL_LINK_RESPONSE_ID_KEY = '__fill_link_response_id';
export const FILL_LINK_LINK_ID_KEY = '__fill_link_link_id';
export const FILL_LINK_RESPONDENT_LABEL_KEY = '__fill_link_respondent_label';
export const FILL_LINK_RESPONDENT_SECONDARY_LABEL_KEY = '__fill_link_respondent_secondary_label';
export const FILL_LINK_SUBMITTED_AT_KEY = '__fill_link_submitted_at';

export function buildFillLinkTemplateFields(fields: PdfField[]) {
  return fields.map((field) => ({
    name: field.name,
    type: field.type,
    page: field.page,
    rect: field.rect,
    groupKey: field.groupKey,
    optionKey: field.optionKey,
    optionLabel: field.optionLabel,
    groupLabel: field.groupLabel,
  }));
}

export function buildFillLinkResponseRows(responses: FillLinkResponse[]) {
  return responses.map((entry) => ({
    ...(entry.answers || {}),
    [FILL_LINK_RESPONSE_ID_KEY]: entry.id,
    [FILL_LINK_LINK_ID_KEY]: entry.linkId,
    [FILL_LINK_RESPONDENT_LABEL_KEY]: entry.respondentLabel,
    [FILL_LINK_RESPONDENT_SECONDARY_LABEL_KEY]: entry.respondentSecondaryLabel ?? '',
    [FILL_LINK_SUBMITTED_AT_KEY]: entry.submittedAt ?? '',
  }));
}

export function fillLinkRespondentPdfDownloadEnabled(
  link: Pick<FillLinkSummary, 'allowRespondentPdfDownload' | 'respondentPdfDownloadEnabled'> | null | undefined,
): boolean {
  if (typeof link?.respondentPdfDownloadEnabled === 'boolean') {
    return link.respondentPdfDownloadEnabled;
  }
  return Boolean(link?.allowRespondentPdfDownload);
}

export function fillLinkRespondentPdfEditableEnabled(
  link: Pick<FillLinkSummary, 'respondentPdfEditableEnabled'> | null | undefined,
): boolean {
  return Boolean(link?.respondentPdfEditableEnabled);
}

export function fillLinkResponseDownloadEnabled(
  result: Pick<PublicFillLinkSubmitResult, 'responseDownloadAvailable' | 'responseDownloadPath' | 'link'>,
): boolean {
  if (result.responseDownloadAvailable) {
    return true;
  }
  if (typeof result.responseDownloadPath === 'string' && result.responseDownloadPath.trim()) {
    return true;
  }
  return fillLinkRespondentPdfDownloadEnabled(result.link);
}

function sortValueMap(valueMap: Record<string, string> | undefined) {
  if (!valueMap) return undefined;
  return Object.fromEntries(
    Object.entries(valueMap).sort(([left], [right]) => left.localeCompare(right)),
  );
}

export function buildFillLinkPublishFingerprint(fields: PdfField[], checkboxRules: CheckboxRule[]): string {
  const normalizedFields = buildFillLinkTemplateFields(fields)
    .map((field) => ({
      name: field.name,
      type: field.type || 'text',
      page: Number.isFinite(field.page) ? field.page : 0,
      rect: {
        x: Number(field.rect?.x || 0),
        y: Number(field.rect?.y || 0),
        width: Number(field.rect?.width || 0),
        height: Number(field.rect?.height || 0),
      },
      groupKey: field.groupKey || '',
      optionKey: field.optionKey || '',
      optionLabel: field.optionLabel || '',
      groupLabel: field.groupLabel || '',
    }))
    .sort((left, right) => {
      if (left.page !== right.page) return left.page - right.page;
      if (left.name !== right.name) return left.name.localeCompare(right.name);
      if (left.rect.y !== right.rect.y) return left.rect.y - right.rect.y;
      if (left.rect.x !== right.rect.x) return left.rect.x - right.rect.x;
      return left.type.localeCompare(right.type);
    });

  const normalizedRules = checkboxRules
    .map((rule) => ({
      databaseField: rule.databaseField || '',
      groupKey: rule.groupKey || '',
      operation: rule.operation,
      trueOption: rule.trueOption || '',
      falseOption: rule.falseOption || '',
      valueMap: sortValueMap(rule.valueMap),
    }))
    .sort((left, right) => {
      if (left.groupKey !== right.groupKey) return left.groupKey.localeCompare(right.groupKey);
      if (left.databaseField !== right.databaseField) {
        return left.databaseField.localeCompare(right.databaseField);
      }
      return left.operation.localeCompare(right.operation);
    });

  return JSON.stringify({
    fields: normalizedFields,
    checkboxRules: normalizedRules,
  });
}
