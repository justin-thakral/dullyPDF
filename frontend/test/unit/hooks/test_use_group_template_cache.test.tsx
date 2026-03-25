import { act, render, waitFor } from '@testing-library/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PdfField } from '../../../src/types';
import { useGroupTemplateCache } from '../../../src/hooks/useGroupTemplateCache';

const loadSavedFormMock = vi.hoisted(() => vi.fn());
const downloadSavedFormMock = vi.hoisted(() => vi.fn());
const createSavedFormSessionMock = vi.hoisted(() => vi.fn());
const updateSavedFormEditorSnapshotMock = vi.hoisted(() => vi.fn());
const touchSessionMock = vi.hoisted(() => vi.fn());
const loadPdfFromFileMock = vi.hoisted(() => vi.fn());
const loadPageSizesMock = vi.hoisted(() => vi.fn());
const extractFieldsFromPdfMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    loadSavedForm: loadSavedFormMock,
    downloadSavedForm: downloadSavedFormMock,
    createSavedFormSession: createSavedFormSessionMock,
    updateSavedFormEditorSnapshot: updateSavedFormEditorSnapshotMock,
    touchSession: touchSessionMock,
  },
}));

vi.mock('../../../src/utils/pdf', () => ({
  loadPdfFromFile: loadPdfFromFileMock,
  loadPageSizes: loadPageSizesMock,
  extractFieldsFromPdf: extractFieldsFromPdfMock,
}));

type DisplayState = {
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  transformMode: boolean;
};

function createPdfDoc(numPages: number) {
  return {
    numPages,
    destroy: vi.fn().mockResolvedValue(undefined),
  };
}

