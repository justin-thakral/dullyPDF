import { act, render } from '@testing-library/react';
import { useRef, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useOpenAiPipeline, type UseOpenAiPipelineDeps } from '../../../src/hooks/useOpenAiPipeline';
import type { PdfField } from '../../../src/types';

const createSavedFormSessionMock = vi.hoisted(() => vi.fn());
const renameFieldsMock = vi.hoisted(() => vi.fn());
const mapSchemaMock = vi.hoisted(() => vi.fn());
const fetchDetectionStatusMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    createSavedFormSession: createSavedFormSessionMock,
    renameFields: renameFieldsMock,
    mapSchema: mapSchemaMock,
  },
}));

vi.mock('../../../src/services/detectionApi', () => ({
  fetchDetectionStatus: fetchDetectionStatusMock,
}));

function createField(name = 'Field 1'): PdfField {
  return {
    id: 'field-1',
    name,
    type: 'text',
    page: 1,
    rect: { x: 10, y: 10, width: 120, height: 24 },
    value: null,
  };
}

function renderHookHarness(overrides: Partial<UseOpenAiPipelineDeps> = {}) {
  let latest: ReturnType<typeof useOpenAiPipeline> | null = null;
  const resetFieldHistory = vi.fn();
  const updateFieldsWith = vi.fn();

  function Harness() {
    const fieldsRef = useRef<PdfField[]>([createField()]);
    const loadTokenRef = useRef(1);
    const pendingAutoActionsRef = useRef(null);
    const [detectSessionId, setDetectSessionId] = useState<string | null>(null);
    const [mappingSessionId, setMappingSessionId] = useState<string | null>(null);
    const {
      detectSessionId: overrideDetectSessionId,
      setDetectSessionId: overrideSetDetectSessionId,
      setMappingSessionId: overrideSetMappingSessionId,
      pendingAutoActionsRef: overridePendingAutoActionsRef,
      ...restOverrides
    } = overrides;

    latest = useOpenAiPipeline({
      verifiedUser: { uid: 'user-1' } as any,
      fieldsRef,
      loadTokenRef,
      detectSessionId: overrideDetectSessionId ?? detectSessionId,
      setDetectSessionId: overrideSetDetectSessionId ?? setDetectSessionId,
      setMappingSessionId: overrideSetMappingSessionId ?? setMappingSessionId,
      activeSavedFormId: 'saved-form-1',
      pageCount: 3,
      dataColumns: ['first_name'],
      schemaId: 'schema-1',
      pendingAutoActionsRef: overridePendingAutoActionsRef ?? pendingAutoActionsRef,
      setBannerNotice: vi.fn(),
      requestConfirm: vi.fn().mockResolvedValue(true),
      loadUserProfile: vi.fn().mockResolvedValue(null),
      resetFieldHistory,
      updateFieldsWith,
      setIdentifierKey: vi.fn(),
      hasDocument: true,
      fieldsCount: 1,
      dataSourceKind: 'csv',
      hasSchemaOrPending: true,
      ...restOverrides,
    });
    void mappingSessionId;
    return null;
  }

  render(<Harness />);

  return {
    resetFieldHistory,
    updateFieldsWith,
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useOpenAiPipeline', () => {
  beforeEach(() => {
    createSavedFormSessionMock.mockReset();
    renameFieldsMock.mockReset();
    mapSchemaMock.mockReset();
    fetchDetectionStatusMock.mockReset();
  });

  it('recreates the saved-form session lazily before rename when prewarm failed', async () => {
    createSavedFormSessionMock.mockResolvedValue({ sessionId: 'saved-session-1' });
    renameFieldsMock.mockResolvedValue({
      success: true,
      fields: [{ originalName: 'Field 1', name: 'Renamed Field' }],
      checkboxRules: [],
    });
    mapSchemaMock.mockResolvedValue({ success: true });
    fetchDetectionStatusMock.mockResolvedValue({ status: 'complete' });

    const hook = renderHookHarness();

    expect(hook.current.canRename).toBe(true);

    await act(async () => {
      await hook.current.runOpenAiRename({ confirm: false });
    });

    expect(createSavedFormSessionMock).toHaveBeenCalledWith(
      'saved-form-1',
      expect.objectContaining({
        pageCount: 3,
        fields: [expect.objectContaining({ name: 'Field 1' })],
      }),
    );
    expect(renameFieldsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: 'saved-session-1',
        templateFields: [expect.objectContaining({ name: 'Field 1' })],
      }),
    );
    expect(hook.resetFieldHistory).toHaveBeenCalledWith([
      expect.objectContaining({ name: 'Renamed Field' }),
    ]);
  });
});
