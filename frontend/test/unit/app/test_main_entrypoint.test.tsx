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
    PublicNotFoundPage: vi.fn(({ requestedPath }: { requestedPath: string }) => (
      <div data-testid="public-not-found">Public not found {requestedPath}</div>
    )),
    FillLinkPublicPage: vi.fn(({ token }: { token: string }) => (
      <div data-testid="fill-link-public">Fill link {token}</div>
    )),
    AccountActionPage: vi.fn(() => <div data-testid="account-action-page">Account action</div>),
    IntentHubPage: vi.fn(({ hubKey }: { hubKey: string }) => <div data-testid={`intent-hub-${hubKey}`}>Hub {hubKey}</div>),
    FeaturePlanPage: vi.fn(({ pageKey }: { pageKey: string }) => (
      <div data-testid={`feature-plan-${pageKey}`}>Feature plan {pageKey}</div>
    )),
    IntentLandingPage: vi.fn(({ pageKey }: { pageKey: string }) => (
      <div data-testid={`intent-${pageKey}`}>Intent {pageKey}</div>
    )),
    UsageDocsPage: vi.fn(({ pageKey }: { pageKey: string }) => (
      <div data-testid={`usage-docs-${pageKey}`}>Usage docs {pageKey}</div>
    )),
    UsageDocsNotFoundPage: vi.fn(({ requestedPath }: { requestedPath: string }) => (
      <div data-testid="usage-docs-not-found">Usage docs not found {requestedPath}</div>
    )),
    initializeGoogleAds: vi.fn(),
    ensureBackendReady: vi.fn().mockResolvedValue(undefined),
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

vi.mock('../../../src/components/pages/PublicNotFoundPage', () => ({
  default: entrypointMocks.PublicNotFoundPage,
}));

vi.mock('../../../src/components/pages/FillLinkPublicPage', () => ({
  default: entrypointMocks.FillLinkPublicPage,
}));

vi.mock('../../../src/components/pages/AccountActionPage', () => ({
  default: entrypointMocks.AccountActionPage,
}));

vi.mock('../../../src/components/pages/IntentHubPage', () => ({
  default: entrypointMocks.IntentHubPage,
}));

vi.mock('../../../src/components/pages/FeaturePlanPage', () => ({
  default: entrypointMocks.FeaturePlanPage,
}));

vi.mock('../../../src/components/pages/IntentLandingPage', () => ({
  default: entrypointMocks.IntentLandingPage,
}));

vi.mock('../../../src/components/pages/UsageDocsPage', () => ({
  default: entrypointMocks.UsageDocsPage,
}));

vi.mock('../../../src/components/pages/UsageDocsNotFoundPage', () => ({
  default: entrypointMocks.UsageDocsNotFoundPage,
}));

vi.mock('../../../src/utils/googleAds', () => ({
  initializeGoogleAds: entrypointMocks.initializeGoogleAds,
}));

vi.mock('../../../src/services/apiConfig', () => ({
  ensureBackendReady: entrypointMocks.ensureBackendReady,
}));

const importEntrypoint = async (pathname: string) => {
  window.history.replaceState({}, '', pathname);
  vi.resetModules();
  await import('../../../src/main');
};

