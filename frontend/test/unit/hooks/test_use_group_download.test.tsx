import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useGroupDownload } from '../../../src/hooks/useGroupDownload';

const materializeFormPdfMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    materializeFormPdf: materializeFormPdfMock,
  },
}));

function createSnapshot(formId: string, templateName: string, sourceFile: File) {
  return {
    formId,
    templateName,
    sourceFile,
    sourceFileName: `${templateName}.pdf`,
    pdfDoc: { destroy: vi.fn().mockResolvedValue(undefined) } as any,
    pageSizes: { 1: { width: 612, height: 792 } },
    pageCount: 1,
    currentPage: 1,
    scale: 1,
    fields: [
      {
        id: `${formId}-field`,
        name: `${templateName}_field`,
        type: 'text',
        page: 1,
        rect: { x: 10, y: 10, width: 120, height: 20 },
        value: templateName,
      },
    ],
    history: { undo: [], redo: [] },
    selectedFieldId: null,
    detectSessionId: null,
    mappingSessionId: null,
    hasRenamedFields: false,
    hasMappedSchema: false,
    checkboxRules: [],
    radioGroupSuggestions: [],
    textTransformRules: [],
    display: {
      showFields: true,
      showFieldNames: true,
      showFieldInfo: false,
      transformMode: false,
    },
  };
}

describe('useGroupDownload', () => {
  beforeEach(() => {
    materializeFormPdfMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('downloads the current group as a zip archive of materialized PDFs', async () => {
    const setLoadError = vi.fn();
    const setBannerNotice = vi.fn();
    const ensureGroupTemplateSnapshot = vi.fn();
    const activeFile = new File(['alpha'], 'Alpha Packet.pdf', { type: 'application/pdf' });
    const cachedFile = new File(['bravo'], 'Bravo Intake.pdf', { type: 'application/pdf' });
    const activeSnapshot = createSnapshot('tpl-a', 'Alpha Packet', activeFile);
    const cachedSnapshot = createSnapshot('tpl-b', 'Bravo Intake', cachedFile);
    ensureGroupTemplateSnapshot.mockResolvedValue(cachedSnapshot);
    const createBlobLike = (value: string) => ({
      arrayBuffer: vi.fn().mockResolvedValue(new TextEncoder().encode(value).buffer),
    });
    materializeFormPdfMock
      .mockResolvedValueOnce(createBlobLike('alpha-pdf'))
      .mockResolvedValueOnce(createBlobLike('bravo-pdf'));

    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:group-download');
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    let latest: ReturnType<typeof useGroupDownload> | null = null;
    function Harness() {
      latest = useGroupDownload({
        verifiedUser: { uid: 'user-1' },
        activeGroupId: 'group-1',
        activeGroupName: 'Admissions',
        activeGroupTemplates: [
          { id: 'tpl-a', name: 'Alpha Packet' },
          { id: 'tpl-b', name: 'Bravo Intake' },
        ],
        activeSavedFormId: 'tpl-a',
        captureActiveGroupTemplateSnapshot: () => activeSnapshot as any,
        ensureGroupTemplateSnapshot,
        setLoadError,
        setBannerNotice,
      });
      return null;
    }

    render(<Harness />);

    if (!latest) {
      throw new Error('hook not initialized');
    }

    await act(async () => {
      await latest?.handleDownloadGroup();
    });

    expect(setLoadError.mock.calls).toEqual([[null]]);
    expect(materializeFormPdfMock).toHaveBeenNthCalledWith(1, activeFile, expect.any(Array));
    expect(materializeFormPdfMock).toHaveBeenNthCalledWith(2, cachedFile, expect.any(Array));
    expect(ensureGroupTemplateSnapshot).toHaveBeenCalledWith('tpl-b', 'Bravo Intake');
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrlSpy).not.toHaveBeenCalled();
    expect(setLoadError).toHaveBeenCalledWith(null);
    expect(setBannerNotice).not.toHaveBeenCalled();
    expect(createObjectUrlSpy).toHaveBeenCalledWith(expect.objectContaining({ type: 'application/zip' }));
  });
});
