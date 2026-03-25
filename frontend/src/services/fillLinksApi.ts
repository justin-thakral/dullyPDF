/**
 * Dedicated API service for Fill By Link endpoints.
 */
import type { TextTransformRule } from '../types';
import { apiFetch, apiJsonFetch } from './apiConfig';

type AbortableRequestOptions = {
  signal?: AbortSignal;
};

function buildAbortOptions(signal?: AbortSignal): AbortableRequestOptions {
  return signal ? { signal } : {};
}

function buildFillLinkSubmitAttemptId(): string {
  const cryptoApi =
    typeof globalThis !== 'undefined' && typeof globalThis.crypto !== 'undefined'
      ? globalThis.crypto
      : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  const randomSuffix = Math.random().toString(36).slice(2, 12);
  return `fill_link_${Date.now()}_${randomSuffix}`;
}

function parseDownloadFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) return null;
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const quotedMatch = contentDisposition.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }
  const bareMatch = contentDisposition.match(/filename=([^;]+)/i);
  return bareMatch?.[1]?.trim() || null;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FillLinkQuestionOption = {
  key: string;
  label: string;
};

export type FillLinkQuestion = {
  id?: string;
  key: string;
  label?: string;
  type: 'text' | 'textarea' | 'date' | 'boolean' | 'radio' | 'multi_select' | 'select' | 'email' | 'phone' | string;
  sourceType?: 'pdf_field' | 'checkbox_group' | 'custom' | 'synthetic' | string;
  requiredForRespondentIdentity?: boolean;
  required?: boolean;
  synthetic?: boolean;
  visible?: boolean;
  maxLength?: number | null;
  placeholder?: string | null;
  helpText?: string | null;
  order?: number;
  sourceField?: string;
  groupKey?: string;
  options?: FillLinkQuestionOption[];
};

export type FillLinkWebFormConfig = {
  schemaVersion?: number;
  introText?: string | null;
  defaultTextMaxLength?: number | null;
  questions?: FillLinkQuestion[];
};

export type FillLinkSigningConfig = {
  enabled?: boolean;
  signatureMode?: 'business' | 'consumer';
  documentCategory?: string | null;
  documentCategoryLabel?: string | null;
  manualFallbackEnabled?: boolean;
  signerNameQuestionKey?: string | null;
  signerEmailQuestionKey?: string | null;
};

export type FillLinkSummary = {
  id?: string;
  scopeType?: 'template' | 'group' | string;
  templateId?: string;
  templateName?: string | null;
  groupId?: string | null;
  groupName?: string | null;
  templateIds?: string[];
  title?: string | null;
  status: 'active' | 'closed' | string;
  closedReason?: string | null;
  statusMessage?: string | null;
  responseCount?: number;
  maxResponses?: number;
  createdAt?: string | null;
  updatedAt?: string | null;
  publishedAt?: string | null;
  closedAt?: string | null;
  publicToken?: string;
  publicPath?: string;
  canAcceptResponses?: boolean;
  requireAllFields?: boolean;
  allowRespondentPdfDownload?: boolean;
  respondentPdfDownloadEnabled?: boolean;
  respondentPdfEditableEnabled?: boolean;
  introText?: string | null;
  webFormConfig?: FillLinkWebFormConfig | null;
  signingConfig?: FillLinkSigningConfig | null;
  postSubmitSigningEnabled?: boolean;
  questions?: FillLinkQuestion[];
};

export type FillLinkResponse = {
  id: string;
  linkId: string;
  scopeType?: 'template' | 'group' | string;
  templateId?: string | null;
  groupId?: string | null;
  respondentLabel: string;
  respondentSecondaryLabel?: string | null;
  submittedAt?: string | null;
  answers: Record<string, unknown>;
  signingRequestId?: string | null;
  signingStatus?: string | null;
  signingPublicPath?: string | null;
  signingCompletedAt?: string | null;
  linkedSigning?: {
    requestId: string;
    status?: string | null;
    completedAt?: string | null;
    manualFallbackRequestedAt?: string | null;
    publicPath?: string | null;
    artifacts?: {
      sourcePdf?: { available?: boolean; downloadPath?: string | null } | null;
      signedPdf?: { available?: boolean; downloadPath?: string | null } | null;
      auditReceipt?: { available?: boolean; downloadPath?: string | null } | null;
    } | null;
  } | null;
};

