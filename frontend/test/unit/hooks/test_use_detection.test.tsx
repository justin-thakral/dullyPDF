import { act, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDetection } from '../../../src/hooks/useDetection';

const detectFieldsMock = vi.hoisted(() => vi.fn());
const pollDetectionStatusMock = vi.hoisted(() => vi.fn());
const loadPdfFromFileMock = vi.hoisted(() => vi.fn());
const loadPageSizesMock = vi.hoisted(() => vi.fn());
const extractFieldsFromPdfMock = vi.hoisted(() => vi.fn());
const touchSessionMock = vi.hoisted(() => vi.fn());
const loadSavedFormMock = vi.hoisted(() => vi.fn());
const downloadSavedFormMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/detectionApi', () => ({
  detectFields: detectFieldsMock,
  pollDetectionStatus: pollDetectionStatusMock,
}));

vi.mock('../../../src/utils/pdf', () => ({
  loadPdfFromFile: loadPdfFromFileMock,
  loadPageSizes: loadPageSizesMock,
  extractFieldsFromPdf: extractFieldsFromPdfMock,
}));

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    createTemplateSession: vi.fn(),
    createSavedFormSession: vi.fn(),
    updateSavedFormEditorSnapshot: vi.fn(),
    loadSavedForm: loadSavedFormMock,
    downloadSavedForm: downloadSavedFormMock,
    touchSession: touchSessionMock,
  },
}));

function createPdfDoc(numPages = 1) {
  return {
    numPages,
    destroy: vi.fn().mockResolvedValue(undefined),
    getData: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
  };
}

