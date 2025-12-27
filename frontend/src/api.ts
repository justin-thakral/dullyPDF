import type { PdfField } from './types';
import { apiFetch, apiJsonFetch, buildApiUrl } from './services/apiConfig';

export type SavedFormSummary = {
  id: string;
  name: string;
  createdAt: string;
};

export class ApiService {
  static async uploadDatabaseFields(
    file: File,
  ): Promise<{ filename: string; databaseFields: string[]; totalFields: number }> {
    const formData = new FormData();
    formData.append('fields', file);

    const response = await apiFetch('POST', buildApiUrl('api', 'upload-fields'), {
      body: formData,
    });

    return apiJsonFetch(response);
  }

  static async mapFields(
    sessionId: string,
    databaseFields: string[],
    pdfFormFields?: Array<{ name: string; type?: string; context?: string }>,
  ): Promise<any> {
    const response = await apiFetch('POST', buildApiUrl('api', 'map-fields'), {
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        sessionId,
        databaseFields,
        ...(pdfFormFields && pdfFormFields.length ? { pdfFormFields } : {}),
      }),
    });

    return apiJsonFetch(response);
  }

  static async getSavedForms(): Promise<SavedFormSummary[]> {
    try {
      const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms'), {
        allowStatuses: [401],
      });
      if (response.status === 401) return [];
      const payload = await apiJsonFetch<{ forms?: SavedFormSummary[] }>(response);
      return payload?.forms || [];
    } catch (err) {
      console.warn('Failed to fetch saved forms', err);
      return [];
    }
  }

  static async loadSavedForm(formId: string): Promise<{ url: string; name: string; sessionId?: string }> {
    const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms', formId));
    return apiJsonFetch(response);
  }

  static async downloadSavedForm(formId: string): Promise<Blob> {
    const response = await apiFetch('GET', buildApiUrl('api', 'saved-forms', formId, 'download'));
    if (!response.ok) {
      throw new Error(`Failed to download saved form: ${response.statusText}`);
    }
    return response.blob();
  }

  static async deleteSavedForm(formId: string): Promise<{ success: boolean }> {
    const response = await apiFetch('DELETE', buildApiUrl('api', 'saved-forms', formId));
    return apiJsonFetch(response);
  }

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
