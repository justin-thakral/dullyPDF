import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';

import type { PdfField } from '../../../../src/types';
import { PdfViewer } from '../../../../src/components/viewer/PdfViewer';

const overlayMocks = vi.hoisted(() => ({
  fieldOverlay: vi.fn(),
  fieldInputOverlay: vi.fn(),
}));

vi.mock('pdfjs-dist', () => ({
  AnnotationMode: {
    ENABLE_FORMS: 7,
  },
}));

vi.mock('../../../../src/components/viewer/FieldOverlay', () => ({
  FieldOverlay: (props: any) => {
    overlayMocks.fieldOverlay(props);
    return (
      <div
        className="mock-field-overlay"
        data-field-id={props.fields[0]?.id ?? ''}
      >
        FieldOverlay
      </div>
    );
  },
}));

vi.mock('../../../../src/components/viewer/FieldInputOverlay', () => ({
  FieldInputOverlay: (props: any) => {
    overlayMocks.fieldInputOverlay(props);
    return (
      <div
        className="mock-field-input-overlay"
        data-field-id={props.fields[0]?.id ?? ''}
      >
        FieldInputOverlay
      </div>
    );
  },
}));

type ObserverEntry = {
  target: Element;
  isIntersecting?: boolean;
  intersectionRatio?: number;
};

class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = [];
  private callback: IntersectionObserverCallback;
  observe: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  unobserve: ReturnType<typeof vi.fn>;

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    this.observe = vi.fn();
    this.disconnect = vi.fn();
    this.unobserve = vi.fn();
    MockIntersectionObserver.instances.push(this);
  }

  trigger(entries: ObserverEntry[]) {
    const normalized = entries.map((entry) => ({
      boundingClientRect: {} as DOMRectReadOnly,
      intersectionRect: {} as DOMRectReadOnly,
      rootBounds: null,
      time: 0,
      isVisible: true,
      isIntersecting: entry.isIntersecting ?? true,
      intersectionRatio: entry.intersectionRatio ?? 0,
      target: entry.target,
    })) as IntersectionObserverEntry[];
    this.callback(normalized, this as unknown as IntersectionObserver);
  }
}

function makeField(overrides: Partial<PdfField> & Pick<PdfField, 'id' | 'name' | 'type' | 'page'>): PdfField {
  return {
    id: overrides.id,
    name: overrides.name,
    type: overrides.type,
    page: overrides.page,
    rect: { x: 10, y: 10, width: 80, height: 20 },
    ...overrides,
  };
}

function createPdfDoc(numPages: number) {
  return {
    numPages,
    getPage: vi.fn(async (_pageNumber: number) => ({
      getViewport: vi.fn(({ scale }: { scale: number }) => ({
        width: 300 * scale,
        height: 500 * scale,
      })),
      render: vi.fn(() => ({
        promise: Promise.resolve(),
        cancel: vi.fn(),
      })),
    })),
  };
}

function makePageSizes(numPages: number) {
  const sizes: Record<number, { width: number; height: number }> = {};
  for (let page = 1; page <= numPages; page += 1) {
    sizes[page] = { width: 300, height: 500 };
  }
  return sizes;
}

function buildProps(overrides: Partial<ComponentProps<typeof PdfViewer>> = {}) {
  const pdfDoc = createPdfDoc(5);
  return {
    pdfDoc: pdfDoc as any,
    pageNumber: 1,
    scale: 1,
    pageSizes: makePageSizes(5),
    fields: [] as PdfField[],
    showFields: false,
    showFieldNames: false,
    showFieldInfo: false,
    moveEnabled: true,
    resizeEnabled: true,
    createEnabled: true,
    activeCreateTool: null,
    selectedFieldId: null,
    onSelectField: vi.fn(),
    onUpdateField: vi.fn(),
    onUpdateFieldGeometry: vi.fn(),
    onCreateFieldWithRect: vi.fn(),
    onBeginFieldChange: vi.fn(),
    onCommitFieldChange: vi.fn(),
    onPageChange: vi.fn(),
    pendingPageJump: null,
    onPageJumpComplete: vi.fn(),
    ...overrides,
  };
}

