import { act, render, waitFor } from '@testing-library/react';
import { useRef, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useWorkspaceGroupCoordinator } from '../../../src/hooks/useWorkspaceGroupCoordinator';

const useGroupTemplateCacheMock = vi.hoisted(() => vi.fn());
const useGroupUploadModalMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/hooks/useGroupTemplateCache', () => ({
  resolveGroupTemplates: (
    group: { templateIds: string[] } | null,
    savedForms: Array<{ id: string; name: string; createdAt: string }>,
  ) => {
    if (!group) return [];
    const savedFormLookup = new Map(savedForms.map((form) => [form.id, form] as const));
    return group.templateIds
      .map((templateId) => savedFormLookup.get(templateId) ?? null)
      .filter((entry): entry is { id: string; name: string; createdAt: string } => Boolean(entry));
  },
  useGroupTemplateCache: (...args: unknown[]) => useGroupTemplateCacheMock(...args),
}));

vi.mock('../../../src/hooks/useGroupUploadModal', () => ({
  useGroupUploadModal: (...args: unknown[]) => useGroupUploadModalMock(...args),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function renderHarness(options?: {
  handleSelectSavedForm?: ReturnType<typeof vi.fn>;
  refreshGroups?: ReturnType<typeof vi.fn>;
}) {
  const pendingOpen = options?.handleSelectSavedForm ?? vi.fn().mockResolvedValue(undefined);
  const refreshGroups = options?.refreshGroups ?? vi.fn().mockResolvedValue([]);
  let latestHook: ReturnType<typeof useWorkspaceGroupCoordinator> | null = null;

  function Harness() {
    const [activeSavedFormId, setActiveSavedFormId] = useState<string | null>(null);
    const [activeSavedFormName, setActiveSavedFormName] = useState<string | null>(null);
    const fieldsRef = useRef<any[]>([]);
    const historyRef = useRef<{ undo: any[][]; redo: any[][] }>({ undo: [], redo: [] });

    latestHook = useWorkspaceGroupCoordinator({
      verifiedUser: { uid: 'user-1' },
      userProfile: null,
      loadUserProfile: vi.fn().mockResolvedValue(null),
      profileLimits: { detectMaxPages: 10, fillableMaxPages: 20, savedFormsMax: 10, fillLinksActiveMax: 1, fillLinkResponsesMax: 5 },
      dialog: {
        setBannerNotice: vi.fn(),
        requestConfirm: vi.fn().mockResolvedValue(true),
      },
      groups: {
        groups: [{
          id: 'group-1',
          name: 'Admissions',
          templateIds: ['tpl-a', 'tpl-b'],
          templateCount: 2,
          templates: [],
        }],
        groupsLoading: false,
        groupsCreating: false,
        updatingGroupId: null,
        deletingGroupId: null,
        selectedGroupFilterId: 'all',
        setSelectedGroupFilterId: vi.fn(),
        refreshGroups,
        createGroup: vi.fn(),
        updateExistingGroup: vi.fn(),
        deleteGroup: vi.fn(),
      },
      savedForms: {
        savedForms: [
          { id: 'tpl-a', name: 'Alpha Packet', createdAt: '2025-01-01T00:00:00.000Z' },
          { id: 'tpl-b', name: 'Bravo Intake', createdAt: '2025-01-02T00:00:00.000Z' },
        ],
        activeSavedFormId,
        activeSavedFormName,
        setActiveSavedFormId,
        setActiveSavedFormName,
        deleteSavedFormById: vi.fn().mockResolvedValue(true),
        handleSavedFormsLimitDelete: vi.fn().mockResolvedValue(true),
        refreshSavedForms: vi.fn().mockResolvedValue([]),
      },
      detection: {
        handleSelectSavedForm: pendingOpen,
        handleFillableUpload: vi.fn().mockResolvedValue(undefined),
        runDetectUpload: vi.fn().mockResolvedValue(undefined),
        isProcessing: true,
        detectSessionId: null,
        mappingSessionId: null,
        setDetectSessionId: vi.fn(),
        setMappingSessionId: vi.fn(),
        setIsProcessing: vi.fn(),
        setProcessingMode: vi.fn(),
      },
      openAi: {
        renameInProgress: false,
        mappingInProgress: false,
        mapSchemaInProgress: false,
        hasRenamedFields: false,
        hasMappedSchema: false,
        checkboxRules: [],
        checkboxHints: [],
        textTransformRules: [],
        setRenameInProgress: vi.fn(),
        setMappingInProgress: vi.fn(),
        setHasRenamedFields: vi.fn(),
        setHasMappedSchema: vi.fn(),
        setCheckboxRules: vi.fn(),
        setCheckboxHints: vi.fn(),
        setTextTransformRules: vi.fn(),
        setOpenAiError: vi.fn(),
        runOpenAiRename: vi.fn(),
        runOpenAiMapSchema: vi.fn(),
        handleMappingSuccess: vi.fn(),
      },
      document: {
        pdfDoc: null,
        sourceFile: null,
        sourceFileName: null,
        pageSizes: {},
        pageCount: 0,
        currentPage: 1,
        scale: 1,
        setLoadError: vi.fn(),
        setShowHomepage: vi.fn(),
        setShowSearchFill: vi.fn(),
        setSearchFillPreset: vi.fn(),
        setShowFillLinkManager: vi.fn(),
        setSourceFile: vi.fn(),
        setSourceFileName: vi.fn(),
        setSourceFileIsDemo: vi.fn(),
        setPdfDoc: vi.fn(),
        setPageSizes: vi.fn(),
        setPageCount: vi.fn(),
        setCurrentPage: vi.fn(),
        setScale: vi.fn(),
        setPendingPageJump: vi.fn(),
        bumpSearchFillSession: vi.fn(),
      },
      pdfState: {
        setPdfDoc: vi.fn(),
        setPageSizes: vi.fn(),
        setPageCount: vi.fn(),
        setCurrentPage: vi.fn(),
        setScale: vi.fn(),
        setPendingPageJump: vi.fn(),
      },
      fieldHistory: {
        fields: [],
        fieldsRef,
        historyRef,
        historyTick: 0,
        restoreState: vi.fn(),
      },
      fieldSelection: {
        selectedFieldId: null,
        setSelectedFieldId: vi.fn(),
        handleFieldsChange: vi.fn(),
      },
      display: {
        showFields: true,
        showFieldNames: true,
        showFieldInfo: false,
        transformMode: false,
        setShowFields: vi.fn(),
        setShowFieldNames: vi.fn(),
        setShowFieldInfo: vi.fn(),
        setTransformMode: vi.fn(),
      },
      dataSource: {
        schemaId: null,
        schemaUploadInProgress: false,
        pendingSchemaPayload: null,
        persistSchemaPayload: vi.fn(),
        setSchemaUploadInProgress: vi.fn(),
        dataColumns: [],
        dataSourceKind: 'none',
        resolveSchemaForMapping: vi.fn().mockResolvedValue(null),
      },
      markSavedFillLinkSnapshot: vi.fn(),
    });

    return null;
  }

  render(<Harness />);

  return {
    pendingOpen,
    refreshGroups,
    get hook() {
      if (!latestHook) {
        throw new Error('hook not initialized');
      }
      return latestHook;
    },
  };
}

describe('useWorkspaceGroupCoordinator', () => {
  beforeEach(() => {
    useGroupTemplateCacheMock.mockReset();
    useGroupUploadModalMock.mockReset();
    useGroupTemplateCacheMock.mockReturnValue({
      activeGroupTemplates: [],
      groupTemplateStatusById: {},
      groupSwitchingTemplateId: null,
      clearGroupTemplateCache: vi.fn(),
      captureActiveGroupTemplateSnapshot: vi.fn(),
      ensureGroupTemplateSnapshot: vi.fn(),
      resolveDirtyGroupTemplateRecords: vi.fn().mockReturnValue([]),
      resolveGroupTemplateDirtyNames: vi.fn().mockReturnValue([]),
      isActiveGroupTemplateDirty: vi.fn().mockReturnValue(false),
      markGroupTemplatesPersisted: vi.fn(),
      handleSelectActiveGroupTemplate: vi.fn(),
      handleFillSearchTargets: vi.fn(),
    });
    useGroupUploadModalMock.mockReturnValue({
      reset: vi.fn(),
    });
  });

  it('tracks the pending group template while opening the first form in a group', async () => {
    const pendingOpen = deferred<void>();
    const handleSelectSavedForm = vi.fn(() => pendingOpen.promise);
    const harness = renderHarness({ handleSelectSavedForm });

    await act(async () => {
      void harness.hook.handleOpenGroup('group-1');
    });

    await waitFor(() => {
      expect(handleSelectSavedForm).toHaveBeenCalledWith(
        'tpl-a',
        expect.any(Object),
        expect.objectContaining({ source: 'saved-group' }),
      );
    });
    expect(harness.hook.pendingGroupTemplateId).toBe('tpl-a');

    await act(async () => {
      pendingOpen.resolve(undefined);
      await pendingOpen.promise;
    });

    await waitFor(() => {
      expect(harness.hook.pendingGroupTemplateId).toBeNull();
    });
  });

  it('does not trigger a redundant group refresh on mount', async () => {
    const refreshGroups = vi.fn().mockResolvedValue([]);
    renderHarness({ refreshGroups });

    await waitFor(() => {
      expect(refreshGroups).not.toHaveBeenCalled();
    });
  });
});
