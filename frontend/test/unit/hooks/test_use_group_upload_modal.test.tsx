import { StrictMode } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useGroupUploadModal } from '../../../src/hooks/useGroupUploadModal';

const detectFieldsMock = vi.hoisted(() => vi.fn());
const loadPdfFromFileMock = vi.hoisted(() => vi.fn());
const extractFieldsFromPdfMock = vi.hoisted(() => vi.fn());
const getPdfPageCountMock = vi.hoisted(() => vi.fn());
const createTemplateSessionMock = vi.hoisted(() => vi.fn());
const renameFieldsMock = vi.hoisted(() => vi.fn());
const mapSchemaMock = vi.hoisted(() => vi.fn());
const materializeFormPdfMock = vi.hoisted(() => vi.fn());
const saveFormToProfileMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/detectionApi', () => ({
  detectFields: detectFieldsMock,
}));

vi.mock('../../../src/utils/pdf', () => ({
  loadPdfFromFile: loadPdfFromFileMock,
  extractFieldsFromPdf: extractFieldsFromPdfMock,
}));

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    getPdfPageCount: getPdfPageCountMock,
    createTemplateSession: createTemplateSessionMock,
    renameFields: renameFieldsMock,
    mapSchema: mapSchemaMock,
    materializeFormPdf: materializeFormPdfMock,
    saveFormToProfile: saveFormToProfileMock,
  },
}));

function createPdfDoc(numPages: number) {
  return {
    numPages,
    destroy: vi.fn().mockResolvedValue(undefined),
  };
}

function createPageCountPayload(pageCount: number, detectMaxPages = 10) {
  return {
    success: true,
    pageCount,
    detectMaxPages,
    withinDetectLimit: pageCount <= detectMaxPages,
  };
}

