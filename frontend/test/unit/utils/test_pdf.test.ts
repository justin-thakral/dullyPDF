import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getDocumentMock, globalWorkerOptions } = vi.hoisted(() => ({
  getDocumentMock: vi.fn(),
  globalWorkerOptions: { workerSrc: '' },
}));

vi.mock('pdfjs-dist', () => ({
  getDocument: getDocumentMock,
  GlobalWorkerOptions: globalWorkerOptions,
}));

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({
  default: '/mocked/pdf.worker.min.mjs',
}));

import {
  extractFieldsFromPdf,
  loadPageSizes,
  loadPdfFromFile,
  loadPdfPageCountFromFile,
} from '../../../src/utils/pdf';

type MockAnnotation = Record<string, unknown>;
type MockFieldObject = Record<string, unknown>;

function createMockPage({
  width = 400,
  height = 300,
  annotations = [],
  convertRect = (rect: number[]) => rect,
}: {
  width?: number;
  height?: number;
  annotations?: MockAnnotation[];
  convertRect?: (rect: number[]) => number[];
}) {
  const viewport = {
    width,
    height,
    convertToViewportRectangle: vi.fn(convertRect),
  };

  return {
    getViewport: vi.fn(() => viewport),
    getAnnotations: vi.fn(async () => annotations),
  };
}

function createMockDoc({
  pages,
  fieldObjects = null,
}: {
  pages: ReturnType<typeof createMockPage>[];
  fieldObjects?: Record<string, MockFieldObject[]> | null;
}) {
  return {
    numPages: pages.length,
    getPage: vi.fn(async (pageNum: number) => pages[pageNum - 1]),
    getFieldObjects: vi.fn(async () => fieldObjects),
  };
}

