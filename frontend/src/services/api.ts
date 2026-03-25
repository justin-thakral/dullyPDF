/**
 * API wrapper for backend endpoints used by the UI.
 */
import type {
  PdfField,
  SavedFormEditorSnapshot,
} from '../types';
import {
  ApiError,
  apiFetch,
  apiJsonFetch,
  buildApiUrl,
  ensureBackendReady as ensureBackendConnectionReady,
} from './apiConfig';
import { FillLinksApiService } from './fillLinksApi';

// Re-export all fill-link types so existing callers that import from
// './services/api' continue to work without changes.
export type {
  FillLinkGroupTemplatePayload,
  FillLinkQuestion,
  FillLinkQuestionOption,
  FillLinkResponse,
  FillLinkSigningConfig,
  FillLinkSummary,
  FillLinkTemplateFieldPayload,
  FillLinkWebFormConfig,
  PublicFillLinkSubmitResult,
} from './fillLinksApi';
export { FillLinksApiService } from './fillLinksApi';

const OPENAI_JOB_POLL_INTERVAL_MS = 1500;
const OPENAI_JOB_POLL_TIMEOUT_MS = 600000;
const OPENAI_REQUEST_ID_CACHE = new Map<string, string>();

type AbortableRequestOptions = {
  signal?: AbortSignal;
  healthUrl?: string;
};

export type MaterializePdfExportMode = 'editable' | 'flat';

class OpenAiJobTerminalError extends Error {}

function buildBillingCheckoutAttemptId(): string {
  const cryptoApi =
    typeof globalThis !== 'undefined' && typeof globalThis.crypto !== 'undefined'
      ? globalThis.crypto
      : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  const randomSuffix = Math.random().toString(36).slice(2, 12);
  return `attempt_${Date.now()}_${randomSuffix}`;
}

function buildOpenAiRequestId(): string {
  const cryptoApi =
    typeof globalThis !== 'undefined' && typeof globalThis.crypto !== 'undefined'
      ? globalThis.crypto
      : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  const randomSuffix = Math.random().toString(36).slice(2, 12);
  return `openai_${Date.now()}_${randomSuffix}`;
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((entry) => stableStringify(entry)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entryValue]) => `${JSON.stringify(key)}:${stableStringify(entryValue)}`);
    return `{${entries.join(',')}}`;
  }
  const serialized = JSON.stringify(value);
  return serialized === undefined ? 'null' : serialized;
}

function getOrCreateOpenAiRequestId(cacheKey: string): string {
  const existing = OPENAI_REQUEST_ID_CACHE.get(cacheKey);
  if (existing) {
    return existing;
  }
  const requestId = buildOpenAiRequestId();
  OPENAI_REQUEST_ID_CACHE.set(cacheKey, requestId);
  return requestId;
}

function clearOpenAiRequestId(cacheKey: string): void {
  OPENAI_REQUEST_ID_CACHE.delete(cacheKey);
}

function isAbortLikeError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  return error instanceof Error && error.name === 'AbortError';
}

function isTimeoutLikeError(error: unknown): boolean {
  return error instanceof TypeError && /timed out/i.test(error.message);
}

function shouldClearOpenAiRequestId(error: unknown): boolean {
  return (
    error instanceof ApiError
    || error instanceof OpenAiJobTerminalError
    || isAbortLikeError(error)
    || isTimeoutLikeError(error)
  );
}

