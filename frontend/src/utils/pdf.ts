import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import type { FieldRect, FieldType, PageSize, PdfField } from '../types';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { clampRectToPage } from './coords';
import { parseConfidence } from './confidence';
import { ensureUniqueFieldName, makeId } from './fields';

const DEBUG_PDF = false;

function debugLog(...args: unknown[]) {
  if (!DEBUG_PDF) return;
  console.log('[dullypdf-ui/pdf]', ...args);
}

// Ensure the PDF.js worker runs in a separate thread for heavy parsing work.
GlobalWorkerOptions.workerSrc = workerSrc;

type PdfJsAnnotation = {
  subtype?: string;
  annotationType?: number;
  fieldType?: string;
  fieldName?: string;
  alternativeText?: string;
  title?: string;
  fieldValue?: unknown;
  defaultFieldValue?: unknown;
  rect?: number[];
  checkBox?: boolean;
  radioButton?: boolean;
  pushButton?: boolean;
};

const CONFIDENCE_TAG_PREFIX = 'dullypdf:confidence=';

function parseConfidenceTag(raw?: string): number | undefined {
  if (!raw) return undefined;
  const lower = raw.toLowerCase();
  const idx = lower.indexOf(CONFIDENCE_TAG_PREFIX);
  if (idx !== -1) {
    const value = raw.slice(idx + CONFIDENCE_TAG_PREFIX.length).split(/[;\\s]/)[0];
    return parseConfidence(value);
  }
  const match = raw.match(/confidence\\s*[:=]\\s*([0-9.]+)/i);
  if (match) return parseConfidence(match[1]);
  return undefined;
}

function isConfidenceTag(raw?: string): boolean {
  if (!raw) return false;
  return raw.toLowerCase().includes(CONFIDENCE_TAG_PREFIX);
}

function extractFieldConfidence(annotation: PdfJsAnnotation): number | undefined {
  return (
    parseConfidenceTag(annotation.alternativeText) ??
    parseConfidenceTag(annotation.title)
  );
}

export async function loadPdfFromFile(file: File): Promise<PDFDocumentProxy> {
  const buffer = await file.arrayBuffer();
  const options = {
    data: buffer,
    enableXfa: true,
    useSystemFonts: true,
  };

  try {
    const task = getDocument(options);
    const doc = await task.promise;
    debugLog('Loaded PDF', { name: file.name, pages: doc.numPages });
    return doc;
  } catch (error) {
    debugLog('Failed to load PDF', error);
    throw error;
  }
}

export async function loadPageSizes(doc: PDFDocumentProxy): Promise<Record<number, PageSize>> {
  // Cache page sizes by page number so the UI can clamp fields without reloading pages.
  const sizes: Record<number, PageSize> = {};
  for (let pageNum = 1; pageNum <= doc.numPages; pageNum += 1) {
    const page = await doc.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1 });
    sizes[pageNum] = { width: viewport.width, height: viewport.height };
  }
  debugLog('Loaded page sizes', sizes);
  return sizes;
}

function mapAnnotationType(annotation: PdfJsAnnotation): FieldType {
  // Convert PDF widget field types into the simplified UI field categories.
  if (annotation.fieldType === 'Sig') {
    return 'signature';
  }
  if (annotation.fieldType === 'Btn') {
    if (annotation.checkBox || annotation.radioButton) {
      return 'checkbox';
    }
    return 'text';
  }
  if (annotation.fieldType === 'Tx') {
    return 'text';
  }
  if (annotation.fieldType === 'Ch') {
    return 'text';
  }
  return 'text';
}

function buildRectFromAnnotation(
  annotationRect: number[],
  pageSize: PageSize,
  viewport: { convertToViewportRectangle: (rect: number[]) => number[] },
): FieldRect | null {
  if (!annotationRect || annotationRect.length < 4) return null;
  // PDF rectangles use a bottom-left origin. Convert to top-left viewport coordinates.
  const [x1, y1, x2, y2] = viewport.convertToViewportRectangle(annotationRect);
  const x = Math.min(x1, x2);
  const y = Math.min(y1, y2);
  const width = Math.abs(x2 - x1);
  const height = Math.abs(y2 - y1);
  if (width < 1 || height < 1) return null;
  return clampRectToPage({ x, y, width, height }, pageSize, 2);
}

export async function extractFieldsFromPdf(doc: PDFDocumentProxy): Promise<PdfField[]> {
  const fields: PdfField[] = [];
  const existingNames = new Set<string>();

  for (let pageNum = 1; pageNum <= doc.numPages; pageNum += 1) {
    const page = await doc.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1 });
    const pageSize = { width: viewport.width, height: viewport.height };
    const annotations = (await page.getAnnotations({ intent: 'display' })) as PdfJsAnnotation[];
    let widgetCount = 0;
    let fieldIndex = 1;

    for (const annotation of annotations) {
      // Widget annotations are the PDF fields we want to edit in the overlay.
      const isWidget =
        annotation.subtype === 'Widget' || annotation.annotationType === 20 || !!annotation.fieldType;
      if (!isWidget) continue;
      widgetCount += 1;
      const rect = buildRectFromAnnotation(annotation.rect || [], pageSize, viewport);
      if (!rect) continue;

      const altText = annotation.alternativeText?.trim();
      const safeAltText = altText && !isConfidenceTag(altText) ? altText : '';
      const rawName = (annotation.fieldName || safeAltText || annotation.title || '').trim();
      const baseName = rawName || `field_${pageNum}_${fieldIndex}`;
      const name = ensureUniqueFieldName(baseName, existingNames);
      const type = mapAnnotationType(annotation);
      const fieldConfidence = extractFieldConfidence(annotation);
      const rawValue = annotation.fieldValue ?? annotation.defaultFieldValue;
      let value: PdfField['value'] | undefined;
      if (rawValue !== undefined && rawValue !== null) {
        if (Array.isArray(rawValue)) {
          value = rawValue.join(', ');
        } else if (
          typeof rawValue === 'string' ||
          typeof rawValue === 'number' ||
          typeof rawValue === 'boolean'
        ) {
          value = rawValue;
        } else {
          value = String(rawValue);
        }
      }
      const hasValue =
        value !== undefined && (typeof value !== 'string' || value.trim() !== '');

      fields.push({
        id: makeId(),
        name,
        type,
        page: pageNum,
        rect,
        ...(fieldConfidence !== undefined ? { fieldConfidence } : {}),
        ...(hasValue ? { value } : {}),
      });

      if (DEBUG_PDF && fieldIndex <= 6) {
        debugLog('Widget', {
          page: pageNum,
          fieldType: annotation.fieldType,
          subtype: annotation.subtype,
          annotationType: annotation.annotationType,
          fieldName: annotation.fieldName,
          rect,
        });
      }

      fieldIndex += 1;
    }

    debugLog('Page annotations', {
      page: pageNum,
      total: annotations.length,
      widgets: widgetCount,
    });
  }

  debugLog('Extracted fields', { total: fields.length });
  return fields;
}
