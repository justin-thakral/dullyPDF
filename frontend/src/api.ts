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

export class ApiService {
  /**
   * Store schema metadata (headers/types) for mapping.
   */
  static async createSchema(payload: {
    name?: string;
    fields: Array<{ name: string; type?: string }>;
    source?: string;
    sampleCount?: number;
  }): Promise<{ schemaId: string; fieldCount: number; fields: Array<{ name: string; type: string }> }> {
    const response = await apiFetch('POST', buildApiUrl('api', 'schemas'), {
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
   * Store an approved schema mapping payload.
   */
  static async createSchemaMapping(payload: {
    schemaId: string;
    templateId?: string;
    mappingResults: Record<string, unknown>;
  }): Promise<{ mappingId: string }> {
    const response = await apiFetch('POST', buildApiUrl('api', 'schema-mappings'), {
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
  static async getSavedForms(options?: { suppressErrors?: boolean }): Promise<SavedFormSummary[]> {
    const suppressErrors = options?.suppressErrors ?? true;
    try {
      const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms'), {
        allowStatuses: [401],
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
  static async loadSavedForm(formId: string): Promise<{ url: string; name: string; sessionId?: string }> {
    const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms', formId));
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
   * Delete a saved form by id.
   */
  static async deleteSavedForm(formId: string): Promise<{ success: boolean }> {
    const response = await apiFetch('DELETE', buildApiUrl('api', 'saved-forms', formId));
    return apiJsonFetch(response);
  }

  /**
   * Save a form PDF to the user's profile.
   */
  static async saveFormToProfile(
    blob: Blob,
    name: string,
    sessionId?: string,
  ): Promise<{ success: boolean; id: string }> {
    const formData = new FormData();
    formData.append('pdf', blob, `${name}.pdf`);
    formData.append('name', name);
    if (sessionId) {
      formData.append('sessionId', sessionId);
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