function buildAbortOptions(signal?: AbortSignal): AbortableRequestOptions {
  return signal ? { signal } : {};
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

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function sleepWithSignal(durationMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(() => {
      cleanup();
      resolve();
    }, durationMs);
    const cleanup = () => {
      globalThis.clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(new DOMException('Request aborted.', 'AbortError'));
    };
    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export type SavedFormSummary = {
  id: string;
  name: string;
  createdAt: string;
};

export type TemplateApiEndpointSummary = {
  id: string;
  templateId: string;
  templateName: string | null;
  status: 'active' | 'revoked' | string;
  snapshotVersion: number;
  keyPrefix: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  publishedAt: string | null;
  lastUsedAt: string | null;
  usageCount: number;
  currentUsageMonth?: string | null;
  currentMonthUsageCount?: number;
  authFailureCount?: number;
  validationFailureCount?: number;
  suspiciousFailureCount?: number;
  lastFailureAt?: string | null;
  lastFailureReason?: string | null;
  auditEventCount?: number;
  fillPath: string;
  schemaPath: string;
};

export type TemplateApiOwnerLimitSummary = {
  activeEndpointsMax: number;
  activeEndpointsUsed: number;
  requestsPerMonthMax: number;
  requestsThisMonth: number;
  requestUsageMonth?: string | null;
  maxPagesPerRequest: number;
  templatePageCount: number;
};

export type TemplateApiAuditEvent = {
  id: string;
  eventType: string;
  outcome: string;
  createdAt: string | null;
  snapshotVersion?: number | null;
  summary: string;
  metadata?: Record<string, unknown>;
};

export type TemplateApiFieldSchema = {
  key: string;
  fieldName: string;
  type: string;
  page?: number | null;
};

export type TemplateApiOptionSchema = {
  optionKey: string;
  optionLabel?: string | null;
  fieldName?: string | null;
};

export type TemplateApiCheckboxGroupSchema = {
  key: string;
  groupKey: string;
  type: 'checkbox_rule' | string;
  operation: 'yes_no' | 'enum' | 'list' | 'presence' | string;
  options: TemplateApiOptionSchema[];
  trueOption?: string | null;
  falseOption?: string | null;
  valueMap?: Record<string, string> | null;
};

export type TemplateApiRadioGroupSchema = {
  groupKey: string;
  type: 'radio' | string;
  options: TemplateApiOptionSchema[];
};

export type TemplateApiSchema = {
  snapshotVersion: number;
  defaultExportMode: MaterializePdfExportMode;
  fields: TemplateApiFieldSchema[];
  checkboxFields: TemplateApiFieldSchema[];
  checkboxGroups: TemplateApiCheckboxGroupSchema[];
  radioGroups: TemplateApiRadioGroupSchema[];
  exampleData: Record<string, unknown>;
};

export type TemplateApiPublishResult = {
  created: boolean;
  secret: string | null;
  endpoint: TemplateApiEndpointSummary;
  schema: TemplateApiSchema;
  limits: TemplateApiOwnerLimitSummary;
  recentEvents: TemplateApiAuditEvent[];
};

export type TemplateGroupSummary = {
  id: string;
  name: string;
  templateIds: string[];
  templateCount: number;
  templates: SavedFormSummary[];
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type ProfileLimits = {
  detectMaxPages: number;
  fillableMaxPages: number;
  savedFormsMax: number;
  fillLinksActiveMax: number;
  fillLinkResponsesMax: number;
  templateApiActiveMax?: number;
  templateApiRequestsMonthlyMax?: number;
  templateApiMaxPages?: number;
};

export type BillingCheckoutKind = 'pro_monthly' | 'pro_yearly' | 'refill_500';

export type CreditPricingConfig = {
  pageBucketSize: number;
  renameBaseCost: number;
  remapBaseCost: number;
  renameRemapBaseCost: number;
};

export type BillingPlanCatalogItem = {
  kind: BillingCheckoutKind;
  mode: 'subscription' | 'payment' | string;
  priceId: string;
  label: string;
  currency?: string | null;
  unitAmount?: number | null;
  interval?: string | null;
  refillCredits?: number | null;
};

export type BillingProfileConfig = {
  enabled: boolean;
  plans: Partial<Record<BillingCheckoutKind, BillingPlanCatalogItem>>;
  hasSubscription?: boolean;
  subscriptionStatus?: string | null;
  cancelAtPeriodEnd?: boolean | null;
  cancelAt?: number | null;
  currentPeriodEnd?: number | null;
};

export type DowngradeRetentionTemplateSummary = {
  id: string;
  name: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  status: 'kept' | 'pending_delete' | string;
};

export type DowngradeRetentionGroupSummary = {
  id: string;
  name: string;
  templateCount: number;
  pendingTemplateCount: number;
  willDelete: boolean;
};

export type DowngradeRetentionLinkSummary = {
  id: string;
  title: string;
  scopeType?: 'template' | 'group' | string;
  status?: 'active' | 'closed' | string;
  templateId?: string | null;
  templateName?: string | null;
  groupId?: string | null;
  groupName?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  pendingDeleteReason?: string | null;
};

export type DowngradeRetentionSummary = {
  status: string;
  policyVersion: number;
  downgradedAt?: string | null;
  graceEndsAt?: string | null;
  daysRemaining: number;
  savedFormsLimit: number;
  fillLinksActiveLimit: number;
  keptTemplateIds: string[];
  pendingDeleteTemplateIds: string[];
  pendingDeleteLinkIds: string[];
  counts: {
    keptTemplates: number;
    pendingTemplates: number;
    affectedGroups: number;
    pendingLinks: number;
    closedLinks?: number;
  };
  templates: DowngradeRetentionTemplateSummary[];
  groups: DowngradeRetentionGroupSummary[];
  links: DowngradeRetentionLinkSummary[];
};

export type UserProfile = {
  email?: string | null;
  displayName?: string | null;
  role?: string | null;
  creditsRemaining?: number | null;
  monthlyCreditsRemaining?: number | null;
  refillCreditsRemaining?: number | null;
  availableCredits?: number | null;
  refillCreditsLocked?: boolean;
  creditPricing?: CreditPricingConfig;
  billing?: BillingProfileConfig;
  retention?: DowngradeRetentionSummary | null;
  limits: ProfileLimits;
};

export type SigningRequestMode = 'sign' | 'fill_and_sign';
export type SigningRequestSignatureMode = 'business' | 'consumer';
export type SigningRequestSourceType = 'workspace' | 'fill_link_response' | 'uploaded_pdf';

export type SigningAnchorPayload = {
  kind: 'signature' | 'signed_date' | 'initials';
  page: number;
  rect: { x: number; y: number; width: number; height: number };
  fieldId?: string;
  fieldName?: string;
};

export type SigningCategoryOption = {
  key: string;
  label: string;
  blocked: boolean;
  reason?: string | null;
};

export type SigningOptions = {
  modes: Array<{ key: SigningRequestMode; label: string }>;
  signatureModes: Array<{ key: SigningRequestSignatureMode; label: string }>;
  categories: SigningCategoryOption[];
};

export type SigningArtifactDescriptor = {
  available: boolean;
  sha256?: string | null;
  bucketPath?: string | null;
  downloadPath?: string | null;
  generatedAt?: string | null;
  retentionUntil?: string | null;
  signatureMethod?: string | null;
  signatureAlgorithm?: string | null;
  kmsKeyResourceName?: string | null;
  kmsKeyVersionName?: string | null;
};

export type SigningArtifactCollection = {
  sourcePdf?: SigningArtifactDescriptor;
  signedPdf: SigningArtifactDescriptor;
  auditManifest?: SigningArtifactDescriptor;
  auditReceipt: SigningArtifactDescriptor;
};

export type SigningRequestSummary = {
  id: string;
  title?: string | null;
  mode: SigningRequestMode;
  signatureMode: SigningRequestSignatureMode;
  sourceType: SigningRequestSourceType;
  sourceId?: string | null;
  sourceLinkId?: string | null;
  sourceRecordLabel?: string | null;
  sourceDocumentName: string;
  sourceTemplateId?: string | null;
  sourceTemplateName?: string | null;
  sourcePdfSha256?: string | null;
  sourcePdfPath?: string | null;
  sourceVersion?: string | null;
  documentCategory: string;
  documentCategoryLabel: string;
  manualFallbackEnabled: boolean;
  signerName: string;
  signerEmail: string;
  inviteDeliveryStatus?: string | null;
  inviteLastAttemptAt?: string | null;
  inviteSentAt?: string | null;
  inviteDeliveryError?: string | null;
  status: string;
  anchors: SigningAnchorPayload[];
  disclosureVersion: string;
  publicToken?: string | null;
  publicPath?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  ownerReviewConfirmedAt?: string | null;
  sentAt?: string | null;
  completedAt?: string | null;
  retentionUntil?: string | null;
  openedAt?: string | null;
  reviewedAt?: string | null;
  consentedAt?: string | null;
  signatureAdoptedAt?: string | null;
  signatureAdoptedName?: string | null;
  manualFallbackRequestedAt?: string | null;
  invalidatedAt?: string | null;
  invalidationReason?: string | null;
  artifacts: SigningArtifactCollection;
};

export type PublicSigningRequest = {
  id: string;
  title?: string | null;
  mode: SigningRequestMode;
  signatureMode: SigningRequestSignatureMode;
  status: string;
  statusMessage: string;
  sourceDocumentName: string;
  sourcePdfSha256?: string | null;
  sourceVersion?: string | null;
  documentCategory: string;
  documentCategoryLabel: string;
  manualFallbackEnabled: boolean;
  signerName: string;
  anchors: SigningAnchorPayload[];
  disclosureVersion: string;
  documentPath: string;
  artifacts: Pick<SigningArtifactCollection, 'signedPdf' | 'auditReceipt'>;
  createdAt?: string | null;
  sentAt?: string | null;
  completedAt?: string | null;
  openedAt?: string | null;
  reviewedAt?: string | null;
  consentedAt?: string | null;
  signatureAdoptedAt?: string | null;
  signatureAdoptedName?: string | null;
  manualFallbackRequestedAt?: string | null;
  invalidatedAt?: string | null;
  invalidationReason?: string | null;
};

export type PublicSigningSession = {
  id: string;
  token: string;
  expiresAt?: string | null;
};

export type PublicSigningBootstrap = {
  request: PublicSigningRequest;
  session?: PublicSigningSession | null;
};

export type SigningRequestArtifactsResponse = {
  requestId: string;
  retentionUntil?: string | null;
  artifacts: SigningArtifactCollection;
};

export type CreateSigningRequestPayload = {
  title?: string;
  mode: SigningRequestMode;
  signatureMode: SigningRequestSignatureMode;
  sourceType: SigningRequestSourceType;
  sourceId?: string;
  sourceLinkId?: string;
  sourceRecordLabel?: string;
  sourceDocumentName: string;
  sourceTemplateId?: string;
  sourceTemplateName?: string;
  sourcePdfSha256?: string;
  documentCategory: string;
  manualFallbackEnabled: boolean;
  signerName: string;
  signerEmail: string;
  anchors: SigningAnchorPayload[];
};

export type SendSigningRequestPayload = {
  pdf: Blob;
  filename?: string;
  sourcePdfSha256?: string;
  ownerReviewConfirmed?: boolean;
};

export type ContactPayload = {
  issueType: string;
  summary: string;
  message: string;
  contactName?: string;
  contactCompany?: string;
  contactEmail?: string;
  contactPhone?: string;
  preferredContact?: string;
  includeContactInSubject?: boolean;
  recaptchaToken?: string;
  recaptchaAction?: string;
  pageUrl?: string;
};

export type RecaptchaAssessmentPayload = {
  token: string;
  action?: string;
};

export class ApiService {
  static async ensureBackendReady(options?: AbortableRequestOptions): Promise<void> {
    await ensureBackendConnectionReady({
      signal: options?.signal,
      healthUrl: options?.healthUrl,
    });
  }

  private static async pollOpenAiJob(
    resource: 'renames' | 'schema-mappings',
    jobId: string,
    timeoutMs = OPENAI_JOB_POLL_TIMEOUT_MS,
    options?: AbortableRequestOptions,
  ): Promise<any> {
    const deadline = Date.now() + timeoutMs;
    let attempt = 0;
    while (Date.now() < deadline) {
      const response = await apiFetch('GET', buildApiUrl('api', resource, 'ai', jobId), buildAbortOptions(options?.signal));
      const payload = await apiJsonFetch<any>(response);
      const status = String(payload?.status || '').toLowerCase();
      if (status === 'complete') {
        return payload?.result && typeof payload.result === 'object' ? payload.result : payload;
      }
      if (status === 'failed') {
        throw new OpenAiJobTerminalError(String(payload?.error || 'OpenAI worker request failed.'));
      }
      attempt += 1;
      await sleepWithSignal(Math.min(OPENAI_JOB_POLL_INTERVAL_MS * attempt, 6000), options?.signal);
    }
    throw new OpenAiJobTerminalError('OpenAI worker request timed out while waiting for completion.');
  }

  /**
   * Fetch profile details and tier limits for the current user.
   */
  static async getProfile(): Promise<UserProfile | null> {
    const response = await apiFetch('GET', '/api/profile', {
      allowStatuses: [401, 403],
    });
    if (response.status === 401 || response.status === 403) {
      return null;
    }
    return apiJsonFetch(response);
  }

  /**
   * Update which saved forms remain outside the downgrade delete queue.
   */
  static async updateDowngradeRetention(
    keptTemplateIds: string[],
  ): Promise<DowngradeRetentionSummary | null> {
    const response = await apiFetch('PATCH', '/api/profile/downgrade-retention', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ keptTemplateIds }),
    });
    const payload = await apiJsonFetch<{ retention?: DowngradeRetentionSummary | null }>(response);
    return payload?.retention ?? null;
  }

  /**
   * Delete all saved forms and dependent links currently queued by downgrade retention.
   */
  static async deleteDowngradeRetentionNow(): Promise<{
    success: boolean;
    deletedTemplateIds: string[];
    deletedLinkIds: string[];
  }> {
    const response = await apiFetch('POST', '/api/profile/downgrade-retention/delete-now');
    return apiJsonFetch(response);
  }

  // -- Fill By Link delegations (canonical implementation in FillLinksApiService) --
  static getFillLinks = FillLinksApiService.getFillLinks;
  static createFillLink = FillLinksApiService.createFillLink;
  static updateFillLink = FillLinksApiService.updateFillLink;
  static closeFillLink = FillLinksApiService.closeFillLink;
  static getFillLinkResponses = FillLinksApiService.getFillLinkResponses;
  static getFillLinkResponse = FillLinksApiService.getFillLinkResponse;
  static getPublicFillLink = FillLinksApiService.getPublicFillLink;
  static submitPublicFillLink = FillLinksApiService.submitPublicFillLink;
  static retryPublicFillLinkSigning = FillLinksApiService.retryPublicFillLinkSigning;
  static downloadPublicFillLinkResponsePdf = FillLinksApiService.downloadPublicFillLinkResponsePdf;

  static async getSigningOptions(): Promise<SigningOptions> {
    const response = await apiFetch('GET', '/api/signing/options');
    return apiJsonFetch(response);
  }

  static async getSigningRequests(): Promise<SigningRequestSummary[]> {
    const response = await apiFetch('GET', '/api/signing/requests');
    const payload = await apiJsonFetch<{ requests?: SigningRequestSummary[] }>(response);
    return Array.isArray(payload?.requests) ? payload.requests : [];
  }

  static async createSigningRequest(payload: CreateSigningRequestPayload): Promise<SigningRequestSummary> {
    const response = await apiFetch('POST', '/api/signing/requests', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: payload.title,
        mode: payload.mode,
        signatureMode: payload.signatureMode,
        sourceType: payload.sourceType,
        sourceId: payload.sourceId,
        sourceLinkId: payload.sourceLinkId,
        sourceRecordLabel: payload.sourceRecordLabel,
        sourceDocumentName: payload.sourceDocumentName,
        sourceTemplateId: payload.sourceTemplateId,
        sourceTemplateName: payload.sourceTemplateName,
        sourcePdfSha256: payload.sourcePdfSha256,
        documentCategory: payload.documentCategory,
        manualFallbackEnabled: payload.manualFallbackEnabled,
        signerName: payload.signerName,
        signerEmail: payload.signerEmail,
        anchors: payload.anchors,
      }),
    });
    const result = await apiJsonFetch<{ request: SigningRequestSummary }>(response);
    return result.request;
  }

  static async getSigningRequest(requestId: string): Promise<SigningRequestSummary> {
    const response = await apiFetch('GET', `/api/signing/requests/${encodeURIComponent(requestId)}`);
    const payload = await apiJsonFetch<{ request: SigningRequestSummary }>(response);
    return payload.request;
  }

  static async getSigningRequestArtifacts(requestId: string): Promise<SigningRequestArtifactsResponse> {
    const response = await apiFetch('GET', `/api/signing/requests/${encodeURIComponent(requestId)}/artifacts`);
    return apiJsonFetch(response);
  }

  static async downloadAuthenticatedFile(
    requestPath: string,
    options?: {
      filename?: string | null;
      signal?: AbortSignal;
      timeoutMs?: number;
    },
  ): Promise<void> {
    const response = await apiFetch('GET', requestPath, {
      signal: options?.signal,
      timeoutMs: options?.timeoutMs,
    });
    if (!response.ok) {
      throw new Error(`Failed to download file: ${response.statusText}`);
    }
    const blob = await response.blob();
    const filename = (
      parseDownloadFilename(response.headers.get('content-disposition'))
      || String(options?.filename || '').trim()
      || 'download.pdf'
    );
    triggerBrowserDownload(blob, filename);
  }

  static async sendSigningRequest(requestId: string, payload: SendSigningRequestPayload): Promise<SigningRequestSummary> {
    const formData = new FormData();
    formData.append('pdf', payload.pdf, payload.filename || 'signing-source.pdf');
    if (payload.sourcePdfSha256) {
      formData.append('sourcePdfSha256', payload.sourcePdfSha256);
    }
    if (typeof payload.ownerReviewConfirmed === 'boolean') {
      formData.append('ownerReviewConfirmed', payload.ownerReviewConfirmed ? 'true' : 'false');
    }
    const response = await apiFetch('POST', `/api/signing/requests/${encodeURIComponent(requestId)}/send`, {
      body: formData,
    });
    const result = await apiJsonFetch<{ request: SigningRequestSummary }>(response);
    return result.request;
  }

  static async getPublicSigningRequest(token: string): Promise<PublicSigningRequest> {
    const response = await apiFetch('GET', `/api/signing/public/${encodeURIComponent(token)}`, {
      authMode: 'anonymous',
    });
    const payload = await apiJsonFetch<{ request: PublicSigningRequest }>(response);
    return payload.request;
  }

  static async startPublicSigningSession(token: string): Promise<PublicSigningBootstrap> {
    const response = await apiFetch('POST', `/api/signing/public/${encodeURIComponent(token)}/bootstrap`, {
      authMode: 'anonymous',
    });
    return apiJsonFetch(response);
  }

  static async reviewPublicSigningRequest(token: string, sessionToken: string): Promise<PublicSigningRequest> {
    const response = await apiFetch('POST', `/api/signing/public/${encodeURIComponent(token)}/review`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': sessionToken,
      },
      body: JSON.stringify({ reviewConfirmed: true }),
    });
    const payload = await apiJsonFetch<{ request: PublicSigningRequest }>(response);
    return payload.request;
  }

  static async consentPublicSigningRequest(token: string, sessionToken: string): Promise<PublicSigningRequest> {
    const response = await apiFetch('POST', `/api/signing/public/${encodeURIComponent(token)}/consent`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': sessionToken,
      },
      body: JSON.stringify({ accepted: true }),
    });
    const payload = await apiJsonFetch<{ request: PublicSigningRequest }>(response);
    return payload.request;
  }

  static async requestPublicSigningManualFallback(
    token: string,
    sessionToken: string,
    note?: string,
  ): Promise<PublicSigningRequest> {
    const response = await apiFetch('POST', `/api/signing/public/${encodeURIComponent(token)}/manual-fallback`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': sessionToken,
      },
      body: JSON.stringify({ note }),
    });
    const payload = await apiJsonFetch<{ request: PublicSigningRequest }>(response);
    return payload.request;
  }

  static async adoptPublicSigningSignature(
    token: string,
    sessionToken: string,
    adoptedName: string,
  ): Promise<PublicSigningRequest> {
    const response = await apiFetch('POST', `/api/signing/public/${encodeURIComponent(token)}/adopt-signature`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': sessionToken,
      },
      body: JSON.stringify({ adoptedName }),
    });
    const payload = await apiJsonFetch<{ request: PublicSigningRequest }>(response);
    return payload.request;
  }

  static async completePublicSigningRequest(token: string, sessionToken: string): Promise<PublicSigningRequest> {
    const response = await apiFetch('POST', `/api/signing/public/${encodeURIComponent(token)}/complete`, {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': sessionToken,
      },
      body: JSON.stringify({ intentConfirmed: true }),
    });
    const payload = await apiJsonFetch<{ request: PublicSigningRequest }>(response);
    return payload.request;
  }

  /**
   * Submit the homepage contact form.
   */
  static async submitContact(payload: ContactPayload): Promise<{ success: boolean }> {
    const response = await apiFetch('POST', '/api/contact', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    return apiJsonFetch(response);
  }

  /**
   * Verify a reCAPTCHA token for public actions (signup).
   */
  static async verifyRecaptcha(payload: RecaptchaAssessmentPayload): Promise<{ success: boolean }> {
    // Prefer same-origin requests so browsers skip the CORS preflight (OPTIONS) that can
    // amplify Cloud Run cold starts for first-time signups. Firebase Hosting rewrites
    // proxy this path to the Cloud Run backend in prod, and Vite proxies it in dev.
    const response = await apiFetch('POST', '/api/recaptcha/assess', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    return apiJsonFetch(response);
  }

  /**
   * Create a Stripe Checkout session for subscription/refill purchases.
   */
  static async createBillingCheckoutSession(
    kind: BillingCheckoutKind,
  ): Promise<{
      success: boolean;
      kind: BillingCheckoutKind;
      sessionId: string;
      checkoutUrl: string;
      attemptId?: string | null;
      checkoutPriceId?: string | null;
    }> {
    const attemptId = buildBillingCheckoutAttemptId();
    const response = await apiFetch('POST', '/api/billing/checkout-session', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ kind, attemptId }),
    });
    const payload = await apiJsonFetch<{
      success: boolean;
      kind: BillingCheckoutKind;
      sessionId: string;
      checkoutUrl: string;
      attemptId?: string | null;
      checkoutPriceId?: string | null;
    }>(response);
    return {
      ...payload,
      attemptId: typeof payload?.attemptId === 'string' ? payload.attemptId : null,
      checkoutPriceId: typeof payload?.checkoutPriceId === 'string' ? payload.checkoutPriceId : null,
    };
  }

  /**
   * Audit and reconcile recent Stripe checkout fulfillment for the current user.
   */
  static async reconcileBillingCheckoutFulfillment(
    payload?: {
      lookbackHours?: number;
      maxEvents?: number;
      dryRun?: boolean;
      sessionId?: string | null;
      attemptId?: string | null;
    },
  ): Promise<{
      success: boolean;
      dryRun: boolean;
      scope: string;
      auditedEventCount: number;
      candidateEventCount: number;
      pendingReconciliationCount: number;
      reconciledCount: number;
      alreadyProcessedCount: number;
      processingCount: number;
      retryableCount: number;
      failedCount: number;
      invalidCount: number;
      skippedForUserCount: number;
      events: Array<{
        eventId: string;
        eventType?: string | null;
        eventUserId?: string | null;
        created?: number | null;
        checkoutSessionId?: string | null;
        checkoutAttemptId?: string | null;
        checkoutKind?: string | null;
        checkoutPriceId?: string | null;
        billingEventStatus?: string | null;
      }>;
    }> {
    const response = await apiFetch('POST', '/api/billing/reconcile', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        lookbackHours: payload?.lookbackHours,
        maxEvents: payload?.maxEvents,
        dryRun: payload?.dryRun,
        sessionId: payload?.sessionId,
        attemptId: payload?.attemptId,
      }),
    });
    return apiJsonFetch(response);
  }

  /**
   * Cancel the active Stripe subscription at period end for the current user.
   */
  static async cancelBillingSubscription(): Promise<{
    success: boolean;
    subscriptionId: string;
    status?: string | null;
    cancelAtPeriodEnd: boolean;
    cancelAt?: number | null;
    currentPeriodEnd?: number | null;
    alreadyCanceled?: boolean;
    stateSyncDeferred?: boolean;
  }> {
    const response = await apiFetch('POST', '/api/billing/subscription/cancel');
    return apiJsonFetch(response);
  }

  /**
   * Store schema metadata (headers/types) for mapping.
   */
  static async createSchema(payload: {
    name?: string;
    fields: Array<{ name: string; type?: string }>;
    source?: string;
    sampleCount?: number;
  }): Promise<{ schemaId: string; fieldCount: number; fields: Array<{ name: string; type: string }> }> {
    const response = await apiFetch('POST', '/api/schemas', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    return apiJsonFetch(response);
  }

  /**
   * Request AI-assisted mapping between schema and PDF template tags.
   */
  static async mapSchema(
    schemaId: string,
    templateFields: Array<{
      name: string;
      type?: string;
      page?: number;
      rect?: { x: number; y: number; width: number; height: number };
      groupKey?: string;
      optionKey?: string;
      optionLabel?: string;
      groupLabel?: string;
    }>,
    templateId?: string,
    sessionId?: string,
    options?: AbortableRequestOptions,
  ): Promise<any> {
    const requestPayload = {
      schemaId,
      templateId,
      templateFields,
      sessionId,
    };
    const requestCacheKey = `schema-mappings:${stableStringify(requestPayload)}`;
    const requestId = getOrCreateOpenAiRequestId(requestCacheKey);
    try {
      const response = await apiFetch('POST', buildApiUrl('api', 'schema-mappings', 'ai'), {
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...requestPayload,
          requestId,
        }),
        ...buildAbortOptions(options?.signal),
      });
      const payload = await apiJsonFetch<any>(response);
      const status = String(payload?.status || '').toLowerCase();
      if ((status === 'queued' || status === 'running') && payload?.jobId) {
        const result = await ApiService.pollOpenAiJob('schema-mappings', String(payload.jobId), OPENAI_JOB_POLL_TIMEOUT_MS, options);
        clearOpenAiRequestId(requestCacheKey);
        return result;
      }
      clearOpenAiRequestId(requestCacheKey);
      return payload;
    } catch (error) {
      if (shouldClearOpenAiRequestId(error)) {
        clearOpenAiRequestId(requestCacheKey);
      }
      throw error;
    }
  }

  /**
   * Request OpenAI rename using a cached PDF session.
   */
  static async renameFields(payload: {
    sessionId: string;
    schemaId?: string;
    templateFields?: Array<{
      name: string;
      type?: string;
      page?: number;
      rect?: { x: number; y: number; width: number; height: number };
      groupKey?: string;
      optionKey?: string;
      optionLabel?: string;
      groupLabel?: string;
    }>;
  }, options?: AbortableRequestOptions): Promise<any> {
    const requestCacheKey = `renames:${stableStringify(payload)}`;
    const requestId = getOrCreateOpenAiRequestId(requestCacheKey);
    try {
      const response = await apiFetch('POST', buildApiUrl('api', 'renames', 'ai'), {
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...payload,
          requestId,
        }),
        ...buildAbortOptions(options?.signal),
      });
      const result = await apiJsonFetch<any>(response);
      const status = String(result?.status || '').toLowerCase();
      if ((status === 'queued' || status === 'running') && result?.jobId) {
        const polled = await ApiService.pollOpenAiJob('renames', String(result.jobId), OPENAI_JOB_POLL_TIMEOUT_MS, options);
        clearOpenAiRequestId(requestCacheKey);
        return polled;
      }
      clearOpenAiRequestId(requestCacheKey);
      return result;
    } catch (error) {
      if (shouldClearOpenAiRequestId(error)) {
        clearOpenAiRequestId(requestCacheKey);
      }
      throw error;
    }
  }

  /**
   * Fetch saved form summaries for the current user.
   */
  static async getSavedForms(options?: { suppressErrors?: boolean; timeoutMs?: number }): Promise<SavedFormSummary[]> {
    const suppressErrors = options?.suppressErrors ?? true;
    try {
      const response = await apiFetch('GET', '/api/saved-forms', {
        allowStatuses: [401],
        timeoutMs: options?.timeoutMs,
      });
      if (response.status === 401) return [];
      const payload = await apiJsonFetch<{ forms?: SavedFormSummary[] }>(response);
      return payload?.forms || [];
    } catch (err) {
      if (suppressErrors) {
        console.warn('Failed to fetch saved forms', err);
        return [];
      }
      throw err;
    }
  }

  /**
   * Fetch named groups for the current user.
   */
  static async getGroups(): Promise<TemplateGroupSummary[]> {
    const response = await apiFetch('GET', '/api/groups', {
      allowStatuses: [401],
    });
    if (response.status === 401) return [];
    const payload = await apiJsonFetch<{ groups?: TemplateGroupSummary[] }>(response);
    return Array.isArray(payload?.groups) ? payload.groups : [];
  }

  /**
   * Create a named group from existing saved forms.
   */
  static async createGroup(
    payload: { name: string; templateIds: string[] },
    options?: AbortableRequestOptions,
  ): Promise<TemplateGroupSummary> {
    const response = await apiFetch('POST', '/api/groups', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      ...buildAbortOptions(options?.signal),
    });
    const result = await apiJsonFetch<{ group: TemplateGroupSummary }>(response);
    return result.group;
  }

  /**
   * Fetch a single named group.
   */
  static async getGroup(groupId: string): Promise<TemplateGroupSummary> {
    const response = await apiFetch('GET', `/api/groups/${encodeURIComponent(groupId)}`);
    const payload = await apiJsonFetch<{ group: TemplateGroupSummary }>(response);
    return payload.group;
  }

  /**
   * Update a named group.
   */
  static async updateGroup(
    groupId: string,
    payload: { name: string; templateIds: string[] },
  ): Promise<TemplateGroupSummary> {
    const response = await apiFetch('PATCH', `/api/groups/${encodeURIComponent(groupId)}`, {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const result = await apiJsonFetch<{ group: TemplateGroupSummary }>(response);
    return result.group;
  }

  /**
   * Delete a named group.
   */
  static async deleteGroup(groupId: string): Promise<{ success: boolean }> {
    const response = await apiFetch('DELETE', `/api/groups/${encodeURIComponent(groupId)}`);
    return apiJsonFetch(response);
  }

  /**
   * Fetch owner-managed API Fill endpoints for the current user.
   */
  static async listTemplateApiEndpoints(templateId?: string | null): Promise<{
    endpoints: TemplateApiEndpointSummary[];
    limits?: TemplateApiOwnerLimitSummary;
  }> {
    const search = templateId ? `?templateId=${encodeURIComponent(templateId)}` : '';
    const response = await apiFetch('GET', `/api/template-api-endpoints${search}`);
    const payload = await apiJsonFetch<{ endpoints?: TemplateApiEndpointSummary[]; limits?: TemplateApiOwnerLimitSummary }>(response);
    return {
      endpoints: Array.isArray(payload?.endpoints) ? payload.endpoints : [],
      limits: payload?.limits,
    };
  }

  /**
   * Publish or republish a saved form as an API Fill endpoint.
   */
  static async publishTemplateApiEndpoint(payload: {
    templateId: string;
    exportMode?: MaterializePdfExportMode;
  }): Promise<TemplateApiPublishResult> {
    const response = await apiFetch('POST', '/api/template-api-endpoints', {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        templateId: payload.templateId,
        exportMode: payload.exportMode || 'flat',
      }),
    });
    return apiJsonFetch(response);
  }

  /**
   * Rotate the scoped secret for an existing API Fill endpoint.
   */
  static async rotateTemplateApiEndpoint(endpointId: string): Promise<{
    secret: string;
    endpoint: TemplateApiEndpointSummary;
    limits: TemplateApiOwnerLimitSummary;
    recentEvents: TemplateApiAuditEvent[];
  }> {
    const response = await apiFetch('POST', `/api/template-api-endpoints/${encodeURIComponent(endpointId)}/rotate`);
    return apiJsonFetch(response);
  }

  /**
   * Revoke a published API Fill endpoint.
   */
  static async revokeTemplateApiEndpoint(endpointId: string): Promise<{
    endpoint: TemplateApiEndpointSummary;
    limits: TemplateApiOwnerLimitSummary;
    recentEvents: TemplateApiAuditEvent[];
  }> {
    const response = await apiFetch('POST', `/api/template-api-endpoints/${encodeURIComponent(endpointId)}/revoke`);
    return apiJsonFetch(response);
  }

  /**
   * Fetch the owner schema for one API Fill endpoint.
   */
  static async getTemplateApiEndpointSchema(endpointId: string): Promise<{
    endpoint: TemplateApiEndpointSummary;
    schema: TemplateApiSchema;
    limits: TemplateApiOwnerLimitSummary;
    recentEvents: TemplateApiAuditEvent[];
  }> {
    const response = await apiFetch('GET', `/api/template-api-endpoints/${encodeURIComponent(endpointId)}/schema`);
    return apiJsonFetch(response);
  }

  /**
   * Validate a PDF and return its page count for preflight UI checks.
   */
  static async getPdfPageCount(
    pdf: File,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ): Promise<{ success: boolean; pageCount: number; detectMaxPages: number; withinDetectLimit: boolean }> {
    const formData = new FormData();
    formData.append('pdf', pdf);
    try {
      const response = await apiFetch('POST', buildApiUrl('api', 'pdf', 'page-count'), {
        body: formData,
        signal: options?.signal,
        timeoutMs: options?.timeoutMs,
      });
      return apiJsonFetch(response);
    } catch (error) {
      if (isTimeoutLikeError(error)) {
        throw new Error('Page counting timed out. Remove this PDF and try again.');
      }
      throw error;
    }
  }

  /**
   * Fetch metadata for a saved form and session reference.
   */
  static async loadSavedForm(
    formId: string,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ): Promise<{
    url: string;
    name: string;
    sessionId?: string;
    fillRules?: {
      version?: number;
      checkboxRules?: Array<Record<string, any>>;
      textTransformRules?: Array<Record<string, any>>;
      templateRules?: Array<Record<string, any>>;
    };
    checkboxRules?: Array<Record<string, any>>;
    textTransformRules?: Array<Record<string, any>>;
    templateRules?: Array<Record<string, any>>;
    editorSnapshot?: SavedFormEditorSnapshot | null;
  }> {
    const response = await apiFetch('GET', `/api/saved-forms/${encodeURIComponent(formId)}`, {
      signal: options?.signal,
      timeoutMs: options?.timeoutMs,
    });
    return apiJsonFetch(response);
  }

  /**
   * Download the saved form PDF.
   */
  static async downloadSavedForm(
    formId: string,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ): Promise<Blob> {
    const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms', formId, 'download'), {
      signal: options?.signal,
      timeoutMs: options?.timeoutMs,
    });
    if (!response.ok) {
      throw new Error(`Failed to download saved form: ${response.statusText}`);
    }
    return response.blob();
  }

  /**
   * Create a backend session for a saved form so OpenAI rename/mapping can run.
   */
  static async createSavedFormSession(
    formId: string,
    payload: { fields: Array<Record<string, any>>; pageCount?: number },
  ): Promise<{ success: boolean; sessionId: string; fieldCount: number }> {
    const encoded = encodeURIComponent(formId);
    const response = await apiFetch('POST', `/api/saved-forms/${encoded}/session`, {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    return apiJsonFetch(response);
  }

  /**
   * Persist a ready-to-hydrate editor snapshot for an existing saved form.
   */
  static async updateSavedFormEditorSnapshot(
    formId: string,
    snapshot: SavedFormEditorSnapshot,
  ): Promise<{ success: boolean }> {
    const response = await apiFetch('PATCH', `/api/saved-forms/${encodeURIComponent(formId)}/editor-snapshot`, {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ snapshot }),
    });
    return apiJsonFetch(response);
  }

  /**
   * Create a backend session for a fillable template upload so OpenAI rename/mapping can run.
   */
  static async createTemplateSession(
    file: File,
    payload: { fields: Array<Record<string, any>>; pageCount?: number },
    options?: AbortableRequestOptions,
  ): Promise<{ success: boolean; sessionId: string; fieldCount: number; pageCount?: number }> {
    const formData = new FormData();
    formData.append('pdf', file, file.name);
    formData.append('fields', JSON.stringify({ fields: payload.fields }));
    if (payload.pageCount) {
      formData.append('pageCount', String(payload.pageCount));
    }
    const response = await apiFetch('POST', buildApiUrl('api', 'templates', 'session'), {
      body: formData,
      ...buildAbortOptions(options?.signal),
    });

    return apiJsonFetch(response);
  }

  /**
   * Refresh the backend session TTL for long-lived editor sessions.
   */
  static async touchSession(sessionId: string): Promise<{ success: boolean; sessionId: string }> {
    const encoded = encodeURIComponent(sessionId);
    const response = await apiFetch('POST', `/api/sessions/${encoded}/touch`);
    return apiJsonFetch(response);
  }

  /**
   * Delete a saved form by id.
   */
  static async deleteSavedForm(formId: string): Promise<{ success: boolean }> {
    const response = await apiFetch('DELETE', `/api/saved-forms/${encodeURIComponent(formId)}`);
    return apiJsonFetch(response);
  }

  /**
   * Save a form PDF to the user's profile.
   */
  static async saveFormToProfile(
    blob: Blob,
    name: string,
    sessionId?: string,
    overwriteFormId?: string,
    checkboxRules?: Array<Record<string, any>>,
    textTransformRules?: Array<Record<string, any>>,
    editorSnapshot?: SavedFormEditorSnapshot,
    options?: AbortableRequestOptions,
  ): Promise<{ success: boolean; id: string; name?: string }> {
    const formData = new FormData();
    formData.append('pdf', blob, `${name}.pdf`);
    formData.append('name', name);
    if (sessionId) {
      formData.append('sessionId', sessionId);
    }
    if (checkboxRules !== undefined) {
      formData.append('checkboxRules', JSON.stringify(checkboxRules));
    }
    if (textTransformRules !== undefined) {
      formData.append('textTransformRules', JSON.stringify(textTransformRules));
    }
    if (editorSnapshot !== undefined) {
      formData.append('editorSnapshot', JSON.stringify(editorSnapshot));
    }
    if (overwriteFormId) {
      formData.append('overwriteFormId', overwriteFormId);
    }

    const response = await apiFetch('POST', buildApiUrl('api', 'saved-forms'), {
      body: formData,
      ...buildAbortOptions(options?.signal),
    });

    return apiJsonFetch(response);
  }

  /**
   * Ask the backend to materialize a fillable PDF with values.
   */
  static async materializeFormPdf(
    blob: Blob,
    fields: PdfField[],
    options?: AbortableRequestOptions & { exportMode?: MaterializePdfExportMode },
  ): Promise<Blob> {
    const formData = new FormData();
    formData.append('pdf', blob, 'form.pdf');
    formData.append('fields', JSON.stringify({ fields }));
    if (options?.exportMode) {
      formData.append('exportMode', options.exportMode);
    }

    const response = await apiFetch('POST', buildApiUrl('api', 'forms', 'materialize'), {
      body: formData,
      ...buildAbortOptions(options?.signal),
    });

    if (!response.ok) {
      throw new Error(`Failed to generate fillable PDF: ${response.statusText}`);
    }

    return response.blob();
  }
}