describe('pdf utils', () => {
  beforeEach(() => {
    getDocumentMock.mockReset();
  });

  it('sets the PDF.js worker source during module initialization', () => {
    expect(globalWorkerOptions.workerSrc).toBe('/mocked/pdf.worker.min.mjs');
  });

  it('loads a PDF via PDF.js getDocument and returns the resolved document', async () => {
    const mockDoc = { numPages: 2 };
    getDocumentMock.mockReturnValue({ promise: Promise.resolve(mockDoc) });
    const sourceBytes = Uint8Array.from([1, 2, 3]);
    const file = {
      name: 'form.pdf',
      arrayBuffer: vi.fn(async () => sourceBytes.buffer),
    } as unknown as File;

    const doc = await loadPdfFromFile(file);

    expect(doc).toBe(mockDoc);
    expect(file.arrayBuffer).toHaveBeenCalledTimes(1);
    expect(getDocumentMock).toHaveBeenCalledTimes(1);
    const options = getDocumentMock.mock.calls[0][0] as {
      data: ArrayBuffer;
      enableXfa: boolean;
      useSystemFonts: boolean;
    };
    expect(options.enableXfa).toBe(true);
    expect(options.useSystemFonts).toBe(true);
    expect(Array.from(new Uint8Array(options.data))).toEqual([1, 2, 3]);
  });

  it('loads page counts with lighter PDF.js options and destroys the document after counting', async () => {
    const destroyMock = vi.fn().mockResolvedValue(undefined);
    const mockDoc = { numPages: 6, destroy: destroyMock };
    getDocumentMock.mockReturnValue({ promise: Promise.resolve(mockDoc), destroy: vi.fn() });
    const sourceBytes = Uint8Array.from([9, 8, 7]);
    const file = {
      name: 'packet.pdf',
      arrayBuffer: vi.fn(async () => sourceBytes.buffer),
    } as unknown as File;

    const pageCount = await loadPdfPageCountFromFile(file);

    expect(pageCount).toBe(6);
    expect(getDocumentMock).toHaveBeenCalledTimes(1);
    const options = getDocumentMock.mock.calls[0][0] as {
      data: ArrayBuffer;
      enableXfa: boolean;
      useSystemFonts: boolean;
      disableFontFace: boolean;
      stopAtErrors: boolean;
    };
    expect(options.enableXfa).toBe(false);
    expect(options.useSystemFonts).toBe(false);
    expect(options.disableFontFace).toBe(true);
    expect(options.stopAtErrors).toBe(true);
    expect(Array.from(new Uint8Array(options.data))).toEqual([9, 8, 7]);
    expect(destroyMock).toHaveBeenCalledTimes(1);
  });

  it('times out stalled page counts and destroys the loading task', async () => {
    vi.useFakeTimers();
    try {
      const destroyTaskMock = vi.fn();
      getDocumentMock.mockReturnValue({
        promise: new Promise(() => {}),
        destroy: destroyTaskMock,
      });
      const file = {
        name: 'stalled.pdf',
        arrayBuffer: vi.fn(async () => Uint8Array.from([1]).buffer),
      } as unknown as File;

      const pending = loadPdfPageCountFromFile(file, { timeoutMs: 25 });
      const rejection = expect(pending).rejects.toThrow(
        'Page counting timed out. Remove this PDF and try again.',
      );
      await vi.advanceTimersByTimeAsync(25);

      await rejection;
      expect(destroyTaskMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('extracts page sizes for every page in the document', async () => {
    const pageOne = { getViewport: vi.fn(() => ({ width: 612, height: 792 })) };
    const pageTwo = { getViewport: vi.fn(() => ({ width: 500, height: 700 })) };
    const doc = {
      numPages: 2,
      getPage: vi.fn(async (pageNum: number) => (pageNum === 1 ? pageOne : pageTwo)),
    };

    const sizes = await loadPageSizes(doc as any);

    expect(sizes).toEqual({
      1: { width: 612, height: 792 },
      2: { width: 500, height: 700 },
    });
    expect(doc.getPage).toHaveBeenNthCalledWith(1, 1);
    expect(doc.getPage).toHaveBeenNthCalledWith(2, 2);
  });

  it('maps widget annotations into fields with type, rect, value coercion, and unique names', async () => {
    const page = createMockPage({
      width: 200,
      height: 100,
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Btn',
          checkBox: true,
          fieldName: 'consent',
          fieldValue: ['yes', 'signed'],
          rect: [20, 10, 40, 26],
        },
        {
          subtype: 'Widget',
          fieldType: 'Sig',
          fieldName: 'consent',
          fieldValue: { by: 'Jane' },
          rect: [50, 10, 110, 30],
        },
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          fieldName: 'notes',
          defaultFieldValue: true,
          rect: [140, 20, 190, 40],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(3);
    expect(fields[0]).toMatchObject({
      name: 'consent',
      type: 'checkbox',
      page: 1,
      rect: { x: 20, y: 10, width: 20, height: 16 },
      value: 'yes, signed',
    });
    expect(fields[1]).toMatchObject({
      name: 'consent_1',
      type: 'signature',
      rect: { x: 50, y: 10, width: 60, height: 20 },
      value: '[object Object]',
    });
    expect(fields[2]).toMatchObject({
      name: 'notes',
      type: 'text',
      rect: { x: 140, y: 20, width: 50, height: 20 },
      value: true,
    });
  });

  it('extracts confidence tags and ignores confidence-only alternative text for names', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          alternativeText: 'dullypdf:confidence=0.33',
          title: 'Fallback Label',
          rect: [5, 5, 65, 25],
        },
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          alternativeText: 'Friendly Label',
          title: 'dullypdf:confidence=72',
          rect: [75, 5, 160, 25],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(2);
    expect(fields[0]).toMatchObject({
      name: 'Fallback Label',
      fieldConfidence: 0.33,
    });
    expect(fields[1]).toMatchObject({
      name: 'Friendly Label',
      fieldConfidence: 0.72,
    });
  });

  it('ignores confidence-only title text when deriving field names', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          title: 'dullypdf:confidence=0.44',
          rect: [5, 5, 65, 25],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(1);
    expect(fields[0]).toMatchObject({
      name: 'field_1_1',
      fieldConfidence: 0.44,
    });
  });

  it('parses confidence from generic confidence labels without dullypdf tag prefix', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          fieldName: 'member_phone',
          title: 'confidence: 72',
          rect: [5, 5, 65, 25],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(1);
    expect(fields[0]).toMatchObject({
      name: 'member_phone',
      fieldConfidence: 0.72,
    });
  });

  it('parses dullypdf confidence tags when trailing metadata is separated by spaces', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          fieldName: 'member_dob',
          title: 'dullypdf:confidence=0.64 source=commonforms',
          rect: [8, 8, 90, 28],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(1);
    expect(fields[0]).toMatchObject({
      name: 'member_dob',
      fieldConfidence: 0.64,
    });
  });

  it('ignores generic confidence-only alternative text when choosing field names', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          alternativeText: 'confidence: 72',
          title: 'Member Phone',
          rect: [8, 8, 90, 28],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(1);
    expect(fields[0]).toMatchObject({
      name: 'Member Phone',
      fieldConfidence: 0.72,
    });
  });

  it('parses dullypdf confidence tags when there is whitespace after the equals sign', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          fieldName: 'member_state',
          title: 'dullypdf:confidence= 0.81;source=commonforms',
          rect: [8, 8, 90, 28],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(1);
    expect(fields[0]).toMatchObject({
      name: 'member_state',
      fieldConfidence: 0.81,
    });
  });

  it('does not coerce an empty dullypdf confidence tag to zero', async () => {
    const page = createMockPage({
      annotations: [
        {
          subtype: 'Widget',
          fieldType: 'Tx',
          fieldName: 'member_city',
          title: 'dullypdf:confidence=',
          rect: [8, 8, 90, 28],
        },
      ],
    });
    const doc = createMockDoc({ pages: [page] });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(fields).toHaveLength(1);
    expect(fields[0]).toMatchObject({
      name: 'member_city',
    });
    expect(fields[0]).not.toHaveProperty('fieldConfidence');
  });

  it('falls back to getFieldObjects when no widgets exist and keeps fallback names unique', async () => {
    const pageOne = createMockPage({ annotations: [] });
    const pageTwo = createMockPage({ annotations: [] });
    const fieldObjects = {
      section_a: [
        {
          name: 'member_id',
          page: 0,
          rect: [10, 10, 110, 30],
          type: 'text',
          value: 12345,
        },
        {
          name: 'member_id',
          page: 0,
          rect: [20, 40, 120, 60],
          type: 'text',
          defaultValue: 'A-1',
        },
      ],
      section_b: [
        {
          name: 'has_consent',
          page: 1,
          rect: [15, 15, 35, 35],
          type: 'checkbox',
          value: true,
        },
        {
          name: '',
          page: 99,
          rect: [40, 40, 42, 42],
          type: 'signature',
          value: null,
        },
      ],
    };

    const doc = createMockDoc({ pages: [pageOne, pageTwo], fieldObjects });

    const fields = await extractFieldsFromPdf(doc as any);

    expect(doc.getFieldObjects).toHaveBeenCalledTimes(1);
    expect(fields).toHaveLength(4);
    expect(fields[0]).toMatchObject({
      name: 'member_id',
      type: 'text',
      page: 1,
      value: 12345,
    });
    expect(fields[1]).toMatchObject({
      name: 'member_id_1',
      type: 'text',
      page: 1,
      value: 'A-1',
    });
    expect(fields[2]).toMatchObject({
      name: 'has_consent',
      type: 'checkbox',
      page: 2,
      value: true,
    });
    expect(fields[3]).toMatchObject({
      name: 'field_2_4',
      type: 'signature',
      page: 2,
    });
    expect(fields[3]).not.toHaveProperty('value');
  });
});