export type FillLinkTemplateFieldPayload = {
  name: string;
  type?: string;
  page?: number;
  rect?: { x: number; y: number; width: number; height: number };
  groupKey?: string;
  optionKey?: string;
  optionLabel?: string;
  groupLabel?: string;
};

export type FillLinkGroupTemplatePayload = {
  templateId: string;
  templateName?: string;
  fields: FillLinkTemplateFieldPayload[];
  checkboxRules?: Array<Record<string, unknown>>;
  textTransformRules?: Array<Record<string, unknown>>;
};

export type PublicFillLinkSubmitResult = {
  success: boolean;
  responseId?: string | null;
  respondentLabel?: string | null;
  link: FillLinkSummary;
  responseDownloadPath?: string | null;
  responseDownloadAvailable?: boolean;
  responseDownloadMode?: 'flat' | 'editable' | string | null;
  signing?: {
    enabled?: boolean;
    available?: boolean;
    requestId?: string | null;
    status?: string | null;
    publicPath?: string | null;
    errorMessage?: string | null;
  } | null;
};

export type PublicFillLinkRetrySigningResult = {
  success: boolean;
  responseId?: string | null;
  link: FillLinkSummary;
  signing?: PublicFillLinkSubmitResult['signing'];
};

// ---------------------------------------------------------------------------
// Normalizers
// ---------------------------------------------------------------------------

export function normalizeFillLinkSummary(link: FillLinkSummary | null | undefined): FillLinkSummary | null {
  if (!link || typeof link !== 'object') {
    return null;
  }
  const respondentPdfDownloadEnabled = typeof link.respondentPdfDownloadEnabled === 'boolean'
    ? link.respondentPdfDownloadEnabled
    : Boolean(link.allowRespondentPdfDownload);
  const respondentPdfEditableEnabled = respondentPdfDownloadEnabled && typeof link.respondentPdfEditableEnabled === 'boolean'
    ? link.respondentPdfEditableEnabled
    : false;
  return {
    ...link,
    allowRespondentPdfDownload: respondentPdfDownloadEnabled,
    respondentPdfDownloadEnabled,
    respondentPdfEditableEnabled,
    postSubmitSigningEnabled:
      typeof link.postSubmitSigningEnabled === 'boolean'
        ? link.postSubmitSigningEnabled
        : Boolean(link.signingConfig?.enabled),
    webFormConfig:
      link.webFormConfig && typeof link.webFormConfig === 'object'
        ? {
          ...link.webFormConfig,
          questions: Array.isArray(link.webFormConfig.questions) ? link.webFormConfig.questions : [],
        }
        : null,
    signingConfig:
      link.signingConfig && typeof link.signingConfig === 'object'
        ? { ...link.signingConfig }
        : null,
  };
}

