import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});

if (typeof window !== 'undefined') {
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }

  if (!window.scrollTo) {
    window.scrollTo = () => {};
  }

  if (!window.requestAnimationFrame) {
    window.requestAnimationFrame = (cb: FrameRequestCallback) =>
      window.setTimeout(() => cb(performance.now()), 16);
  }

  if (!window.cancelAnimationFrame) {
    window.cancelAnimationFrame = (id: number) => {
      window.clearTimeout(id);
    };
  }

  if (!window.ResizeObserver) {
    class ResizeObserverMock {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (window as any).ResizeObserver = ResizeObserverMock;
    (globalThis as any).ResizeObserver = ResizeObserverMock;
  }

  if (!window.IntersectionObserver) {
    class IntersectionObserverMock {
      constructor(_callback: IntersectionObserverCallback, _options?: IntersectionObserverInit) {}
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    (window as any).IntersectionObserver = IntersectionObserverMock;
    (globalThis as any).IntersectionObserver = IntersectionObserverMock;
  }

  if (!window.MutationObserver) {
    class MutationObserverMock {
      constructor(_callback: MutationCallback) {}
      observe() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    (window as any).MutationObserver = MutationObserverMock;
    (globalThis as any).MutationObserver = MutationObserverMock;
  }

  if (typeof CSS !== 'undefined' && !CSS.escape) {
    (CSS as any).escape = (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }
}
