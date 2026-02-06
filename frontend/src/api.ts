/**
 * API wrapper for backend endpoints used by the UI.
 */
import type { PdfField } from './types';
import { apiFetch, apiJsonFetch, buildApiUrl } from './services/apiConfig';

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

export type UserProfile = {
  email?: string | null;
  displayName?: string | null;
  role?: string | null;
  creditsRemaining?: number | null;
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

    return apiJsonFetch(response);
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

    return apiJsonFetch(response);
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
    checkboxRules?: Array<Record<string, any>>;
    checkboxHints?: Array<Record<string, any>>;
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
