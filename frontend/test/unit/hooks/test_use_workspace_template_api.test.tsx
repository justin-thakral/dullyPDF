import { act, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkspaceTemplateApi } from '../../../src/hooks/useWorkspaceTemplateApi';
import { ApiService } from '../../../src/services/api';

function renderHarness(overrides: Record<string, unknown> = {}) {
  const setManagerOpen = vi.fn();
  const setBannerNotice = vi.fn();
  let latestHook: ReturnType<typeof useWorkspaceTemplateApi> | null = null;
  const verifiedUser = overrides.verifiedUser ?? { uid: 'user-1' };
  const activeTemplateId = overrides.activeTemplateId ?? 'tpl-1';
  const activeTemplateName = overrides.activeTemplateName ?? 'Patient Intake';
  const activeGroupId = overrides.activeGroupId ?? null;
  const managerOpen = overrides.managerOpen ?? true;

  function Harness() {
    latestHook = useWorkspaceTemplateApi({
      verifiedUser,
      managerOpen,
      setManagerOpen,
      setBannerNotice,
      activeTemplateId,
      activeTemplateName,
      activeGroupId,
      ...overrides,
    });
    return null;
  }

  render(<Harness />);

  return {
    setManagerOpen,
    setBannerNotice,
    get hook() {
      if (!latestHook) {
        throw new Error('Hook not initialized');
      }
      return latestHook;
    },
  };
}