function normalizePublicFillLinkSubmitResult(payload: any): PublicFillLinkSubmitResult {
  const download = payload?.download && typeof payload.download === 'object'
    ? payload.download as { enabled?: unknown; downloadPath?: unknown; mode?: unknown }
    : null;
  const responseDownloadAvailable = typeof payload?.responseDownloadAvailable === 'boolean'
    ? payload.responseDownloadAvailable
    : Boolean(download?.enabled);
  const responseDownloadPath = typeof payload?.responseDownloadPath === 'string'
    ? payload.responseDownloadPath
    : typeof download?.downloadPath === 'string'
      ? download.downloadPath
      : null;
  const responseDownloadMode = typeof payload?.responseDownloadMode === 'string'
    ? payload.responseDownloadMode
    : typeof download?.mode === 'string'
      ? download.mode
      : null;
  return {
    ...payload,
    link: normalizeFillLinkSummary(payload?.link) || { status: 'closed' },
    responseDownloadAvailable,
    responseDownloadPath,
    responseDownloadMode,
    signing:
      payload?.signing && typeof payload.signing === 'object'
        ? {
          enabled: Boolean(payload.signing.enabled),
          available: Boolean(payload.signing.available),
          requestId: typeof payload.signing.requestId === 'string' ? payload.signing.requestId : null,
          status: typeof payload.signing.status === 'string' ? payload.signing.status : null,
          publicPath: typeof payload.signing.publicPath === 'string' ? payload.signing.publicPath : null,
          errorMessage: typeof payload.signing.errorMessage === 'string' ? payload.signing.errorMessage : null,
        }
        : null,
  };
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

export class FillLinksApiService {
  /**
   * List Fill By Link records for the current owner.
   */
  static async getFillLinks(
    filters?: string | { templateId?: string; groupId?: string; scopeType?: string },
  ): Promise<FillLinkSummary[]> {
    const params = new URLSearchParams();
    if (typeof filters === 'string') {
      params.set('templateId', filters);
    } else if (filters) {
      if (filters.templateId) params.set('templateId', filters.templateId);
      if (filters.groupId) params.set('groupId', filters.groupId);
      if (filters.scopeType) params.set('scopeType', filters.scopeType);
    }
    const query = params.toString();
    const response = await apiFetch('GET', `/api/fill-links${query ? `?${query}` : ''}`);
    const payload = await apiJsonFetch<{ links?: FillLinkSummary[] }>(response);
    return (payload?.links || []).map((link) => normalizeFillLinkSummary(link) || link);
  }

  /**
   * Publish or refresh a Fill By Link from the current template.
   */
  static async createFillLink(payload: {
    scopeType?: 'template' | 'group';
    templateId?: string;
    templateName?: string;
    groupId?: string;
    groupName?: string;
    title?: string;
    requireAllFields?: boolean;
    allowRespondentPdfDownload?: boolean;
    allowRespondentEditablePdfDownload?: boolean;
    webFormConfig?: FillLinkWebFormConfig;
    signingConfig?: FillLinkSigningConfig;
    fields: FillLinkTemplateFieldPayload[];
    checkboxRules?: Array<Record<string, unknown>>;
    textTransformRules?: TextTransformRule[];
    groupTemplates?: FillLinkGroupTemplatePayload[];
  }): Promise<FillLinkSummary> {
    const { allowRespondentPdfDownload, allowRespondentEditablePdfDownload, ...rest } = payload;
    const response = await apiFetch('POST', '/api/fill-links', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...rest,
        ...(typeof allowRespondentPdfDownload === 'boolean'
          ? { respondentPdfDownloadEnabled: allowRespondentPdfDownload }
          : {}),
        ...(typeof allowRespondentEditablePdfDownload === 'boolean'
          ? { respondentPdfEditableEnabled: allowRespondentEditablePdfDownload }
          : {}),
      }),
    });
    const data = await apiJsonFetch<{ link: FillLinkSummary }>(response);
    return normalizeFillLinkSummary(data.link) || data.link;
  }

  /**
   * Update or reopen an existing Fill By Link.
   */
  static async updateFillLink(
    linkId: string,
    payload: {
      title?: string;
      groupName?: string;
      requireAllFields?: boolean;
      allowRespondentPdfDownload?: boolean;
      allowRespondentEditablePdfDownload?: boolean;
      webFormConfig?: FillLinkWebFormConfig;
      signingConfig?: FillLinkSigningConfig;
      status?: 'active' | 'closed';
      fields?: FillLinkTemplateFieldPayload[];
      checkboxRules?: Array<Record<string, unknown>>;
      textTransformRules?: TextTransformRule[];
      groupTemplates?: FillLinkGroupTemplatePayload[];
    },
  ): Promise<FillLinkSummary> {
    const { allowRespondentPdfDownload, allowRespondentEditablePdfDownload, ...rest } = payload;
    const response = await apiFetch('PATCH', `/api/fill-links/${encodeURIComponent(linkId)}`, {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...rest,
        ...(typeof allowRespondentPdfDownload === 'boolean'
          ? { respondentPdfDownloadEnabled: allowRespondentPdfDownload }
          : {}),
        ...(typeof allowRespondentEditablePdfDownload === 'boolean'
          ? { respondentPdfEditableEnabled: allowRespondentEditablePdfDownload }
          : {}),
      }),
    });
    const data = await apiJsonFetch<{ link: FillLinkSummary }>(response);
    return normalizeFillLinkSummary(data.link) || data.link;
  }

  /**
   * Close an active Fill By Link.
   */
  static async closeFillLink(linkId: string): Promise<FillLinkSummary> {
    const response = await apiFetch('POST', `/api/fill-links/${encodeURIComponent(linkId)}/close`);
    const data = await apiJsonFetch<{ link: FillLinkSummary }>(response);
    return normalizeFillLinkSummary(data.link) || data.link;
  }

  /**
   * List responses for a Fill By Link.
   */
  static async getFillLinkResponses(
    linkId: string,
    payload?: { search?: string; limit?: number },
  ): Promise<{ link: FillLinkSummary; responses: FillLinkResponse[] }> {
    const params = new URLSearchParams();
    if (payload?.search) params.set('search', payload.search);
    if (typeof payload?.limit === 'number') params.set('limit', String(payload.limit));
    const query = params.toString();
    const response = await apiFetch(
      'GET',
      `/api/fill-links/${encodeURIComponent(linkId)}/responses${query ? `?${query}` : ''}`,
    );
    const data = await apiJsonFetch<{ link: FillLinkSummary; responses: FillLinkResponse[] }>(response);
    return {
      ...data,
      link: normalizeFillLinkSummary(data.link) || data.link,
    };
  }

  /**
   * Fetch a single stored respondent response.
   */
  static async getFillLinkResponse(linkId: string, responseId: string): Promise<FillLinkResponse> {
    const response = await apiFetch(
      'GET',
      `/api/fill-links/${encodeURIComponent(linkId)}/responses/${encodeURIComponent(responseId)}`,
    );
    const payload = await apiJsonFetch<{ response: FillLinkResponse }>(response);
    return payload.response;
  }

  /**
   * Load a public Fill By Link definition for anonymous respondents.
   */
  static async getPublicFillLink(token: string): Promise<FillLinkSummary> {
    const response = await apiFetch('GET', `/api/fill-links/public/${encodeURIComponent(token)}`, {
      authMode: 'anonymous',
    });
    const payload = await apiJsonFetch<{ link: FillLinkSummary }>(response);
    return normalizeFillLinkSummary(payload.link) || payload.link;
  }

  /**
   * Submit anonymous respondent answers for a Fill By Link.
   */
  static async submitPublicFillLink(
    token: string,
    payload: {
      answers: Record<string, unknown>;
      recaptchaToken?: string;
      recaptchaAction?: string;
      attemptId?: string;
    },
  ): Promise<PublicFillLinkSubmitResult> {
    const response = await apiFetch('POST', `/api/fill-links/public/${encodeURIComponent(token)}/submit`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...payload,
        attemptId: typeof payload.attemptId === 'string' && payload.attemptId.trim()
          ? payload.attemptId
          : buildFillLinkSubmitAttemptId(),
      }),
    });
    const result = await apiJsonFetch<any>(response);
    return normalizePublicFillLinkSubmitResult(result);
  }

  /**
   * Retry a post-submit signing handoff for an already stored public response.
   */
  static async retryPublicFillLinkSigning(
    token: string,
    payload: { responseId: string },
  ): Promise<PublicFillLinkRetrySigningResult> {
    const response = await apiFetch('POST', `/api/fill-links/public/${encodeURIComponent(token)}/retry-signing`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const result = await apiJsonFetch<any>(response);
    return {
      success: Boolean(result?.success),
      responseId: typeof result?.responseId === 'string' ? result.responseId : null,
      link: normalizeFillLinkSummary(result?.link) || { status: 'closed' },
      signing:
        result?.signing && typeof result.signing === 'object'
          ? {
            enabled: Boolean(result.signing.enabled),
            available: Boolean(result.signing.available),
            requestId: typeof result.signing.requestId === 'string' ? result.signing.requestId : null,
            status: typeof result.signing.status === 'string' ? result.signing.status : null,
            publicPath: typeof result.signing.publicPath === 'string' ? result.signing.publicPath : null,
            errorMessage: typeof result.signing.errorMessage === 'string' ? result.signing.errorMessage : null,
          }
          : null,
    };
  }

  /**
   * Download a respondent PDF copy from a public Fill By Link response.
   */
  static async downloadPublicFillLinkResponsePdf(
    token: string,
    responseId: string,
    options?: {
      downloadPath?: string | null;
    } & AbortableRequestOptions,
  ): Promise<{ blob: Blob; filename: string | null }> {
    const rawPath = options?.downloadPath?.trim();
    const requestPath = rawPath || `/api/fill-links/public/${encodeURIComponent(token)}/responses/${encodeURIComponent(responseId)}/download`;
    const response = await apiFetch('GET', requestPath, {
      authMode: 'anonymous',
      ...buildAbortOptions(options?.signal),
    });
    if (!response.ok) {
      throw new Error(`Failed to download submitted PDF: ${response.statusText}`);
    }
    return {
      blob: await response.blob(),
      filename: parseDownloadFilename(response.headers.get('content-disposition')),
    };
  }
}