function createPdfState() {
  return {
    setPdfDoc: vi.fn(),
    setPageSizes: vi.fn(),
    setPageCount: vi.fn(),
    setCurrentPage: vi.fn(),
    setScale: vi.fn(),
    setPendingPageJump: vi.fn(),
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

function createDeps(overrides: Record<string, unknown> = {}) {
  const fieldsRef = { current: [] as any[] };
  const historyRef = { current: { undo: [] as any[][], redo: [] as any[][] } };
  const setSearchFillSessionId = vi.fn();
  const resetFieldHistory = vi.fn((fields: any[] = []) => {
    fieldsRef.current = fields;
    historyRef.current = { undo: [], redo: [] };
  });
  const updateFields = vi.fn((fields: any[]) => {
    fieldsRef.current = fields;
  });
  return {
    verifiedUser: { uid: 'user-1' } as any,
    profileLimits: { detectMaxPages: 10, fillableMaxPages: 10 },
    fieldsRef,
    historyRef,
    resetFieldHistory,
    updateFields,
    setSelectedFieldId: vi.fn(),
    clearWorkspace: vi.fn(),
    setBannerNotice: vi.fn(),
    setShowHomepage: vi.fn(),
    setHasRenamedFields: vi.fn(),
    setHasMappedSchema: vi.fn(),
    setCheckboxRules: vi.fn(),
    setRadioGroupSuggestions: vi.fn(),
    setTextTransformRules: vi.fn(),
    setSchemaError: vi.fn(),
    setOpenAiError: vi.fn(),
    setSourceFile: vi.fn(),
    setSourceFileName: vi.fn(),
    setSourceFileIsDemo: vi.fn(),
    markSavedFillLinkSnapshot: vi.fn(),
    setActiveSavedFormId: vi.fn(),
    setActiveSavedFormName: vi.fn(),
    setShowSearchFill: vi.fn(),
    setSearchFillSessionId,
    setLoadError: vi.fn(),
    runOpenAiRename: vi.fn(),
    applySchemaMappings: vi.fn(),
    handleMappingSuccess: vi.fn(),
    schemaId: null,
    pdfDoc: null,
    sourceFileIsDemo: false,
    sourceFileName: null,
    demoStateRef: { current: { demoActive: false, demoCompletionOpen: false } },
    ...overrides,
  };
}

function renderHookHarness(deps: ReturnType<typeof createDeps>) {
  let latest: ReturnType<typeof useDetection> | null = null;

  function Harness() {
    latest = useDetection(deps as any);
    return null;
  }

  render(<Harness />);

  return {
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useDetection', () => {
  beforeEach(() => {
    detectFieldsMock.mockReset();
    pollDetectionStatusMock.mockReset();
    loadPdfFromFileMock.mockReset().mockResolvedValue(createPdfDoc());
    loadPageSizesMock.mockReset().mockResolvedValue({ 1: { width: 612, height: 792 } });
    extractFieldsFromPdfMock.mockReset().mockResolvedValue([]);
    touchSessionMock.mockReset();
    loadSavedFormMock.mockReset().mockResolvedValue({
      name: 'Saved Template',
      editorSnapshot: {
        pageCount: 1,
        pageSizes: { 1: { width: 612, height: 792 } },
        fields: [],
      },
    });
    downloadSavedFormMock.mockReset().mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does not immediately touch the same session twice when bootstrap assigns detect and mapping ids separately', async () => {
    const deps = createDeps({
      pdfDoc: createPdfDoc(),
    });
    const hook = renderHookHarness(deps);

    await act(async () => {
      hook.current.setDetectSessionId('session-1');
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(touchSessionMock).toHaveBeenCalledTimes(1);
      expect(touchSessionMock).toHaveBeenCalledWith('session-1');
    });

    await act(async () => {
      hook.current.setMappingSessionId('session-1');
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(touchSessionMock).toHaveBeenCalledTimes(1);
    });
  });

  it('keeps the processing view active when detection times out before any real fields are available', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);
    const pdfState = createPdfState();
    const backgroundPoll = deferred<any>();

    detectFieldsMock.mockResolvedValue({
      sessionId: 'slow-session-1',
      status: 'running',
      timedOut: true,
      fields: [],
    });
    pollDetectionStatusMock.mockReturnValue(backgroundPoll.promise);

    await act(async () => {
      await hook.current.runDetectUpload(
        new File(['pdf'], 'slow-detect.pdf', { type: 'application/pdf' }),
        {},
        pdfState,
      );
    });

    expect(hook.current.isProcessing).toBe(true);
    expect(hook.current.processingMode).toBe('detect');
    expect(hook.current.processingDetail).toContain('Opening the editor once fields are ready.');
    expect(pdfState.setPdfDoc).toHaveBeenCalledTimes(1);
    expect(deps.resetFieldHistory).toHaveBeenCalledWith([]);
    expect(pollDetectionStatusMock).toHaveBeenCalledWith(
      'slow-session-1',
      expect.objectContaining({
        signal: expect.any(AbortSignal),
      }),
    );
    expect(deps.setBannerNotice).not.toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Detection is still running on the backend. Using embedded form fields for now.',
      }),
    );

    backgroundPoll.resolve({ status: 'running' });
  });

  it('exits processing and applies fields once the background detection poll finishes', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);
    const pdfState = createPdfState();
    const backgroundPoll = deferred<any>();

    detectFieldsMock.mockResolvedValue({
      sessionId: 'slow-session-2',
      status: 'running',
      timedOut: true,
      fields: [],
    });
    pollDetectionStatusMock.mockReturnValue(backgroundPoll.promise);

    await act(async () => {
      await hook.current.runDetectUpload(
        new File(['pdf'], 'slow-detect.pdf', { type: 'application/pdf' }),
        {},
        pdfState,
      );
    });

    await act(async () => {
      backgroundPoll.resolve({
        sessionId: 'slow-session-2',
        status: 'complete',
        fields: [{
          name: 'Recovered Field',
          type: 'text',
          page: 1,
          rect: [10, 10, 120, 24],
        }],
      });
      await backgroundPoll.promise;
    });

    await waitFor(() => {
      expect(hook.current.isProcessing).toBe(false);
    });
    expect(deps.resetFieldHistory).toHaveBeenLastCalledWith([
      expect.objectContaining({ name: 'Recovered Field' }),
    ]);
    expect(deps.setBannerNotice).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Detection finished in the background (1 fields).',
      }),
    );
  });

  it('runs rename and then mapping for auto-rename plus auto-map uploads', async () => {
    const deps = createDeps({
      schemaId: 'schema-1',
      runOpenAiRename: vi.fn().mockResolvedValue([
        {
          id: 'field-1',
          name: 'Renamed Field',
          type: 'text',
          page: 1,
          rect: { x: 10, y: 10, width: 120, height: 24 },
          value: null,
        },
      ]),
      applySchemaMappings: vi.fn().mockResolvedValue(true),
    });
    const hook = renderHookHarness(deps);
    const pdfState = createPdfState();

    detectFieldsMock.mockResolvedValue({
      sessionId: 'session-rename-map',
      status: 'complete',
      fields: [{
        name: 'Original Field',
        type: 'text',
        page: 1,
        rect: [10, 10, 120, 24],
      }],
    });

    await act(async () => {
      await hook.current.runDetectUpload(
        new File(['pdf'], 'rename-map.pdf', { type: 'application/pdf' }),
        { autoRename: true, autoMap: true },
        pdfState,
      );
    });

    expect(deps.runOpenAiRename).toHaveBeenCalledWith({
      confirm: false,
      allowDefer: true,
      sessionId: 'session-rename-map',
      schemaId: 'schema-1',
    });
    expect(deps.applySchemaMappings).toHaveBeenCalledWith({
      fieldsOverride: [
        expect.objectContaining({ name: 'Renamed Field' }),
      ],
      schemaIdOverride: 'schema-1',
    });
    expect(deps.handleMappingSuccess).toHaveBeenCalledTimes(1);
  });

  it('shows a banner while auto-rename is still running after the editor opens', async () => {
    const renameDeferred = deferred<any>();
    const deps = createDeps({
      runOpenAiRename: vi.fn(() => renameDeferred.promise),
    });
    const hook = renderHookHarness(deps);
    const pdfState = createPdfState();

    detectFieldsMock.mockResolvedValue({
      sessionId: 'session-auto-rename',
      status: 'complete',
      fields: [{
        name: 'Original Field',
        type: 'text',
        page: 1,
        rect: [10, 10, 120, 24],
      }],
    });

    let uploadPromise: Promise<void> | null = null;
    await act(async () => {
      uploadPromise = hook.current.runDetectUpload(
        new File(['pdf'], 'auto-rename.pdf', { type: 'application/pdf' }),
        { autoRename: true },
        pdfState,
      );
      await Promise.resolve();
    });

    expect(pdfState.setPdfDoc).toHaveBeenCalledTimes(1);
    expect(deps.setBannerNotice).toHaveBeenCalledWith({
      tone: 'info',
      message: 'Fields are still renaming. You can review the editor while OpenAI finishes.',
      autoDismissMs: 8000,
    });

    renameDeferred.resolve([
      {
        id: 'field-1',
        name: 'Renamed Field',
        type: 'text',
        page: 1,
        rect: { x: 10, y: 10, width: 120, height: 24 },
        value: null,
      },
    ]);

    await act(async () => {
      await uploadPromise;
    });
  });

  it('marks the workspace as a saved form before the saved PDF finishes hydrating', async () => {
    const deps = createDeps();
    const hook = renderHookHarness(deps);
    const pdfState = createPdfState();
    const pendingPdfLoad = deferred<any>();

    loadPdfFromFileMock.mockReturnValueOnce(pendingPdfLoad.promise);

    let openPromise: Promise<boolean> | null = null;
    await act(async () => {
      openPromise = hook.current.handleSelectSavedForm('saved-form-1', pdfState);
      await Promise.resolve();
    });

    expect(deps.setActiveSavedFormId).toHaveBeenCalledWith('saved-form-1');
    expect(deps.setActiveSavedFormName).toHaveBeenCalledWith('Saved Template');
    expect(pdfState.setPdfDoc).not.toHaveBeenCalled();

    pendingPdfLoad.resolve(createPdfDoc());

    await act(async () => {
      await openPromise;
    });
  });
});