function createField(id: string, name: string): PdfField {
  return {
    id,
    name,
    type: 'text',
    page: 1,
    rect: { x: 10, y: 10, width: 120, height: 20 },
    value: null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function renderHarness(
  initialDisplay: DisplayState,
  options?: { verifiedUser?: unknown },
) {
  const bannerNotice = vi.fn();
  const openSavedFormWithinGroup = vi.fn();
  const activePdfDoc = createPdfDoc(1);
  const activeSourceFile = new File(['alpha'], 'Alpha Packet.pdf', { type: 'application/pdf' });
  let latestHook: ReturnType<typeof useGroupTemplateCache> | null = null;
  let latestState:
    | (DisplayState & {
      activeSavedFormId: string | null;
      setDisplay: (next: DisplayState) => void;
      setFields: (nextFields: PdfField[]) => void;
    })
    | null = null;

  function Harness() {
    const [activeSavedFormId, setActiveSavedFormId] = useState<string | null>('tpl-a');
    const [activeSavedFormName, setActiveSavedFormName] = useState<string | null>('Alpha Packet');
    const [pdfDoc, setPdfDoc] = useState<any>(activePdfDoc);
    const [sourceFile, setSourceFile] = useState<File | null>(activeSourceFile);
    const [sourceFileName, setSourceFileName] = useState<string | null>('Alpha Packet.pdf');
    const [pageSizes, setPageSizes] = useState<Record<number, { width: number; height: number }>>({
      1: { width: 612, height: 792 },
    });
    const [pageCount, setPageCount] = useState(1);
    const [currentPage, setCurrentPage] = useState(1);
    const [scale, setScale] = useState(1);
    const [fields, setFields] = useState<PdfField[]>([createField('field-a', 'Alpha Field')]);
    const fieldsRef = useRef<PdfField[]>(fields);
    const historyRef = useRef<{ undo: PdfField[][]; redo: PdfField[][] }>({ undo: [], redo: [] });
    const [historyTick, setHistoryTick] = useState(0);
    const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
    const [showSearchFill, setShowSearchFill] = useState(false);
    const [searchFillPreset, setSearchFillPreset] = useState<any>(null);
    const [showFillLinkManager, setShowFillLinkManager] = useState(false);
    const [showFields, setShowFields] = useState(initialDisplay.showFields);
    const [showFieldNames, setShowFieldNames] = useState(initialDisplay.showFieldNames);
    const [showFieldInfo, setShowFieldInfo] = useState(initialDisplay.showFieldInfo);
    const [transformMode, setTransformMode] = useState(initialDisplay.transformMode);
    const [detectSessionId, setDetectSessionId] = useState<string | null>('session-a');
    const [mappingSessionId, setMappingSessionId] = useState<string | null>('session-a');
    const [hasRenamedFields, setHasRenamedFields] = useState(false);
    const [hasMappedSchema, setHasMappedSchema] = useState(false);
    const [checkboxRules, setCheckboxRules] = useState<any[]>([]);
    const [radioGroupSuggestions, setRadioGroupSuggestions] = useState<any[]>([]);
    const [textTransformRules, setTextTransformRules] = useState<any[]>([]);

    useEffect(() => {
      fieldsRef.current = fields;
    }, [fields]);

    const restoreState = useCallback((nextFields: PdfField[], history?: { undo?: PdfField[][]; redo?: PdfField[][] } | null) => {
      fieldsRef.current = nextFields;
      historyRef.current = {
        undo: history?.undo ?? [],
        redo: history?.redo ?? [],
      };
      setFields(nextFields);
      setHistoryTick((prev) => prev + 1);
    }, []);

    latestHook = useGroupTemplateCache({
      verifiedUser: options?.verifiedUser ?? null,
      group: {
        groups: [{
          id: 'group-1',
          name: 'Admissions',
          templateIds: ['tpl-a', 'tpl-b'],
          templateCount: 2,
          templates: [],
        }],
        groupsLoading: false,
        activeGroupId: 'group-1',
        activeGroupName: 'Admissions',
        activeGroupTemplateIds: ['tpl-a', 'tpl-b'],
        setActiveGroupId: vi.fn(),
        setActiveGroupName: vi.fn(),
        setActiveGroupTemplateIds: vi.fn(),
        groupRenameMapInProgress: false,
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
        openSavedFormWithinGroup,
      },
      document: {
        pdfDoc,
        sourceFile,
        sourceFileName,
        pageSizes,
        pageCount,
        currentPage,
        scale,
        setLoadError: vi.fn(),
        setShowHomepage: vi.fn(),
        setShowSearchFill,
        bumpSearchFillSession: vi.fn(),
        setSearchFillPreset,
        setShowFillLinkManager,
        setSourceFile,
        setSourceFileName,
        setSourceFileIsDemo: vi.fn(),
        setPdfDoc,
        setPageSizes,
        setPageCount,
        setCurrentPage,
        setScale,
        setPendingPageJump: vi.fn(),
      },
      fieldHistory: {
        fields,
        fieldsRef,
        historyRef,
        historyTick,
        restoreState,
      },
      fieldSelection: {
        selectedFieldId,
        setSelectedFieldId,
        handleFieldsChange: setFields,
      },
      detection: {
        detectSessionId,
        mappingSessionId,
        resetProcessing: vi.fn(),
        setDetectSessionId,
        setMappingSessionId,
      },
      openAi: {
        renameInProgress: false,
        mappingInProgress: false,
        mapSchemaInProgress: false,
        hasRenamedFields,
        hasMappedSchema,
        checkboxRules,
        radioGroupSuggestions,
        textTransformRules,
        setRenameInProgress: vi.fn(),
        setMappingInProgress: vi.fn(),
        setHasRenamedFields,
        setHasMappedSchema,
        setCheckboxRules,
        setRadioGroupSuggestions,
        setTextTransformRules,
        setOpenAiError: vi.fn(),
      },
      searchFill: {
        dataSourceKind: 'csv',
      },
      setBannerNotice: bannerNotice,
      markSavedFillLinkSnapshot: vi.fn(),
    });

    latestState = {
      activeSavedFormId,
      showFields,
      showFieldNames,
      showFieldInfo,
      transformMode,
      setFields,
      setDisplay: (next) => {
        setShowFields(next.showFields);
        setShowFieldNames(next.showFieldNames);
        setShowFieldInfo(next.showFieldInfo);
        setTransformMode(next.transformMode);
      },
    };

    void showSearchFill;
    void searchFillPreset;
    void showFillLinkManager;

    return null;
  }

  render(<Harness />);

  return {
    bannerNotice,
    openSavedFormWithinGroup,
    get hook() {
      if (!latestHook) {
        throw new Error('hook not initialized');
      }
      return latestHook;
    },
    get state() {
      if (!latestState) {
        throw new Error('state not initialized');
      }
      return latestState;
    },
  };
}

describe('useGroupTemplateCache', () => {
  beforeEach(() => {
    loadSavedFormMock.mockReset();
    downloadSavedFormMock.mockReset();
    createSavedFormSessionMock.mockReset();
    updateSavedFormEditorSnapshotMock.mockReset();
    touchSessionMock.mockReset();
    loadPdfFromFileMock.mockReset();
    loadPageSizesMock.mockReset();
    extractFieldsFromPdfMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('blocks switching to a template that is still preparing', async () => {
    const savedMetaDeferred = deferred<any>();
    const blobDeferred = deferred<Blob>();
    loadSavedFormMock.mockReturnValue(savedMetaDeferred.promise);
    downloadSavedFormMock.mockReturnValue(blobDeferred.promise);

    const harness = renderHarness({
      showFields: true,
      showFieldNames: true,
      showFieldInfo: false,
      transformMode: false,
    });

    void harness.hook.ensureGroupTemplateSnapshot('tpl-b', 'Bravo Intake');

    await waitFor(() => expect(loadSavedFormMock).toHaveBeenCalledWith(
      'tpl-b',
      expect.objectContaining({ timeoutMs: 15000 }),
    ));

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-b');
    });

    expect(harness.bannerNotice).toHaveBeenCalledWith(expect.objectContaining({
      tone: 'info',
      message: 'Wait for this group template to finish preparing before opening it.',
    }));
    expect(harness.state.activeSavedFormId).toBe('tpl-a');
  });

  it('keeps the current display mode when switching cached group templates', async () => {
    loadSavedFormMock.mockResolvedValue({ name: 'Bravo Intake' });
    downloadSavedFormMock.mockResolvedValue(new Blob(['pdf']));
    loadPdfFromFileMock.mockResolvedValue(createPdfDoc(2));
    loadPageSizesMock.mockResolvedValue({
      1: { width: 612, height: 792 },
      2: { width: 612, height: 792 },
    });
    extractFieldsFromPdfMock.mockResolvedValue([createField('field-b', 'Bravo Field')]);

    const harness = renderHarness({
      showFields: true,
      showFieldNames: false,
      showFieldInfo: true,
      transformMode: false,
    });

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-b');
    });

    expect(harness.state.activeSavedFormId).toBe('tpl-b');
    expect(harness.state.showFieldInfo).toBe(true);
    expect(harness.state.transformMode).toBe(false);

    act(() => {
      harness.state.setDisplay({
        showFields: true,
        showFieldNames: false,
        showFieldInfo: false,
        transformMode: true,
      });
    });

    await waitFor(() => expect(harness.state.transformMode).toBe(true));

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-a');
    });

    expect(harness.state.activeSavedFormId).toBe('tpl-a');
    expect(harness.state.showFields).toBe(true);
    expect(harness.state.showFieldNames).toBe(false);
    expect(harness.state.showFieldInfo).toBe(false);
    expect(harness.state.transformMode).toBe(true);

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-b');
    });

    expect(harness.state.activeSavedFormId).toBe('tpl-b');
    expect(harness.state.showFields).toBe(true);
    expect(harness.state.showFieldNames).toBe(false);
    expect(harness.state.showFieldInfo).toBe(false);
    expect(harness.state.transformMode).toBe(true);
  });

  it('loads group templates without blocking on saved-form session warmup', async () => {
    loadSavedFormMock.mockResolvedValue({ name: 'Bravo Intake' });
    downloadSavedFormMock.mockResolvedValue(new Blob(['pdf']));
    loadPdfFromFileMock.mockResolvedValue(createPdfDoc(2));
    loadPageSizesMock.mockResolvedValue({
      1: { width: 612, height: 792 },
      2: { width: 612, height: 792 },
    });
    extractFieldsFromPdfMock.mockResolvedValue([createField('field-b', 'Bravo Field')]);

    const harness = renderHarness({
      showFields: true,
      showFieldNames: true,
      showFieldInfo: false,
      transformMode: false,
    }, {
      verifiedUser: { uid: 'user-1' },
    });

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-b');
    });

    await waitFor(() => expect(harness.state.activeSavedFormId).toBe('tpl-b'));
    expect(createSavedFormSessionMock).not.toHaveBeenCalled();
    expect(updateSavedFormEditorSnapshotMock).toHaveBeenCalledWith(
      'tpl-b',
      expect.objectContaining({
        version: 2,
        pageCount: 2,
        radioGroups: [],
        fields: [expect.objectContaining({ id: 'field-b', name: 'Bravo Field' })],
      }),
    );
  });

  it('uses the saved-form editor snapshot instead of re-extracting group template fields', async () => {
    loadSavedFormMock.mockResolvedValue({
      name: 'Bravo Intake',
      editorSnapshot: {
        version: 1,
        pageCount: 2,
        pageSizes: {
          1: { width: 612, height: 792 },
          2: { width: 612, height: 792 },
        },
        fields: [createField('field-b', 'Bravo Field')],
        hasRenamedFields: true,
        hasMappedSchema: true,
      },
    });
    downloadSavedFormMock.mockResolvedValue(new Blob(['pdf']));
    loadPdfFromFileMock.mockResolvedValue(createPdfDoc(2));

    const harness = renderHarness({
      showFields: true,
      showFieldNames: true,
      showFieldInfo: false,
      transformMode: false,
    }, {
      verifiedUser: { uid: 'user-1' },
    });

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-b');
    });

    expect(harness.state.activeSavedFormId).toBe('tpl-b');
    expect(loadPageSizesMock).not.toHaveBeenCalled();
    expect(extractFieldsFromPdfMock).not.toHaveBeenCalled();
    expect(updateSavedFormEditorSnapshotMock).not.toHaveBeenCalled();
  });

  it('tracks dirty cached group templates until they are marked persisted', async () => {
    const harness = renderHarness({
      showFields: true,
      showFieldNames: true,
      showFieldInfo: false,
      transformMode: false,
    });

    expect(harness.hook.resolveGroupTemplateDirtyNames()).toEqual([]);

    act(() => {
      harness.state.setFields([createField('field-a', 'Edited Alpha Field')]);
    });

    await waitFor(() =>
      expect(harness.hook.resolveGroupTemplateDirtyNames()).toEqual(['Alpha Packet']),
    );

    act(() => {
      harness.hook.markGroupTemplatesPersisted(['tpl-a']);
    });

    expect(harness.hook.resolveGroupTemplateDirtyNames()).toEqual([]);
  });

  it('resolves dirty group templates for a targeted subset of form ids', async () => {
    loadSavedFormMock.mockResolvedValue({ name: 'Bravo Intake' });
    downloadSavedFormMock.mockResolvedValue(new Blob(['pdf']));
    loadPdfFromFileMock.mockResolvedValue(createPdfDoc(2));
    loadPageSizesMock.mockResolvedValue({
      1: { width: 612, height: 792 },
      2: { width: 612, height: 792 },
    });
    extractFieldsFromPdfMock.mockResolvedValue([createField('field-b', 'Bravo Field')]);

    const harness = renderHarness({
      showFields: true,
      showFieldNames: true,
      showFieldInfo: false,
      transformMode: false,
    });

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-b');
    });

    act(() => {
      harness.state.setFields([createField('field-b', 'Edited Bravo Field')]);
    });

    await waitFor(() =>
      expect(harness.hook.resolveDirtyGroupTemplateRecords(['tpl-b'])).toEqual([
        { formId: 'tpl-b', templateName: 'Bravo Intake' },
      ]),
    );

    await act(async () => {
      await harness.hook.handleSelectActiveGroupTemplate('tpl-a');
    });

    expect(harness.hook.resolveDirtyGroupTemplateRecords(['tpl-b'])).toEqual([
      { formId: 'tpl-b', templateName: 'Bravo Intake' },
    ]);
    expect(harness.hook.resolveDirtyGroupTemplateRecords(['tpl-a'])).toEqual([]);
  });
});
