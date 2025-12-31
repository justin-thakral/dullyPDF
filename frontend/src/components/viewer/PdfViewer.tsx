import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist/types/src/display/api';
import type { PageSize, PdfField } from '../../types';
import { FieldOverlay } from './FieldOverlay';
import { FieldInputOverlay } from './FieldInputOverlay';

const EMPTY_SIZE: PageSize = { width: 0, height: 0 };
const RENDER_RADIUS = 2;

type PdfViewerProps = {
  pdfDoc: PDFDocumentProxy | null;
  pageNumber: number;
  scale: number;
  pageSizes: Record<number, PageSize>;
  fields: PdfField[];
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  selectedFieldId: string | null;
  onSelectField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  onPageChange: (page: number) => void;
  pendingPageJump: number | null;
  onPageJumpComplete: () => void;
};

type PdfPageProps = {
  pdfDoc: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  pageSize: PageSize;
  fields: PdfField[];
  showFields: boolean;
  showFieldNames: boolean;
  showFieldInfo: boolean;
  selectedFieldId: string | null;
  onSelectField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: Partial<PdfField>) => void;
  registerRef: (node: HTMLDivElement | null) => void;
  isActive: boolean;
};

function PdfPage({
  pdfDoc,
  pageNumber,
  scale,
  pageSize,
  fields,
  showFields,
  showFieldNames,
  showFieldInfo,
  selectedFieldId,
  onSelectField,
  onUpdateField,
  registerRef,
  isActive,
}: PdfPageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isRendering, setIsRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let renderTask: RenderTask | null = null;

    const renderPage = async () => {
      if (!pdfDoc || !canvasRef.current) return;
      setIsRendering(true);
      setRenderError(null);

      try {
        const page = await pdfDoc.getPage(pageNumber);
        if (cancelled || !canvasRef.current) return;

        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const context = canvas.getContext('2d');

        if (!context) {
          throw new Error('Unable to get canvas context.');
        }

        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        renderTask = page.render({ canvasContext: context, viewport });
        await renderTask.promise;
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : 'Failed to render PDF page.';
          setRenderError(message);
        }
      } finally {
        if (!cancelled) {
          setIsRendering(false);
        }
      }
    };

    if (!isActive) {
      setIsRendering(false);
      setRenderError(null);
      return () => undefined;
    }

    renderPage();

    return () => {
      cancelled = true;
      if (renderTask) {
        renderTask.cancel();
      }
    };
  }, [pdfDoc, pageNumber, scale, isActive]);

  return (
    <div
      className="viewer__page"
      data-page-number={pageNumber}
      ref={registerRef}
      style={{
        width: pageSize.width * scale,
        height: pageSize.height * scale,
      }}
    >
      {isActive ? (
        <>
          <canvas ref={canvasRef} className="viewer__canvas" />
          {showFields ? (
            <FieldOverlay
              fields={fields}
              pageSize={pageSize}
              scale={scale}
              showFieldNames={showFieldNames}
              selectedFieldId={selectedFieldId}
              onSelectField={onSelectField}
              onUpdateField={onUpdateField}
            />
          ) : null}
          {showFieldInfo ? (
            <FieldInputOverlay
              fields={fields}
              pageSize={pageSize}
              scale={scale}
              selectedFieldId={selectedFieldId}
              onSelectField={onSelectField}
              onUpdateField={onUpdateField}
            />
          ) : null}
          {isRendering ? <div className="viewer__status">Rendering page...</div> : null}
          {renderError ? <div className="viewer__error">{renderError}</div> : null}
        </>
      ) : (
        <div className="viewer__page-placeholder">
          <span>Page {pageNumber}</span>
        </div>
      )}
    </div>
  );
}