describe('PdfViewer', () => {
  const originalScrollIntoView = Element.prototype.scrollIntoView;
  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  const originalIntersectionObserver = globalThis.IntersectionObserver;

  beforeEach(() => {
    vi.clearAllMocks();
    MockIntersectionObserver.instances = [];
    Element.prototype.scrollIntoView = vi.fn();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({} as CanvasRenderingContext2D));
    (globalThis as any).IntersectionObserver = MockIntersectionObserver;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  afterAll(() => {
    Element.prototype.scrollIntoView = originalScrollIntoView;
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    (globalThis as any).IntersectionObserver = originalIntersectionObserver;
  });

  it('shows empty state when no document is loaded', () => {
    render(<PdfViewer {...buildProps({ pdfDoc: null, pageSizes: {} })} />);

    expect(screen.getByText('No document loaded')).toBeTruthy();
    expect(screen.getByText('Upload a PDF to start editing fields.')).toBeTruthy();
  });

  it('virtualizes active pages around current page and pending page jump anchors', () => {
    const pdfDoc = createPdfDoc(7);
    const props = buildProps({
      pdfDoc: pdfDoc as any,
      pageNumber: 4,
      pageSizes: makePageSizes(7),
    });
    const { rerender } = render(<PdfViewer {...props} />);

    expect(screen.getByText('Page 1')).toBeTruthy();
    expect(screen.getByText('Page 7')).toBeTruthy();
    expect(screen.queryByText('Page 4')).toBeNull();
    expect(screen.queryByText('Page 6')).toBeNull();

    rerender(<PdfViewer {...props} pendingPageJump={6} />);
    expect(screen.getByText('Page 2')).toBeTruthy();
    expect(screen.getByText('Page 3')).toBeTruthy();
    expect(screen.queryByText('Page 6')).toBeNull();
  });

  it('scrolls to pending page jump and calls completion callback after timeout', async () => {
    const onPageJumpComplete = vi.fn();
    const pdfDoc = createPdfDoc(4);
    render(
      <PdfViewer
        {...buildProps({
          pdfDoc: pdfDoc as any,
          pageSizes: makePageSizes(4),
          pendingPageJump: 3,
          onPageJumpComplete,
        })}
      />,
    );

    await waitFor(() => {
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    });
    const scrollCall = (Element.prototype.scrollIntoView as any).mock.calls[0][0];
    expect(scrollCall).toEqual({ behavior: 'smooth', block: 'start' });
    expect(onPageJumpComplete).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onPageJumpComplete).toHaveBeenCalledTimes(1);
    });
  });

  it('does not auto-scroll selected field in either overlay mode', async () => {
    const selectedField = makeField({
      id: 'selected-field',
      name: 'Selected',
      type: 'text',
      page: 2,
    });
    const pdfDoc = createPdfDoc(3);
    const props = buildProps({
      pdfDoc: pdfDoc as any,
      pageSizes: makePageSizes(3),
      pageNumber: 2,
      fields: [selectedField],
      selectedFieldId: 'selected-field',
      showFields: true,
      showFieldInfo: false,
    });
    const { rerender } = render(<PdfViewer {...props} />);

    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    (Element.prototype.scrollIntoView as any).mockClear();
    rerender(<PdfViewer {...props} showFields={false} showFieldInfo />);

    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it('updates current page from intersection observer visibility changes', () => {
    const onPageChange = vi.fn();
    render(
      <PdfViewer
        {...buildProps({
          pdfDoc: createPdfDoc(3) as any,
          pageSizes: makePageSizes(3),
          pageNumber: 1,
          onPageChange,
        })}
      />,
    );

    const observer = MockIntersectionObserver.instances[0];
    const page1 = document.querySelector('[data-page-number="1"]') as Element;
    const page2 = document.querySelector('[data-page-number="2"]') as Element;
    observer.trigger([
      { target: page1, intersectionRatio: 0.25, isIntersecting: true },
      { target: page2, intersectionRatio: 0.7, isIntersecting: true },
    ]);

    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('composes overlays according to showFields/showFieldInfo toggles', () => {
    const field = makeField({ id: 'f1', name: 'Name', type: 'text', page: 1 });
    const props = buildProps({
      pdfDoc: createPdfDoc(2) as any,
      pageSizes: makePageSizes(2),
      fields: [field],
      pageNumber: 1,
      showFields: false,
      showFieldInfo: false,
    });
    const { container, rerender } = render(<PdfViewer {...props} />);

    expect(container.querySelectorAll('.mock-field-overlay')).toHaveLength(0);
    expect(container.querySelectorAll('.mock-field-input-overlay')).toHaveLength(0);

    rerender(<PdfViewer {...props} showFields showFieldInfo={false} />);
    expect(container.querySelectorAll('.mock-field-overlay').length).toBeGreaterThan(0);
    expect(container.querySelectorAll('.mock-field-input-overlay')).toHaveLength(0);

    rerender(<PdfViewer {...props} showFields={false} showFieldInfo />);
    expect(container.querySelectorAll('.mock-field-overlay')).toHaveLength(0);
    expect(container.querySelectorAll('.mock-field-input-overlay').length).toBeGreaterThan(0);
  });
});
