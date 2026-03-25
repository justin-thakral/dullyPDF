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

});
