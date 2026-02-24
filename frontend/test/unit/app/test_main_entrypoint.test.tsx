import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const entrypointMocks = vi.hoisted(() => {
  const renderSpy = vi.fn();
  return {
    renderSpy,
    createRoot: vi.fn(() => ({
      render: renderSpy,
    })),
    App: vi.fn(() => <div data-testid="app-view">App shell</div>),
    LegalPage: vi.fn(({ kind }: { kind: string }) => <div data-testid={`legal-${kind}`}>Legal {kind}</div>),
    UsageDocsPage: vi.fn(({ pageKey, unknownSlug }: { pageKey: string; unknownSlug?: string | null }) => (
      <div data-testid={`usage-docs-${pageKey}`}>Usage docs {pageKey} {unknownSlug ?? ''}</div>
    )),
  };
});

vi.mock('react-dom/client', () => ({
  createRoot: entrypointMocks.createRoot,
}));

vi.mock('../../../src/App', () => ({
  default: entrypointMocks.App,
}));

vi.mock('../../../src/components/pages/LegalPage', () => ({
  default: entrypointMocks.LegalPage,
}));

vi.mock('../../../src/components/pages/UsageDocsPage', () => ({
  default: entrypointMocks.UsageDocsPage,
}));

const importEntrypoint = async (pathname: string) => {
  window.history.replaceState({}, '', pathname);
  vi.resetModules();
  await import('../../../src/main');
};

const renderCapturedTree = () => {
  const tree = entrypointMocks.renderSpy.mock.calls.at(-1)?.[0] as ReactNode | undefined;
  expect(tree).toBeDefined();
  render(<>{tree}</>);
};

describe('main entrypoint', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="root"></div>';
    entrypointMocks.renderSpy.mockClear();
    entrypointMocks.createRoot.mockClear();
    entrypointMocks.App.mockClear();
    entrypointMocks.LegalPage.mockClear();
    entrypointMocks.UsageDocsPage.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders App on non-legal routes and performs best-effort health warmup', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await importEntrypoint('/');
    renderCapturedTree();

    expect(fetchMock).toHaveBeenCalledWith('/api/health', { method: 'GET', mode: 'cors' });
    expect(screen.getByTestId('app-view')).toBeTruthy();
    expect(screen.queryByTestId('legal-privacy')).toBeNull();
    expect(screen.queryByTestId('legal-terms')).toBeNull();
    expect(screen.queryByTestId('usage-docs-index')).toBeNull();
  });

  it.each([
    ['/privacy', 'privacy'],
    ['/privacy-policy', 'privacy'],
    ['/terms', 'terms'],
    ['/terms-of-service', 'terms'],
  ])('renders LegalPage kind=%s route=%s', async (pathname, kind) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await importEntrypoint(pathname);
    renderCapturedTree();

    expect(screen.getByTestId(`legal-${kind}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it.each([
    ['/usage-docs', 'index'],
    ['/usage-docs/getting-started', 'getting-started'],
    ['/usage-docs/editor-workflow', 'editor-workflow'],
    ['/docs/search-fill', 'search-fill'],
    ['/usage-docs/not-a-real-page', 'index'],
  ])('renders UsageDocs pageKey=%s route=%s', async (pathname, pageKey) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await importEntrypoint(pathname);
    renderCapturedTree();

    expect(screen.getByTestId(`usage-docs-${pageKey}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it('does not crash when warmup fetch rejects', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('warmup failed'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(importEntrypoint('/')).resolves.toBeUndefined();
    renderCapturedTree();

    expect(screen.getByTestId('app-view')).toBeTruthy();
  });
});