export function PdfViewer({
  pdfDoc,
  pageNumber,
  scale,
  pageSizes,
  fields,
  showFields,
  showFieldNames,
  showFieldInfo,
  selectedFieldId,
  onSelectField,
  onUpdateField,
  onPageChange,
  pendingPageJump,
  onPageJumpComplete,
}: PdfViewerProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pageRefs = useRef(new Map<number, HTMLDivElement | null>());
  const activePageRef = useRef(pageNumber);
  const scrollLockRef = useRef(false);
  const scaleRef = useRef(1);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

  const pages = useMemo(() => {
    if (!pdfDoc) return [] as number[];
    return Array.from({ length: pdfDoc.numPages }, (_, idx) => idx + 1);
  }, [pdfDoc]);

  const activePages = useMemo(() => {
    if (!pages.length) return new Set<number>();
    const anchor = pendingPageJump || pageNumber;
    const start = Math.max(1, anchor - RENDER_RADIUS);
    const end = Math.min(pages.length, anchor + RENDER_RADIUS);
    const active = new Set<number>();
    for (let page = start; page <= end; page += 1) {
      active.add(page);
    }
    return active;
  }, [pages, pageNumber, pendingPageJump]);

  const maxPageSize = useMemo(() => {
    let maxWidth = 0;
    let maxHeight = 0;
    Object.values(pageSizes).forEach((size) => {
      if (size.width > maxWidth) maxWidth = size.width;
      if (size.height > maxHeight) maxHeight = size.height;
    });
    return { width: maxWidth, height: maxHeight };
  }, [pageSizes]);

  const fitScale = useMemo(() => {
    if (!maxPageSize.width || !maxPageSize.height) return 1;
    if (!containerSize.width || !containerSize.height) return 1;
    const widthScale = containerSize.width / maxPageSize.width;
    const heightScale = containerSize.height / maxPageSize.height;
    return Math.min(widthScale, heightScale);
  }, [containerSize, maxPageSize]);

  const effectiveScale = fitScale * scale;

  const fieldsByPage = useMemo(() => {
    const map = new Map<number, PdfField[]>();
    fields.forEach((field) => {
      if (!map.has(field.page)) {
        map.set(field.page, []);
      }
      map.get(field.page)?.push(field);
    });
    return map;
  }, [fields]);

  const registerPageRef = useCallback(
    (page: number) => (node: HTMLDivElement | null) => {
      pageRefs.current.set(page, node);
    },
    [],
  );

  useEffect(() => {
    activePageRef.current = pageNumber;
  }, [pageNumber]);

  useEffect(() => {
    if (!scrollRef.current) return;
    if (!pendingPageJump) return;
    const target = pageRefs.current.get(pendingPageJump);
    if (!target) return;

    scrollLockRef.current = true;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const timeout = window.setTimeout(() => {
      scrollLockRef.current = false;
      onPageJumpComplete();
    }, 250);

    return () => window.clearTimeout(timeout);
  }, [pendingPageJump, onPageJumpComplete]);

  useEffect(() => {
    if (!scrollRef.current || pages.length === 0) return;
    const container = scrollRef.current;

    const observer = new IntersectionObserver(
      (entries) => {
        if (scrollLockRef.current) return;
        let bestPage = activePageRef.current;
        let bestRatio = 0;

        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const page = Number(entry.target.getAttribute('data-page-number'));
          if (!page) return;
          if (entry.intersectionRatio > bestRatio) {
            bestRatio = entry.intersectionRatio;
            bestPage = page;
          }
        });

        if (bestPage !== activePageRef.current) {
          onPageChange(bestPage);
        }
      },
      {
        root: container,
        threshold: [0.2, 0.4, 0.6, 0.8],
      },
    );

    pages.forEach((page) => {
      const node = pageRefs.current.get(page);
      if (node) observer.observe(node);
    });

    return () => observer.disconnect();
  }, [pages, onPageChange, effectiveScale]);

  useLayoutEffect(() => {
    if (!scrollRef.current) return;
    const container = scrollRef.current;

    const updateSize = () => {
      const rect = container.getBoundingClientRect();
      const styles = window.getComputedStyle(container);
      const paddingX = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
      const paddingY = parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom);
      setContainerSize({
        width: Math.max(0, rect.width - paddingX),
        height: Math.max(0, rect.height - paddingY),
      });
    };

    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (!scrollRef.current) return;
    if (scrollLockRef.current) return;
    if (pendingPageJump) return;

    const container = scrollRef.current;
    const prevScale = scaleRef.current;
    if (prevScale === effectiveScale) return;

    const previousScrollHeight = container.scrollHeight;
    const previousCenter = container.scrollTop + container.clientHeight / 2;
    const ratio = previousScrollHeight ? previousCenter / previousScrollHeight : 0;

    scaleRef.current = effectiveScale;
    scrollLockRef.current = true;
    requestAnimationFrame(() => {
      const nextScrollHeight = container.scrollHeight;
      const nextCenter = ratio * nextScrollHeight;
      container.scrollTop = Math.max(0, nextCenter - container.clientHeight / 2);
      scrollLockRef.current = false;
    });
  }, [effectiveScale, pendingPageJump]);

  if (!pdfDoc || pages.length === 0) {
    return (
      <div className="viewer viewer--empty">
        <div className="viewer__placeholder">
          <h2>No document loaded</h2>
          <p>Upload a PDF to start editing fields.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="viewer" ref={scrollRef}>
      <div className="viewer__document">
        {pages.map((page) => (
          <PdfPage
            key={page}
            pdfDoc={pdfDoc}
            pageNumber={page}
            scale={effectiveScale}
            pageSize={pageSizes[page] || EMPTY_SIZE}
            fields={fieldsByPage.get(page) || []}
            showFields={showFields}
            showFieldNames={showFieldNames}
            showFieldInfo={showFieldInfo}
            selectedFieldId={selectedFieldId}
            onSelectField={onSelectField}
            onUpdateField={onUpdateField}
            registerRef={registerPageRef(page)}
            isActive={activePages.has(page)}
          />
        ))}
      </div>
    </div>
  );
}