describe('useWorkspaceTemplateApi', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the active endpoint and schema when the manager opens', async () => {
    vi.spyOn(ApiService, 'listTemplateApiEndpoints').mockResolvedValue({
      endpoints: [
        {
          id: 'tep-1',
          templateId: 'tpl-1',
          templateName: 'Patient Intake',
          status: 'active',
          snapshotVersion: 2,
          keyPrefix: 'dpa_live_abc123',
          createdAt: '2026-03-25T12:00:00.000Z',
          updatedAt: '2026-03-25T12:00:00.000Z',
          publishedAt: '2026-03-25T12:00:00.000Z',
          lastUsedAt: null,
          usageCount: 0,
          fillPath: '/api/v1/fill/tep-1.pdf',
          schemaPath: '/api/template-api-endpoints/tep-1/schema',
        },
      ],
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
    });
    vi.spyOn(ApiService, 'getTemplateApiEndpointSchema').mockResolvedValue({
      endpoint: {
        id: 'tep-1',
        templateId: 'tpl-1',
        templateName: 'Patient Intake',
        status: 'active',
        snapshotVersion: 2,
        keyPrefix: 'dpa_live_abc123',
        createdAt: '2026-03-25T12:00:00.000Z',
        updatedAt: '2026-03-25T12:00:00.000Z',
        publishedAt: '2026-03-25T12:00:00.000Z',
        lastUsedAt: null,
        usageCount: 0,
        fillPath: '/api/v1/fill/tep-1.pdf',
        schemaPath: '/api/template-api-endpoints/tep-1/schema',
      },
      schema: {
        snapshotVersion: 2,
        defaultExportMode: 'flat',
        fields: [],
        checkboxFields: [],
        checkboxGroups: [],
        radioGroups: [],
        exampleData: {},
      },
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
      recentEvents: [
        {
          id: 'evt-1',
          eventType: 'published',
          outcome: 'success',
          createdAt: '2026-03-25T12:00:00.000Z',
          summary: 'Endpoint published',
          metadata: {},
        },
      ],
    });

    const harness = renderHarness();

    await waitFor(() => {
      expect(harness.hook.dialogProps.endpoint?.id).toBe('tep-1');
      expect(harness.hook.dialogProps.schema?.snapshotVersion).toBe(2);
      expect(harness.hook.dialogProps.limits?.requestsThisMonth).toBe(12);
      expect(harness.hook.dialogProps.recentEvents[0]?.eventType).toBe('published');
    });
  });

  it('prefers an active endpoint when duplicate records are returned for one template', async () => {
    const listSpy = vi.spyOn(ApiService, 'listTemplateApiEndpoints').mockResolvedValue({
      endpoints: [
        {
          id: 'tep-revoked',
          templateId: 'tpl-1',
          templateName: 'Patient Intake',
          status: 'revoked',
          snapshotVersion: 1,
          keyPrefix: null,
          createdAt: '2026-03-24T12:00:00.000Z',
          updatedAt: '2026-03-26T12:00:00.000Z',
          publishedAt: '2026-03-24T12:00:00.000Z',
          lastUsedAt: null,
          usageCount: 0,
          fillPath: '/api/v1/fill/tep-revoked.pdf',
          schemaPath: '/api/template-api-endpoints/tep-revoked/schema',
        },
        {
          id: 'tep-active',
          templateId: 'tpl-1',
          templateName: 'Patient Intake',
          status: 'active',
          snapshotVersion: 2,
          keyPrefix: 'dpa_live_active',
          createdAt: '2026-03-25T12:00:00.000Z',
          updatedAt: '2026-03-25T12:00:00.000Z',
          publishedAt: '2026-03-25T12:00:00.000Z',
          lastUsedAt: null,
          usageCount: 0,
          fillPath: '/api/v1/fill/tep-active.pdf',
          schemaPath: '/api/template-api-endpoints/tep-active/schema',
        },
      ],
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
    });
    const schemaSpy = vi.spyOn(ApiService, 'getTemplateApiEndpointSchema').mockResolvedValue({
      endpoint: {
        id: 'tep-active',
        templateId: 'tpl-1',
        templateName: 'Patient Intake',
        status: 'active',
        snapshotVersion: 2,
        keyPrefix: 'dpa_live_active',
        createdAt: '2026-03-25T12:00:00.000Z',
        updatedAt: '2026-03-25T12:00:00.000Z',
        publishedAt: '2026-03-25T12:00:00.000Z',
        lastUsedAt: null,
        usageCount: 0,
        fillPath: '/api/v1/fill/tep-active.pdf',
        schemaPath: '/api/template-api-endpoints/tep-active/schema',
      },
      schema: {
        snapshotVersion: 2,
        defaultExportMode: 'flat',
        fields: [],
        checkboxFields: [],
        checkboxGroups: [],
        radioGroups: [],
        exampleData: {},
      },
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
      recentEvents: [],
    });

    const harness = renderHarness();

    await waitFor(() => {
      expect(harness.hook.dialogProps.endpoint?.id).toBe('tep-active');
    });
    expect(listSpy).toHaveBeenCalledWith('tpl-1');
    expect(schemaSpy).toHaveBeenCalledWith('tep-active');
  });

  it('clears the one-time secret when the manager refreshes or closes', async () => {
    vi.spyOn(ApiService, 'listTemplateApiEndpoints').mockResolvedValue({
      endpoints: [
        {
          id: 'tep-1',
          templateId: 'tpl-1',
          templateName: 'Patient Intake',
          status: 'active',
          snapshotVersion: 2,
          keyPrefix: 'dpa_live_abc123',
          createdAt: '2026-03-25T12:00:00.000Z',
          updatedAt: '2026-03-25T12:00:00.000Z',
          publishedAt: '2026-03-25T12:00:00.000Z',
          lastUsedAt: null,
          usageCount: 0,
          fillPath: '/api/v1/fill/tep-1.pdf',
          schemaPath: '/api/template-api-endpoints/tep-1/schema',
        },
      ],
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
    });
    vi.spyOn(ApiService, 'getTemplateApiEndpointSchema').mockResolvedValue({
      endpoint: {
        id: 'tep-1',
        templateId: 'tpl-1',
        templateName: 'Patient Intake',
        status: 'active',
        snapshotVersion: 2,
        keyPrefix: 'dpa_live_abc123',
        createdAt: '2026-03-25T12:00:00.000Z',
        updatedAt: '2026-03-25T12:00:00.000Z',
        publishedAt: '2026-03-25T12:00:00.000Z',
        lastUsedAt: null,
        usageCount: 0,
        fillPath: '/api/v1/fill/tep-1.pdf',
        schemaPath: '/api/template-api-endpoints/tep-1/schema',
      },
      schema: {
        snapshotVersion: 2,
        defaultExportMode: 'flat',
        fields: [],
        checkboxFields: [],
        checkboxGroups: [],
        radioGroups: [],
        exampleData: {},
      },
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
      recentEvents: [],
    });
    vi.spyOn(ApiService, 'publishTemplateApiEndpoint').mockResolvedValue({
      created: true,
      secret: 'dpa_live_secret',
      endpoint: {
        id: 'tep-1',
        templateId: 'tpl-1',
        templateName: 'Patient Intake',
        status: 'active',
        snapshotVersion: 2,
        keyPrefix: 'dpa_live_abc123',
        createdAt: '2026-03-25T12:00:00.000Z',
        updatedAt: '2026-03-25T12:00:00.000Z',
        publishedAt: '2026-03-25T12:00:00.000Z',
        lastUsedAt: null,
        usageCount: 0,
        fillPath: '/api/v1/fill/tep-1.pdf',
        schemaPath: '/api/template-api-endpoints/tep-1/schema',
      },
      schema: {
        snapshotVersion: 2,
        defaultExportMode: 'flat',
        fields: [],
        checkboxFields: [],
        checkboxGroups: [],
        radioGroups: [],
        exampleData: {},
      },
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
      recentEvents: [],
    });

    const harness = renderHarness();

    await waitFor(() => {
      expect(harness.hook.dialogProps.endpoint?.id).toBe('tep-1');
    });

    await act(async () => {
      await harness.hook.dialogProps.onPublish('flat');
    });
    await waitFor(() => {
      expect(harness.hook.dialogProps.latestSecret).toBe('dpa_live_secret');
    });

    await act(async () => {
      await harness.hook.dialogProps.onRefresh();
    });
    await waitFor(() => {
      expect(harness.hook.dialogProps.latestSecret).toBeNull();
    });

    await act(async () => {
      await harness.hook.dialogProps.onPublish('flat');
    });
    await waitFor(() => {
      expect(harness.hook.dialogProps.latestSecret).toBe('dpa_live_secret');
    });

    await act(async () => {
      harness.hook.dialogProps.onClose();
    });
    await waitFor(() => {
      expect(harness.hook.dialogProps.latestSecret).toBeNull();
    });
  });

  it('preserves the last coherent endpoint/schema pair when a refresh schema read fails', async () => {
    vi.spyOn(ApiService, 'listTemplateApiEndpoints')
      .mockResolvedValueOnce({
        endpoints: [
          {
            id: 'tep-1',
            templateId: 'tpl-1',
            templateName: 'Patient Intake',
            status: 'active',
            snapshotVersion: 2,
            keyPrefix: 'dpa_live_abc123',
            createdAt: '2026-03-25T12:00:00.000Z',
            updatedAt: '2026-03-25T12:00:00.000Z',
            publishedAt: '2026-03-25T12:00:00.000Z',
            lastUsedAt: null,
            usageCount: 7,
            fillPath: '/api/v1/fill/tep-1.pdf',
            schemaPath: '/api/template-api-endpoints/tep-1/schema',
          },
        ],
        limits: {
          activeEndpointsMax: 1,
          activeEndpointsUsed: 1,
          requestsPerMonthMax: 250,
          requestsThisMonth: 12,
          requestUsageMonth: '2026-03',
          maxPagesPerRequest: 25,
          templatePageCount: 1,
        },
      })
      .mockResolvedValueOnce({
        endpoints: [
          {
            id: 'tep-2',
            templateId: 'tpl-1',
            templateName: 'Patient Intake v2',
            status: 'active',
            snapshotVersion: 3,
            keyPrefix: 'dpa_live_next',
            createdAt: '2026-03-26T12:00:00.000Z',
            updatedAt: '2026-03-26T12:00:00.000Z',
            publishedAt: '2026-03-26T12:00:00.000Z',
            lastUsedAt: null,
            usageCount: 8,
            fillPath: '/api/v1/fill/tep-2.pdf',
            schemaPath: '/api/template-api-endpoints/tep-2/schema',
          },
        ],
        limits: {
          activeEndpointsMax: 2,
          activeEndpointsUsed: 1,
          requestsPerMonthMax: 500,
          requestsThisMonth: 99,
          requestUsageMonth: '2026-04',
          maxPagesPerRequest: 25,
          templatePageCount: 2,
        },
      });
    vi.spyOn(ApiService, 'getTemplateApiEndpointSchema')
      .mockResolvedValueOnce({
        endpoint: {
          id: 'tep-1',
          templateId: 'tpl-1',
          templateName: 'Patient Intake',
          status: 'active',
          snapshotVersion: 2,
          keyPrefix: 'dpa_live_abc123',
          createdAt: '2026-03-25T12:00:00.000Z',
          updatedAt: '2026-03-25T12:00:00.000Z',
          publishedAt: '2026-03-25T12:00:00.000Z',
          lastUsedAt: null,
          usageCount: 7,
          fillPath: '/api/v1/fill/tep-1.pdf',
          schemaPath: '/api/template-api-endpoints/tep-1/schema',
        },
        schema: {
          snapshotVersion: 2,
          defaultExportMode: 'flat',
          fields: [{ key: 'full_name', fieldName: 'full_name', type: 'text', page: 1 }],
          checkboxFields: [],
          checkboxGroups: [],
          radioGroups: [],
          exampleData: { full_name: 'Ada Lovelace' },
        },
        limits: {
          activeEndpointsMax: 1,
          activeEndpointsUsed: 1,
          requestsPerMonthMax: 250,
          requestsThisMonth: 12,
          requestUsageMonth: '2026-03',
          maxPagesPerRequest: 25,
          templatePageCount: 1,
        },
        recentEvents: [
          {
            id: 'evt-1',
            eventType: 'published',
            outcome: 'success',
            createdAt: '2026-03-25T12:00:00.000Z',
            summary: 'Endpoint published',
            metadata: {},
          },
        ],
      })
      .mockRejectedValueOnce(new Error('Failed to load API Fill details.'));
    vi.spyOn(ApiService, 'publishTemplateApiEndpoint').mockResolvedValue({
      created: true,
      secret: 'dpa_live_secret',
      endpoint: {
        id: 'tep-1',
        templateId: 'tpl-1',
        templateName: 'Patient Intake',
        status: 'active',
        snapshotVersion: 2,
        keyPrefix: 'dpa_live_abc123',
        createdAt: '2026-03-25T12:00:00.000Z',
        updatedAt: '2026-03-25T12:00:00.000Z',
        publishedAt: '2026-03-25T12:00:00.000Z',
        lastUsedAt: null,
        usageCount: 7,
        fillPath: '/api/v1/fill/tep-1.pdf',
        schemaPath: '/api/template-api-endpoints/tep-1/schema',
      },
      schema: {
        snapshotVersion: 2,
        defaultExportMode: 'flat',
        fields: [{ key: 'full_name', fieldName: 'full_name', type: 'text', page: 1 }],
        checkboxFields: [],
        checkboxGroups: [],
        radioGroups: [],
        exampleData: { full_name: 'Ada Lovelace' },
      },
      limits: {
        activeEndpointsMax: 1,
        activeEndpointsUsed: 1,
        requestsPerMonthMax: 250,
        requestsThisMonth: 12,
        requestUsageMonth: '2026-03',
        maxPagesPerRequest: 25,
        templatePageCount: 1,
      },
      recentEvents: [
        {
          id: 'evt-1',
          eventType: 'published',
          outcome: 'success',
          createdAt: '2026-03-25T12:00:00.000Z',
          summary: 'Endpoint published',
          metadata: {},
        },
      ],
    });

    const harness = renderHarness();

    await waitFor(() => {
      expect(harness.hook.dialogProps.endpoint?.id).toBe('tep-1');
      expect(harness.hook.dialogProps.schema?.snapshotVersion).toBe(2);
    });

    await act(async () => {
      await harness.hook.dialogProps.onPublish('flat');
    });
    await waitFor(() => {
      expect(harness.hook.dialogProps.latestSecret).toBe('dpa_live_secret');
    });

    await act(async () => {
      await harness.hook.dialogProps.onRefresh();
    });

    await waitFor(() => {
      expect(harness.hook.dialogProps.error).toBe('Failed to load API Fill details.');
    });
    expect(harness.hook.dialogProps.latestSecret).toBeNull();
    expect(harness.hook.dialogProps.endpoint?.id).toBe('tep-1');
    expect(harness.hook.dialogProps.endpoint?.templateName).toBe('Patient Intake');
    expect(harness.hook.dialogProps.schema?.snapshotVersion).toBe(2);
    expect(harness.hook.dialogProps.schema?.fields[0]?.key).toBe('full_name');
    expect(harness.hook.dialogProps.recentEvents[0]?.eventType).toBe('published');
    expect(harness.hook.dialogProps.limits?.requestsThisMonth).toBe(99);
    expect(harness.hook.dialogProps.limits?.requestUsageMonth).toBe('2026-04');
    expect(harness.setBannerNotice).toHaveBeenCalledWith({
      tone: 'error',
      message: 'Failed to load API Fill details.',
    });
  });

});
