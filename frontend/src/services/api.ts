/**
 * API wrapper for backend endpoints used by the UI.
 */
import type { PdfField } from '../types';
import { apiFetch, apiJsonFetch, buildApiUrl } from './apiConfig';

const OPENAI_JOB_POLL_INTERVAL_MS = 1500;
const OPENAI_JOB_POLL_TIMEOUT_MS = 600000;

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

export type SavedFormSummary = {
  id: string;
  name: string;
  createdAt: string;
};

export type ProfileLimits = {
  detectMaxPages: number;
  fillableMaxPages: number;
  savedFormsMax: number;
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
  limits: ProfileLimits;
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
  private static async pollOpenAiJob(
    resource: 'renames' | 'schema-mappings',
    jobId: string,
    timeoutMs = OPENAI_JOB_POLL_TIMEOUT_MS,
  ): Promise<any> {
    const deadline = Date.now() + timeoutMs;
    let attempt = 0;
    while (Date.now() < deadline) {
      const response = await apiFetch('GET', buildApiUrl('api', resource, 'ai', jobId));
      const payload = await apiJsonFetch<any>(response);
      const status = String(payload?.status || '').toLowerCase();
      if (status === 'complete') {
        return payload?.result && typeof payload.result === 'object' ? payload.result : payload;
      }
      if (status === 'failed') {
        throw new Error(String(payload?.error || 'OpenAI worker request failed.'));
      }
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, Math.min(OPENAI_JOB_POLL_INTERVAL_MS * attempt, 6000)));
    }
    throw new Error('OpenAI worker request timed out while waiting for completion.');
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
   * Submit the homepage contact form.
   */
  static async submitContact(payload: ContactPayload): Promise<{ success: boolean }> {
    const response = await apiFetch('POST', '/api/contact', {
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
    payload?: { lookbackHours?: number; maxEvents?: number; dryRun?: boolean },
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
  ): Promise<any> {
    const response = await apiFetch('POST', buildApiUrl('api', 'schema-mappings', 'ai'), {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        schemaId,
        templateId,
        templateFields,
        sessionId,
      }),
    });
    const payload = await apiJsonFetch<any>(response);
    const status = String(payload?.status || '').toLowerCase();
    if ((status === 'queued' || status === 'running') && payload?.jobId) {
      return ApiService.pollOpenAiJob('schema-mappings', String(payload.jobId));
    }
    return payload;
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
  }): Promise<any> {
    const response = await apiFetch('POST', buildApiUrl('api', 'renames', 'ai'), {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const result = await apiJsonFetch<any>(response);
    const status = String(result?.status || '').toLowerCase();
    if ((status === 'queued' || status === 'running') && result?.jobId) {
      return ApiService.pollOpenAiJob('renames', String(result.jobId));
    }
    return result;
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
   * Fetch metadata for a saved form and session reference.
   */
  static async loadSavedForm(formId: string): Promise<{
    url: string;
    name: string;
    sessionId?: string;
    fillRules?: {
      version?: number;
      checkboxRules?: Array<Record<string, any>>;
      checkboxHints?: Array<Record<string, any>>;
      textTransformRules?: Array<Record<string, any>>;
      templateRules?: Array<Record<string, any>>;
    };
    checkboxRules?: Array<Record<string, any>>;
    checkboxHints?: Array<Record<string, any>>;
    textTransformRules?: Array<Record<string, any>>;
    templateRules?: Array<Record<string, any>>;
  }> {
    const response = await apiFetch('GET', `/api/saved-forms/${encodeURIComponent(formId)}`);
    return apiJsonFetch(response);
  }

  /**
   * Download the saved form PDF.
   */
  static async downloadSavedForm(formId: string): Promise<Blob> {
    const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms', formId, 'download'));
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
   * Create a backend session for a fillable template upload so OpenAI rename/mapping can run.
   */
  static async createTemplateSession(
    file: File,
    payload: { fields: Array<Record<string, any>>; pageCount?: number },
  ): Promise<{ success: boolean; sessionId: string; fieldCount: number; pageCount?: number }> {
    const formData = new FormData();
    formData.append('pdf', file, file.name);
    formData.append('fields', JSON.stringify({ fields: payload.fields }));
    if (payload.pageCount) {
      formData.append('pageCount', String(payload.pageCount));
    }
    const response = await apiFetch('POST', buildApiUrl('api', 'templates', 'session'), {
      body: formData,
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
    checkboxHints?: Array<Record<string, any>>,
    textTransformRules?: Array<Record<string, any>>,
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
    if (checkboxHints !== undefined) {
      formData.append('checkboxHints', JSON.stringify(checkboxHints));
    }
    if (textTransformRules !== undefined) {
      formData.append('textTransformRules', JSON.stringify(textTransformRules));
    }
    if (overwriteFormId) {
      formData.append('overwriteFormId', overwriteFormId);
    }

    const response = await apiFetch('POST', buildApiUrl('api', 'saved-forms'), {
      body: formData,
    });

    return apiJsonFetch(response);
  }

  /**
   * Ask the backend to materialize a fillable PDF with values.
   */
  static async materializeFormPdf(blob: Blob, fields: PdfField[]): Promise<Blob> {
    const formData = new FormData();
    formData.append('pdf', blob, 'form.pdf');
    formData.append('fields', JSON.stringify({ fields }));

    const response = await apiFetch('POST', buildApiUrl('api', 'forms', 'materialize'), {
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Failed to generate fillable PDF: ${response.statusText}`);
    }

    return response.blob();
  }
}
