import { describe, expect, it, vi } from 'vitest';

const apiConfigMocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiJsonFetch: vi.fn(),
  buildApiUrl: vi.fn((...segments: string[]) => `https://api.local/${segments.filter(Boolean).join('/')}`),
}));

vi.mock('../../../src/services/apiConfig', () => ({
  apiFetch: apiConfigMocks.apiFetch,
  apiJsonFetch: apiConfigMocks.apiJsonFetch,
  buildApiUrl: apiConfigMocks.buildApiUrl,
}));

import { ApiService } from '../../../src/services/api';

describe('ApiService', () => {
  it('wires profile and public JSON endpoints with expected methods and payloads', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ status: 401 })
      .mockResolvedValueOnce({ id: 'contact-response' })
      .mockResolvedValueOnce({ id: 'recaptcha-response' })
      .mockResolvedValueOnce({ id: 'schema-response' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ schemaId: 'schema-1', fieldCount: 1, fields: [{ name: 'first_name', type: 'text' }] });

    const profile = await ApiService.getProfile();
    const contact = await ApiService.submitContact({ issueType: 'bug', summary: 'S', message: 'M' });
    const recaptcha = await ApiService.verifyRecaptcha({ token: 'token-1', action: 'signup' });
    const schema = await ApiService.createSchema({ fields: [{ name: 'first_name' }], sampleCount: 2 });

    expect(profile).toBeNull();
    expect(contact).toEqual({ success: true });
    expect(recaptcha).toEqual({ success: true });
    expect(schema.schemaId).toBe('schema-1');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/profile', {
      allowStatuses: [401, 403],
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', '/api/contact', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ issueType: 'bug', summary: 'S', message: 'M' }),
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(3, 'POST', '/api/recaptcha/assess', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: 'token-1', action: 'signup' }),
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(4, 'POST', '/api/schemas', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fields: [{ name: 'first_name' }], sampleCount: 2 }),
    });
  });

  it('wires rename/map endpoints and payload shape through buildApiUrl', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'rename-response' })
      .mockResolvedValueOnce({ id: 'map-response' });
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ renamed: true })
      .mockResolvedValueOnce({ mapped: true });

    await ApiService.renameFields({
      sessionId: 'sess-1',
      schemaId: 'schema-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    });

    await ApiService.mapSchema(
      'schema-1',
      [{ name: 'First Name', type: 'text' }],
      'template-1',
      'sess-1',
    );

    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'renames', 'ai');
    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'schema-mappings', 'ai');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      1,
      'POST',
      'https://api.local/api/renames/ai',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: 'sess-1',
          schemaId: 'schema-1',
          templateFields: [{ name: 'First Name', type: 'text' }],
        }),
      },
    );

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      'POST',
      'https://api.local/api/schema-mappings/ai',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schemaId: 'schema-1',
          templateId: 'template-1',
          templateFields: [{ name: 'First Name', type: 'text' }],
          sessionId: 'sess-1',
        }),
      },
    );
  });

  it('handles saved-form list/load/download/delete/session/touch operations', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ status: 200, id: 'saved-forms' })
      .mockResolvedValueOnce({ status: 200, id: 'load-saved' })
      .mockResolvedValueOnce({ ok: true, blob: vi.fn().mockResolvedValue(new Blob(['pdf'])) })
      .mockResolvedValueOnce({ status: 200, id: 'create-saved-session' })
      .mockResolvedValueOnce({ status: 200, id: 'touch-session' })
      .mockResolvedValueOnce({ status: 200, id: 'delete-saved' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ forms: [{ id: 'f-1', name: 'A', createdAt: '2026-01-01' }] })
      .mockResolvedValueOnce({ id: 'f-1', name: 'A', url: 'https://file.local/a.pdf' })
      .mockResolvedValueOnce({ success: true, sessionId: 'sess-1', fieldCount: 1 })
      .mockResolvedValueOnce({ success: true, sessionId: 'sess-1' })
      .mockResolvedValueOnce({ success: true });

    const savedForms = await ApiService.getSavedForms({ suppressErrors: false, timeoutMs: 3210 });
    const loaded = await ApiService.loadSavedForm('form id/with spaces');
    const blob = await ApiService.downloadSavedForm('form id/with spaces');
    const session = await ApiService.createSavedFormSession('form id/with spaces', {
      fields: [{ name: 'first_name' }],
      pageCount: 2,
    });
    const touched = await ApiService.touchSession('session / id');
    const deleted = await ApiService.deleteSavedForm('form id/with spaces');

    expect(savedForms).toHaveLength(1);
    expect(loaded.id).toBe('f-1');
    expect(blob).toBeInstanceOf(Blob);
    expect(session.sessionId).toBe('sess-1');
    expect(touched.success).toBe(true);
    expect(deleted.success).toBe(true);

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/saved-forms', {
      allowStatuses: [401],
      timeoutMs: 3210,
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      'GET',
      '/api/saved-forms/form%20id%2Fwith%20spaces',
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      'GET',
      'https://api.local/api/saved-forms/form id/with spaces/download',
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      4,
      'POST',
      '/api/saved-forms/form%20id%2Fwith%20spaces/session',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields: [{ name: 'first_name' }], pageCount: 2 }),
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      5,
      'POST',
      '/api/sessions/session%20%2F%20id/touch',
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      6,
      'DELETE',
      '/api/saved-forms/form%20id%2Fwith%20spaces',
    );
  });

  it('builds FormData payloads for template sessions and save/materialize flows', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'template-session' })
      .mockResolvedValueOnce({ id: 'save-form' })
      .mockResolvedValueOnce({ ok: true, blob: vi.fn().mockResolvedValue(new Blob(['fillable'])) });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ success: true, sessionId: 'tmpl-1', fieldCount: 2 })
      .mockResolvedValueOnce({ success: true, id: 'saved-1', name: 'My Saved Form' });

    const templateFile = new File(['pdf'], 'template.pdf', { type: 'application/pdf' });
    const sourceBlob = new Blob(['pdf'], { type: 'application/pdf' });

    const templateSession = await ApiService.createTemplateSession(templateFile, {
      fields: [{ name: 'first_name' }, { name: 'last_name' }],
      pageCount: 3,
    });

    const saved = await ApiService.saveFormToProfile(
      sourceBlob,
      'Patient Intake',
      'sess-99',
      'overwrite-1',
      [{ fieldName: 'insurance_opt_in' }],
      [{ groupKey: 'insurance' }],
    );

    const materialized = await ApiService.materializeFormPdf(sourceBlob, [
      {
        id: 'f-1',
        name: 'First Name',
        type: 'text',
        page: 1,
        rect: { x: 0, y: 0, width: 10, height: 10 },
        value: 'Alex',
      },
    ] as any);

    expect(templateSession.success).toBe(true);
    expect(saved.id).toBe('saved-1');
    expect(materialized).toBeInstanceOf(Blob);

    const templateBody = apiConfigMocks.apiFetch.mock.calls[0][2].body as FormData;
    expect(templateBody).toBeInstanceOf(FormData);
    expect((templateBody.get('pdf') as File).name).toBe('template.pdf');
    expect(templateBody.get('fields')).toBe(
      JSON.stringify({ fields: [{ name: 'first_name' }, { name: 'last_name' }] }),
    );
    expect(templateBody.get('pageCount')).toBe('3');

    const saveBody = apiConfigMocks.apiFetch.mock.calls[1][2].body as FormData;
    expect((saveBody.get('pdf') as File).name).toBe('Patient Intake.pdf');
    expect(saveBody.get('name')).toBe('Patient Intake');
    expect(saveBody.get('sessionId')).toBe('sess-99');
    expect(saveBody.get('overwriteFormId')).toBe('overwrite-1');
    expect(saveBody.get('checkboxRules')).toBe(JSON.stringify([{ fieldName: 'insurance_opt_in' }]));
    expect(saveBody.get('checkboxHints')).toBe(JSON.stringify([{ groupKey: 'insurance' }]));

    const materializeBody = apiConfigMocks.apiFetch.mock.calls[2][2].body as FormData;
    expect((materializeBody.get('pdf') as File).name).toBe('form.pdf');
    expect(materializeBody.get('fields')).toBe(
      JSON.stringify({
        fields: [
          {
            id: 'f-1',
            name: 'First Name',
            type: 'text',
            page: 1,
            rect: { x: 0, y: 0, width: 10, height: 10 },
            value: 'Alex',
          },
        ],
      }),
    );
  });

  it('throws clear errors for non-ok blob endpoints', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ ok: false, statusText: 'Forbidden' })
      .mockResolvedValueOnce({ ok: false, statusText: 'Unprocessable Entity' });

    await expect(ApiService.downloadSavedForm('x')).rejects.toThrow(
      'Failed to download saved form: Forbidden',
    );

    await expect(
      ApiService.materializeFormPdf(new Blob(['pdf']), [
        {
          id: 'f-1',
          name: 'x',
          type: 'text',
          page: 1,
          rect: { x: 0, y: 0, width: 1, height: 1 },
        },
      ] as any),
    ).rejects.toThrow('Failed to generate fillable PDF: Unprocessable Entity');
  });
});