const renderCapturedTree = async () => {
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
    entrypointMocks.PublicNotFoundPage.mockClear();
    entrypointMocks.FillLinkPublicPage.mockClear();
    entrypointMocks.AccountActionPage.mockClear();
    entrypointMocks.IntentHubPage.mockClear();
    entrypointMocks.FeaturePlanPage.mockClear();
    entrypointMocks.IntentLandingPage.mockClear();
    entrypointMocks.UsageDocsPage.mockClear();
    entrypointMocks.UsageDocsNotFoundPage.mockClear();
    entrypointMocks.initializeGoogleAds.mockClear();
    entrypointMocks.ensureBackendReady.mockReset().mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders App on the root route without workspace warmup', async () => {
    await importEntrypoint('/');
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(entrypointMocks.initializeGoogleAds).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId('app-view')).toBeTruthy();
    expect(screen.queryByTestId('legal-privacy')).toBeNull();
    expect(screen.queryByTestId('legal-terms')).toBeNull();
    expect(screen.queryByTestId('usage-docs-index')).toBeNull();
  });

  it.each([
    ['/upload', { kind: 'upload-root' }],
    ['/ui', { kind: 'ui-root' }],
    ['/ui/profile', { kind: 'profile' }],
    ['/ui/forms/saved-1', { kind: 'saved-form', formId: 'saved-1' }],
    ['/ui/groups/group-1?template=saved-2', { kind: 'group', groupId: 'group-1', templateId: 'saved-2' }],
  ])('routes %s through App with the parsed workspace browser route', async (pathname, expectedRoute) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(entrypointMocks.initializeGoogleAds).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId('app-view')).toBeTruthy();
    expect(entrypointMocks.App).toHaveBeenCalled();
    expect(entrypointMocks.App.mock.calls.at(-1)?.[0]?.initialBrowserRoute).toEqual(expectedRoute);
  });

  it.each([
    ['/workflows', 'workflows'],
    ['/industries', 'industries'],
  ])('renders intent hub route %s', async (pathname, hubKey) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(entrypointMocks.initializeGoogleAds).not.toHaveBeenCalled();
    expect(await screen.findByTestId(`intent-hub-${hubKey}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it.each([
    ['/free-features', 'free-features'],
    ['/premium-features', 'premium-features'],
  ])('renders feature plan route %s', async (pathname, pageKey) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(entrypointMocks.initializeGoogleAds).not.toHaveBeenCalled();
    expect(await screen.findByTestId(`feature-plan-${pageKey}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it('renders the branded account-action route without warmup fetch', async () => {
    await importEntrypoint('/account-action?mode=verifyEmail&oobCode=abc123');
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(entrypointMocks.initializeGoogleAds).not.toHaveBeenCalled();
    expect(await screen.findByTestId('account-action-page')).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it('renders the public Fill By Link route without backend warmup', async () => {
    await importEntrypoint('/respond/token-1');
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(entrypointMocks.initializeGoogleAds).not.toHaveBeenCalled();
    expect(await screen.findByTestId('fill-link-public')).toBeTruthy();
    expect(screen.getByText('Fill link token-1')).toBeTruthy();
  });

  it('normalizes legacy /verify-email links to /account-action before rendering', async () => {
    await importEntrypoint('/verify-email?mode=verifyEmail&oobCode=abc123');
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId('account-action-page')).toBeTruthy();
    expect(window.location.pathname).toBe('/account-action');
  });

  it.each([
    ['/privacy', 'privacy'],
    ['/privacy-policy', 'privacy'],
    ['/terms', 'terms'],
    ['/terms-of-service', 'terms'],
  ])('renders LegalPage kind=%s route=%s', async (pathname, kind) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId(`legal-${kind}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it.each([
    ['/usage-docs', 'index'],
    ['/usage-docs/getting-started', 'getting-started'],
    ['/usage-docs/editor-workflow', 'editor-workflow'],
    ['/usage-docs/create-group', 'create-group'],
    ['/usage-docs/search-fill/', 'search-fill'],
  ])('renders UsageDocs pageKey=%s route=%s', async (pathname, pageKey) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId(`usage-docs-${pageKey}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
    expect(screen.queryByTestId('usage-docs-not-found')).toBeNull();
  });

  it.each([
    ['/pdf-to-fillable-form', 'pdf-to-fillable-form'],
    ['/pdf-to-database-template', 'pdf-to-database-template'],
    ['/fill-pdf-from-csv', 'fill-pdf-from-csv'],
    ['/fill-information-in-pdf', 'fill-information-in-pdf'],
    ['/fillable-form-field-name', 'fillable-form-field-name'],
    ['/healthcare-pdf-automation', 'healthcare-pdf-automation'],
    ['/acord-form-automation', 'acord-form-automation'],
    ['/real-estate-pdf-automation', 'real-estate-pdf-automation'],
    ['/government-form-automation', 'government-form-automation'],
    ['/finance-loan-pdf-automation', 'finance-loan-pdf-automation'],
    ['/hr-pdf-automation', 'hr-pdf-automation'],
    ['/legal-pdf-workflow-automation', 'legal-pdf-workflow-automation'],
    ['/education-form-automation', 'education-form-automation'],
    ['/nonprofit-pdf-form-automation', 'nonprofit-pdf-form-automation'],
    ['/logistics-pdf-automation', 'logistics-pdf-automation'],
  ])('renders intent landing page for route %s', async (pathname, pageKey) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId(`intent-${pageKey}`)).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it('canonicalizes /docs/* routes to /usage-docs/* before rendering', async () => {
    await importEntrypoint('/docs/search-fill');
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId('usage-docs-search-fill')).toBeTruthy();
    expect(window.location.pathname).toBe('/usage-docs/search-fill');
  });

  it.each([
    '/usage-docs/not-a-real-page',
    '/usage-docs/search-fill/extra',
    '/docs/not-a-real-page',
  ])('renders UsageDocsNotFoundPage for unknown docs routes (%s)', async (pathname) => {
    await importEntrypoint(pathname);
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId('usage-docs-not-found')).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it('renders PublicNotFoundPage for unknown public routes', async () => {
    await importEntrypoint('/this-path-does-not-exist');
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId('public-not-found')).toBeTruthy();
    expect(screen.queryByTestId('app-view')).toBeNull();
  });

  it('renders workspace routes without relying on entrypoint warmup', async () => {
    await expect(importEntrypoint('/upload')).resolves.toBeUndefined();
    await renderCapturedTree();

    expect(entrypointMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(await screen.findByTestId('app-view')).toBeTruthy();
  });
});