function createDetectionField(name = 'Field 1') {
  return {
    name,
    type: 'text',
    page: 1,
    rect: [10, 20, 100, 24],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function expectAbortableOptions() {
  return expect.objectContaining({
    signal: expect.any(AbortSignal),
  });
}

function createDeps(overrides: Record<string, any> = {}) {
  return {
    verifiedUser: { uid: 'user-1' } as any,
    userProfile: {
      role: 'pro',
      availableCredits: 20,
      creditsRemaining: 20,
      creditPricing: {
        pageBucketSize: 5,
        renameBaseCost: 1,
        remapBaseCost: 1,
        renameRemapBaseCost: 2,
      },
    },
    loadUserProfile: vi.fn().mockResolvedValue({
      role: 'pro',
      availableCredits: 20,
      creditsRemaining: 20,
      creditPricing: {
        pageBucketSize: 5,
        renameBaseCost: 1,
        remapBaseCost: 1,
        renameRemapBaseCost: 2,
      },
    }),
    profileLimits: {
      detectMaxPages: 10,
      savedFormsMax: 20,
    },
    savedFormsCount: 0,
    dataColumns: ['first_name'],
    schemaId: 'schema-1',
    schemaUploadInProgress: false,
    pendingSchemaPayload: null,
    persistSchemaPayload: vi.fn().mockResolvedValue('schema-1'),
    setSchemaUploadInProgress: vi.fn(),
    createGroup: vi.fn().mockResolvedValue({
      id: 'group-1',
      name: 'Packet Group',
      templateIds: ['saved-1'],
      templateCount: 1,
      templates: [],
    }),
    openGroup: vi.fn().mockResolvedValue(undefined),
    refreshSavedForms: vi.fn().mockResolvedValue(undefined),
    setBannerNotice: vi.fn(),
    ...overrides,
  };
}

function renderHookHarness(
  deps: ReturnType<typeof createDeps>,
  options: { strict?: boolean } = {},
) {
  let latest: ReturnType<typeof useGroupUploadModal> | null = null;

  function Harness() {
    latest = useGroupUploadModal(deps);
    return null;
  }

  render(options.strict ? <StrictMode><Harness /></StrictMode> : <Harness />);

  return {
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useGroupUploadModal', () => {
  beforeEach(() => {
    detectFieldsMock.mockReset();
    getPdfPageCountMock.mockReset();
    loadPdfFromFileMock.mockReset();
    extractFieldsFromPdfMock.mockReset();
    createTemplateSessionMock.mockReset();
    renameFieldsMock.mockReset();
    mapSchemaMock.mockReset();
    materializeFormPdfMock.mockReset();
    saveFormToProfileMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('computes per-document credit estimates for grouped uploads', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);

    getPdfPageCountMock
      .mockResolvedValueOnce(createPageCountPayload(3))
      .mockResolvedValueOnce(createPageCountPayload(7));

    await act(async () => {
      await hook.current.addFiles([
        new File(['a'], 'alpha.pdf', { type: 'application/pdf' }),
        new File(['b'], 'beta.pdf', { type: 'application/pdf' }),
      ]);
    });

    act(() => {
      hook.current.setWantsRename(true);
      hook.current.setWantsMap(true);
    });

    await waitFor(() =>
      expect(hook.current.creditEstimate).toMatchObject({
        documentCount: 2,
        totalPages: 10,
        totalCredits: 6,
      }),
    );
  });

  it('keeps page count updates alive under StrictMode remounts', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps, { strict: true });

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(2));

    await act(async () => {
      await hook.current.addFiles([new File(['a'], 'strict-mode.pdf', { type: 'application/pdf' })]);
    });

    await waitFor(() => {
      expect(hook.current.items).toHaveLength(1);
      expect(hook.current.items[0]).toMatchObject({
        name: 'strict-mode.pdf',
        pageCount: 2,
        status: 'ready',
        detail: '2 pages',
      });
    });
  });

  it('blocks grouped rename when credits are insufficient after summing each PDF separately', async () => {
    const deps = createDeps({
      userProfile: {
        role: 'pro',
        availableCredits: 1,
        creditsRemaining: 1,
        creditPricing: {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        },
      },
      loadUserProfile: vi.fn().mockResolvedValue({
        role: 'pro',
        availableCredits: 1,
        creditsRemaining: 1,
        creditPricing: {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        },
      }),
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock
      .mockResolvedValueOnce(createPageCountPayload(1))
      .mockResolvedValueOnce(createPageCountPayload(1));

    await act(async () => {
      await hook.current.addFiles([
        new File(['a'], 'alpha.pdf', { type: 'application/pdf' }),
        new File(['b'], 'beta.pdf', { type: 'application/pdf' }),
      ]);
    });

    act(() => {
      hook.current.setWantsRename(true);
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.localError).toContain('required=2');
    expect(detectFieldsMock).not.toHaveBeenCalled();
  });

  it('blocks grouped uploads when any PDF exceeds the detect page limit', async () => {
    const deps = createDeps({
      profileLimits: {
        detectMaxPages: 5,
        savedFormsMax: 20,
      },
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(8, 5));

    await act(async () => {
      await hook.current.addFiles([new File(['a'], 'oversize.pdf', { type: 'application/pdf' })]);
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.localError).toBe('Each PDF in this group must be 5 pages or fewer on your plan.');
    expect(detectFieldsMock).not.toHaveBeenCalled();
  });

  it('marks PDFs as failed when page counting stalls instead of leaving them loading forever', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);

    getPdfPageCountMock.mockRejectedValueOnce(
      new Error('Page counting timed out. Remove this PDF and try again.'),
    );

    await act(async () => {
      await hook.current.addFiles([new File(['a'], 'stalled.pdf', { type: 'application/pdf' })]);
    });

    expect(hook.current.items).toHaveLength(1);
    expect(hook.current.items[0]).toMatchObject({
      name: 'stalled.pdf',
      status: 'failed',
      error: 'Page counting timed out. Remove this PDF and try again.',
      detail: 'Page counting timed out. Remove this PDF and try again.',
      pageCount: null,
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.localError).toBe('Remove invalid PDFs before creating the group.');
    expect(detectFieldsMock).not.toHaveBeenCalled();
  });

  it('blocks grouped uploads that would exceed the saved forms limit', async () => {
    const deps = createDeps({
      savedFormsCount: 4,
      profileLimits: {
        detectMaxPages: 10,
        savedFormsMax: 4,
      },
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(1));

    await act(async () => {
      await hook.current.addFiles([new File(['a'], 'single.pdf', { type: 'application/pdf' })]);
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.localError).toContain('saved form limit (4 max)');
    expect(detectFieldsMock).not.toHaveBeenCalled();
  });

  it('persists a pending schema before map-only group processing starts', async () => {
    const deps = createDeps({
      schemaId: null,
      pendingSchemaPayload: { source: 'csv' },
      persistSchemaPayload: vi.fn().mockResolvedValue('schema-uploaded'),
    });
    const hook = renderHookHarness(deps);
    const file = new File(['a'], 'single.pdf', { type: 'application/pdf' });

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(2));
    detectFieldsMock.mockResolvedValue({
      sessionId: 'session-1',
      fields: [createDetectionField('Original Field')],
    });
    mapSchemaMock.mockResolvedValue({
      success: true,
      mappingResults: {
        mappings: [{ originalPdfField: 'Original Field', pdfField: 'first_name', confidence: 0.92 }],
        checkboxRules: [],
        checkboxHints: [],
        textTransformRules: [],
      },
    });
    materializeFormPdfMock.mockResolvedValue(new Blob(['pdf']));
    saveFormToProfileMock.mockResolvedValue({ success: true, id: 'saved-1', name: 'single' });

    await act(async () => {
      await hook.current.addFiles([file]);
    });

    act(() => {
      hook.current.setWantsMap(true);
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(deps.persistSchemaPayload).toHaveBeenCalledWith({ source: 'csv' });
    expect(mapSchemaMock).toHaveBeenCalledWith(
      'schema-uploaded',
      expect.any(Array),
      undefined,
      'session-1',
      expectAbortableOptions(),
    );
  });

  it('surfaces preflight profile refresh failures without starting uploads', async () => {
    const deps = createDeps({
      loadUserProfile: vi.fn().mockRejectedValue(new Error('Profile refresh failed.')),
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(1));

    await act(async () => {
      await hook.current.addFiles([new File(['a'], 'single.pdf', { type: 'application/pdf' })]);
    });

    act(() => {
      hook.current.setWantsRename(true);
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(detectFieldsMock).not.toHaveBeenCalled();
    expect(hook.current.localError).toBe('Profile refresh failed.');
    expect(hook.current.processing).toBe(false);
    expect(deps.setBannerNotice).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: 'error',
        message: 'Profile refresh failed.',
      }),
    );
  });

  it('does not start grouped uploads after the dialog is closed during preflight', async () => {
    const profileDeferred = deferred<any>();
    const deps = createDeps({
      loadUserProfile: vi.fn().mockReturnValue(profileDeferred.promise),
    });
    const hook = renderHookHarness(deps);
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal('confirm', confirmMock);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(1));

    await act(async () => {
      await hook.current.addFiles([new File(['a'], 'single.pdf', { type: 'application/pdf' })]);
    });

    act(() => {
      hook.current.setWantsRename(true);
    });

    void hook.current.confirm();
    await waitFor(() => expect(deps.loadUserProfile).toHaveBeenCalledTimes(1));

    act(() => {
      hook.current.closeDialog();
    });

    expect(confirmMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      profileDeferred.resolve({
        role: 'pro',
        availableCredits: 20,
        creditsRemaining: 20,
        creditPricing: {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        },
      });
    });

    await waitFor(() => expect(hook.current.processing).toBe(false));
    expect(detectFieldsMock).not.toHaveBeenCalled();
    expect(deps.createGroup).not.toHaveBeenCalled();
  });

  it('processes multiple PDFs, saves them, creates the group, and opens it', async () => {
    const deps = createDeps({
      createGroup: vi.fn().mockResolvedValue({
        id: 'group-42',
        name: 'Packet Group',
        templateIds: ['saved-1', 'saved-2'],
        templateCount: 2,
        templates: [],
      }),
    });
    const hook = renderHookHarness(deps);
    const firstFile = new File(['a'], 'alpha.pdf', { type: 'application/pdf' });
    const secondFile = new File(['b'], 'beta.pdf', { type: 'application/pdf' });

    getPdfPageCountMock
      .mockResolvedValueOnce(createPageCountPayload(2))
      .mockResolvedValueOnce(createPageCountPayload(6));
    detectFieldsMock
      .mockResolvedValueOnce({
        sessionId: 'session-1',
        fields: [createDetectionField('Alpha Field')],
      })
      .mockResolvedValueOnce({
        sessionId: 'session-2',
        fields: [createDetectionField('Beta Field')],
      });
    renameFieldsMock
      .mockResolvedValueOnce({
        success: true,
        fields: [{ originalName: 'Alpha Field', name: 'first_name' }],
        checkboxRules: [],
        checkboxHints: [],
      })
      .mockResolvedValueOnce({
        success: true,
        fields: [{ originalName: 'Beta Field', name: 'first_name' }],
        checkboxRules: [],
        checkboxHints: [],
      });
    materializeFormPdfMock
      .mockResolvedValueOnce(new Blob(['alpha']))
      .mockResolvedValueOnce(new Blob(['beta']));
    saveFormToProfileMock
      .mockResolvedValueOnce({ success: true, id: 'saved-1', name: 'alpha' })
      .mockResolvedValueOnce({ success: true, id: 'saved-2', name: 'beta' });

    await act(async () => {
      await hook.current.addFiles([firstFile, secondFile]);
    });

    act(() => {
      hook.current.setGroupName('Packet Group');
      hook.current.setWantsRename(true);
      hook.current.setWantsMap(true);
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(renameFieldsMock).toHaveBeenCalledTimes(2);
    expect(renameFieldsMock).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        sessionId: 'session-1',
        schemaId: 'schema-1',
      }),
      expectAbortableOptions(),
    );
    expect(renameFieldsMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        sessionId: 'session-2',
        schemaId: 'schema-1',
      }),
      expectAbortableOptions(),
    );
    expect(saveFormToProfileMock).toHaveBeenCalledTimes(2);
    expect(deps.createGroup).toHaveBeenCalledWith({
      name: 'Packet Group',
      templateIds: ['saved-1', 'saved-2'],
    }, expectAbortableOptions());
    expect(deps.openGroup).toHaveBeenCalledWith('group-42');
    expect(deps.setBannerNotice).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: 'success',
        message: 'Created group "Packet Group" with 2 templates.',
      }),
    );
  });

  it('keeps detection queued ahead of rename/save work for the next PDF', async () => {
    const deps = createDeps({
      createGroup: vi.fn().mockResolvedValue({
        id: 'group-queue',
        name: 'Queued Packet',
        templateIds: ['saved-1', 'saved-2', 'saved-3'],
        templateCount: 3,
        templates: [],
      }),
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock
      .mockResolvedValueOnce(createPageCountPayload(1))
      .mockResolvedValueOnce(createPageCountPayload(1))
      .mockResolvedValueOnce(createPageCountPayload(1));

    const detect1 = deferred<any>();
    const detect2 = deferred<any>();
    const detect3 = deferred<any>();
    const rename1 = deferred<any>();
    const rename2 = deferred<any>();
    const rename3 = deferred<any>();
    const materialize1 = deferred<any>();
    const materialize2 = deferred<any>();
    const materialize3 = deferred<any>();
    const save1 = deferred<any>();
    const save2 = deferred<any>();
    const save3 = deferred<any>();

    detectFieldsMock
      .mockImplementationOnce(() => detect1.promise)
      .mockImplementationOnce(() => detect2.promise)
      .mockImplementationOnce(() => detect3.promise);
    renameFieldsMock
      .mockImplementationOnce(() => rename1.promise)
      .mockImplementationOnce(() => rename2.promise)
      .mockImplementationOnce(() => rename3.promise);
    materializeFormPdfMock
      .mockImplementationOnce(() => materialize1.promise)
      .mockImplementationOnce(() => materialize2.promise)
      .mockImplementationOnce(() => materialize3.promise);
    saveFormToProfileMock
      .mockImplementationOnce(() => save1.promise)
      .mockImplementationOnce(() => save2.promise)
      .mockImplementationOnce(() => save3.promise);

    await act(async () => {
      await hook.current.addFiles([
        new File(['1'], 'one.pdf', { type: 'application/pdf' }),
        new File(['2'], 'two.pdf', { type: 'application/pdf' }),
        new File(['3'], 'three.pdf', { type: 'application/pdf' }),
      ]);
    });

    act(() => {
      hook.current.setGroupName('Queued Packet');
      hook.current.setWantsRename(true);
    });

    void hook.current.confirm();
    await waitFor(() => expect(detectFieldsMock).toHaveBeenCalledTimes(1));

    detect1.resolve({ sessionId: 'session-1', fields: [createDetectionField('Alpha Field')] });
    await waitFor(() => {
      expect(renameFieldsMock).toHaveBeenCalledTimes(1);
      expect(detectFieldsMock).toHaveBeenCalledTimes(2);
    });

    detect2.resolve({ sessionId: 'session-2', fields: [createDetectionField('Beta Field')] });
    await waitFor(() => expect(detectFieldsMock).toHaveBeenCalledTimes(3));

    rename1.resolve({
      success: true,
      fields: [{ originalName: 'Alpha Field', name: 'first_name' }],
      checkboxRules: [],
      checkboxHints: [],
    });
    await waitFor(() => expect(materializeFormPdfMock).toHaveBeenCalledTimes(1));
    materialize1.resolve(new Blob(['one']));
    await waitFor(() => expect(saveFormToProfileMock).toHaveBeenCalledTimes(1));
    save1.resolve({ success: true, id: 'saved-1', name: 'one' });

    await waitFor(() => expect(renameFieldsMock).toHaveBeenCalledTimes(2));
    rename2.resolve({
      success: true,
      fields: [{ originalName: 'Beta Field', name: 'first_name' }],
      checkboxRules: [],
      checkboxHints: [],
    });
    await waitFor(() => expect(materializeFormPdfMock).toHaveBeenCalledTimes(2));
    materialize2.resolve(new Blob(['two']));
    await waitFor(() => expect(saveFormToProfileMock).toHaveBeenCalledTimes(2));
    save2.resolve({ success: true, id: 'saved-2', name: 'two' });

    detect3.resolve({ sessionId: 'session-3', fields: [createDetectionField('Gamma Field')] });
    await waitFor(() => expect(renameFieldsMock).toHaveBeenCalledTimes(3));
    rename3.resolve({
      success: true,
      fields: [{ originalName: 'Gamma Field', name: 'first_name' }],
      checkboxRules: [],
      checkboxHints: [],
    });
    await waitFor(() => expect(materializeFormPdfMock).toHaveBeenCalledTimes(3));
    materialize3.resolve(new Blob(['three']));
    await waitFor(() => expect(saveFormToProfileMock).toHaveBeenCalledTimes(3));
    save3.resolve({ success: true, id: 'saved-3', name: 'three' });

    await waitFor(() => expect(deps.createGroup).toHaveBeenCalledWith({
      name: 'Queued Packet',
      templateIds: ['saved-1', 'saved-2', 'saved-3'],
    }, expectAbortableOptions()));
  });

  it('fails timed-out detection items instead of saving incomplete templates', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(1));
    detectFieldsMock.mockResolvedValueOnce({
      sessionId: 'session-timeout',
      status: 'running',
      timedOut: true,
    });

    await act(async () => {
      await hook.current.addFiles([new File(['1'], 'slow.pdf', { type: 'application/pdf' })]);
    });

    act(() => {
      hook.current.setGroupName('Slow Packet');
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(materializeFormPdfMock).not.toHaveBeenCalled();
    expect(saveFormToProfileMock).not.toHaveBeenCalled();
    expect(deps.createGroup).not.toHaveBeenCalled();
    expect(hook.current.localError).toBe('Detection is still running on the backend. Retry this PDF after it finishes.');
    expect(deps.setBannerNotice).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: 'error',
        message: 'Detection is still running on the backend. Retry this PDF after it finishes.',
      }),
    );
  });

  it('continues processing after one PDF fails and creates a partial group from the successes', async () => {
    const deps = createDeps({
      createGroup: vi.fn().mockResolvedValue({
        id: 'group-partial',
        name: 'Partial Packet',
        templateIds: ['saved-2'],
        templateCount: 1,
        templates: [],
      }),
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock
      .mockResolvedValueOnce(createPageCountPayload(1))
      .mockResolvedValueOnce(createPageCountPayload(1));
    detectFieldsMock
      .mockRejectedValueOnce(new Error('Detector stalled'))
      .mockResolvedValueOnce({
        sessionId: 'session-2',
        fields: [createDetectionField('Beta Field')],
      });
    materializeFormPdfMock.mockResolvedValueOnce(new Blob(['two']));
    saveFormToProfileMock.mockResolvedValueOnce({ success: true, id: 'saved-2', name: 'two' });

    await act(async () => {
      await hook.current.addFiles([
        new File(['1'], 'one.pdf', { type: 'application/pdf' }),
        new File(['2'], 'two.pdf', { type: 'application/pdf' }),
      ]);
    });

    act(() => {
      hook.current.setGroupName('Partial Packet');
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(detectFieldsMock).toHaveBeenCalledTimes(2);
    expect(saveFormToProfileMock).toHaveBeenCalledTimes(1);
    expect(deps.createGroup).toHaveBeenCalledWith({
      name: 'Partial Packet',
      templateIds: ['saved-2'],
    }, expectAbortableOptions());
    expect(deps.setBannerNotice).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: 'warning',
        message: 'Created group "Partial Packet" with 1 saved template and 1 failure.',
      }),
    );
  });

  it('surfaces saved templates when final group creation fails after upload success', async () => {
    const deps = createDeps({
      createGroup: vi.fn().mockRejectedValue(new Error('Group name already exists')),
    });
    const hook = renderHookHarness(deps);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(1));
    detectFieldsMock.mockResolvedValueOnce({
      sessionId: 'session-1',
      fields: [createDetectionField('Alpha Field')],
    });
    materializeFormPdfMock.mockResolvedValueOnce(new Blob(['one']));
    saveFormToProfileMock.mockResolvedValueOnce({ success: true, id: 'saved-1', name: 'one' });

    await act(async () => {
      await hook.current.addFiles([
        new File(['1'], 'one.pdf', { type: 'application/pdf' }),
      ]);
    });

    act(() => {
      hook.current.setGroupName('Existing Packet');
    });

    await act(async () => {
      await hook.current.confirm();
    });

    expect(deps.createGroup).toHaveBeenCalledWith({
      name: 'Existing Packet',
      templateIds: ['saved-1'],
    }, expectAbortableOptions());
    expect(hook.current.localError).toBe(
      'Saved 1 template, but failed to create group "Existing Packet". The saved templates remain in your account without a group.',
    );
    expect(deps.setBannerNotice).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: 'warning',
        message: 'Saved 1 template, but failed to create group "Existing Packet". The saved templates remain in your account without a group.',
      }),
    );
  });

  it('stops the remaining queued PDFs after close and keeps already-saved templates', async () => {
    const deps = createDeps({
      createGroup: vi.fn().mockResolvedValue({
        id: 'group-stopped',
        name: 'Stopped Packet',
        templateIds: ['saved-1'],
        templateCount: 1,
        templates: [],
      }),
    });
    const hook = renderHookHarness(deps);
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal('confirm', confirmMock);

    getPdfPageCountMock
      .mockResolvedValueOnce(createPageCountPayload(1))
      .mockResolvedValueOnce(createPageCountPayload(1))
      .mockResolvedValueOnce(createPageCountPayload(1));

    detectFieldsMock
      .mockResolvedValueOnce({
        sessionId: 'session-1',
        fields: [createDetectionField('Alpha Field')],
      })
      .mockImplementationOnce((_file: File, options?: { signal?: AbortSignal }) => new Promise((_, reject) => {
        options?.signal?.addEventListener('abort', () => {
          reject(new DOMException('Detection polling aborted.', 'AbortError'));
        }, { once: true });
      }));

    materializeFormPdfMock.mockResolvedValueOnce(new Blob(['one']));
    saveFormToProfileMock.mockResolvedValueOnce({ success: true, id: 'saved-1', name: 'one' });

    await act(async () => {
      await hook.current.addFiles([
        new File(['1'], 'one.pdf', { type: 'application/pdf' }),
        new File(['2'], 'two.pdf', { type: 'application/pdf' }),
        new File(['3'], 'three.pdf', { type: 'application/pdf' }),
      ]);
    });

    act(() => {
      hook.current.setGroupName('Stopped Packet');
    });

    void hook.current.confirm();
    await waitFor(() => expect(saveFormToProfileMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(detectFieldsMock).toHaveBeenCalledTimes(2));

    act(() => {
      hook.current.closeDialog();
    });

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(deps.createGroup).toHaveBeenCalledWith({
      name: 'Stopped Packet',
      templateIds: ['saved-1'],
    }, expectAbortableOptions()));

    expect(detectFieldsMock).toHaveBeenCalledTimes(2);
    expect(deps.openGroup).not.toHaveBeenCalled();
  });

  it('aborts an in-flight save when the grouped upload dialog is closed', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);
    const confirmMock = vi.fn(() => true);
    vi.stubGlobal('confirm', confirmMock);

    getPdfPageCountMock.mockResolvedValueOnce(createPageCountPayload(1));
    detectFieldsMock.mockResolvedValueOnce({
      sessionId: 'session-1',
      fields: [createDetectionField('Alpha Field')],
    });
    materializeFormPdfMock.mockResolvedValueOnce(new Blob(['one']));
    saveFormToProfileMock.mockImplementationOnce((
      _blob: Blob,
      _name: string,
      _sessionId?: string,
      _overwriteFormId?: string,
      _checkboxRules?: Array<Record<string, unknown>>,
      _checkboxHints?: Array<Record<string, unknown>>,
      _textTransformRules?: Array<Record<string, unknown>>,
      _editorSnapshot?: Record<string, unknown>,
      options?: { signal?: AbortSignal },
    ) => new Promise((_, reject) => {
      options?.signal?.addEventListener('abort', () => {
        reject(new DOMException('Request aborted.', 'AbortError'));
      }, { once: true });
    }));

    await act(async () => {
      await hook.current.addFiles([new File(['1'], 'one.pdf', { type: 'application/pdf' })]);
    });

    act(() => {
      hook.current.setGroupName('Abort Save Packet');
    });

    void hook.current.confirm();
    await waitFor(() => expect(saveFormToProfileMock).toHaveBeenCalledTimes(1));

    act(() => {
      hook.current.closeDialog();
    });

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(hook.current.processing).toBe(false));

    expect(saveFormToProfileMock).toHaveBeenCalledWith(
      expect.any(Blob),
      'one',
      'session-1',
      undefined,
      [],
      [],
      [],
      undefined,
      expectAbortableOptions(),
    );
    expect(deps.createGroup).not.toHaveBeenCalled();
    expect(deps.openGroup).not.toHaveBeenCalled();
  });
});
