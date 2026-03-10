import { StrictMode } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useFillLinks } from '../../../src/hooks/useFillLinks';

const apiMocks = vi.hoisted(() => ({
  getFillLinks: vi.fn(),
  getFillLinkResponses: vi.fn(),
  createFillLink: vi.fn(),
  closeFillLink: vi.fn(),
  updateFillLink: vi.fn(),
}));

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    getFillLinks: apiMocks.getFillLinks,
    getFillLinkResponses: apiMocks.getFillLinkResponses,
    createFillLink: apiMocks.createFillLink,
    closeFillLink: apiMocks.closeFillLink,
    updateFillLink: apiMocks.updateFillLink,
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function createLink(id: string, responseCount = 1) {
  return {
    id,
    status: 'active',
    responseCount,
    maxResponses: 1000,
    publicPath: `/respond/${id}`,
  };
}

function createResponse(id: string, respondentLabel: string) {
  return {
    id,
    linkId: 'link-1',
    respondentLabel,
    answers: { full_name: respondentLabel },
    submittedAt: '2026-03-10T12:00:00.000Z',
  };
}

function renderHarness(scopeId = 'tpl-1') {
  const setBannerNotice = vi.fn();
  let latestHook: ReturnType<typeof useFillLinks> | null = null;

  function Harness({ nextScopeId }: { nextScopeId: string | null }) {
    latestHook = useFillLinks({
      verifiedUser: { uid: 'user-1' },
      enabled: false,
      scopeType: 'template',
      scopeId: nextScopeId,
      scopeName: 'Template One',
      fields: [],
      checkboxRules: [],
      setBannerNotice,
    });
    return null;
  }

  const rendered = render(<Harness nextScopeId={scopeId} />);

  return {
    ...rendered,
    setBannerNotice,
    get hook() {
      if (!latestHook) {
        throw new Error('Hook not initialized');
      }
      return latestHook;
    },
    rerenderScope(nextScopeId: string | null) {
      rendered.rerender(<Harness nextScopeId={nextScopeId} />);
    },
  };
}

describe('useFillLinks', () => {
  beforeEach(() => {
    apiMocks.getFillLinks.mockReset();
    apiMocks.getFillLinkResponses.mockReset();
    apiMocks.createFillLink.mockReset();
    apiMocks.closeFillLink.mockReset();
    apiMocks.updateFillLink.mockReset();
  });

  it('ignores stale respondent search results that resolve out of order', async () => {
    const link = createLink('link-1', 2);
    const slowSearch = deferred<{ link: ReturnType<typeof createLink>; responses: ReturnType<typeof createResponse>[] }>();
    const fastSearch = deferred<{ link: ReturnType<typeof createLink>; responses: ReturnType<typeof createResponse>[] }>();

    apiMocks.getFillLinks.mockResolvedValue([link]);
    apiMocks.getFillLinkResponses
      .mockResolvedValueOnce({
        link,
        responses: [createResponse('resp-initial', 'Initial Response')],
      })
      .mockImplementationOnce(() => slowSearch.promise)
      .mockImplementationOnce(() => fastSearch.promise);

    const harness = renderHarness();

    await act(async () => {
      await harness.hook.refreshForScope();
    });

    await waitFor(() => {
      expect(harness.hook.currentLink?.id).toBe('link-1');
      expect(harness.hook.responses).toHaveLength(1);
    });

    act(() => {
      void harness.hook.searchResponses('ada');
      void harness.hook.searchResponses('alan');
    });

    await act(async () => {
      fastSearch.resolve({
        link: createLink('link-1', 1),
        responses: [createResponse('resp-fast', 'Alan Turing')],
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(harness.hook.responses.map((entry) => entry.respondentLabel)).toEqual(['Alan Turing']);
    });

    await act(async () => {
      slowSearch.resolve({
        link: createLink('link-1', 1),
        responses: [createResponse('resp-slow', 'Ada Lovelace')],
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(harness.hook.responses.map((entry) => entry.respondentLabel)).toEqual(['Alan Turing']);
      expect(harness.hook.loadingResponses).toBe(false);
    });
  });

  it('ignores stale scope loads after the active template changes', async () => {
    const slowScope = deferred<ReturnType<typeof createLink>[]>();
    const fastScope = deferred<ReturnType<typeof createLink>[]>();
    const linkB = createLink('link-b', 1);

    apiMocks.getFillLinks
      .mockImplementationOnce(() => slowScope.promise)
      .mockImplementationOnce(() => fastScope.promise);
    apiMocks.getFillLinkResponses.mockResolvedValue({
      link: linkB,
      responses: [createResponse('resp-b', 'Bravo Response')],
    });

    const harness = renderHarness('tpl-a');
    const firstLoad = harness.hook.refreshForScope();
    harness.rerenderScope('tpl-b');
    const secondLoad = harness.hook.refreshForScope();

    await act(async () => {
      fastScope.resolve([linkB]);
      await secondLoad;
    });

    await waitFor(() => {
      expect(harness.hook.currentLink?.id).toBe('link-b');
      expect(harness.hook.responses.map((entry) => entry.respondentLabel)).toEqual(['Bravo Response']);
    });

    await act(async () => {
      slowScope.resolve([createLink('link-a', 1)]);
      await firstLoad;
    });

    await waitFor(() => {
      expect(harness.hook.currentLink?.id).toBe('link-b');
      expect(harness.hook.responses.map((entry) => entry.respondentLabel)).toEqual(['Bravo Response']);
    });

    expect(apiMocks.getFillLinkResponses).toHaveBeenCalledTimes(1);
    expect(apiMocks.getFillLinkResponses).toHaveBeenCalledWith('link-b', {
      search: undefined,
      limit: 100,
    });
  });

  it('exposes link metadata before respondent loading finishes', async () => {
    const link = createLink('link-1', 2);
    const slowResponses = deferred<{
      link: ReturnType<typeof createLink>;
      responses: ReturnType<typeof createResponse>[];
    }>();

    apiMocks.getFillLinks.mockResolvedValue([link]);
    apiMocks.getFillLinkResponses.mockImplementationOnce(() => slowResponses.promise);

    const harness = renderHarness();

    await act(async () => {
      await harness.hook.refreshForScope();
    });

    await waitFor(() => {
      expect(harness.hook.currentLink?.id).toBe('link-1');
      expect(harness.hook.loadingLink).toBe(false);
      expect(harness.hook.loadingResponses).toBe(true);
    });

    await act(async () => {
      slowResponses.resolve({
        link,
        responses: [createResponse('resp-1', 'Ada Lovelace')],
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(harness.hook.loadingResponses).toBe(false);
      expect(harness.hook.responses.map((entry) => entry.respondentLabel)).toEqual(['Ada Lovelace']);
    });
  });

  it('completes the initial load in React strict mode', async () => {
    const link = createLink('link-strict', 1);
    apiMocks.getFillLinks.mockResolvedValue([link]);
    apiMocks.getFillLinkResponses.mockResolvedValue({
      link,
      responses: [createResponse('resp-strict', 'Grace Hopper')],
    });

    const setBannerNotice = vi.fn();
    let latestHook: ReturnType<typeof useFillLinks> | null = null;

    function Harness() {
      latestHook = useFillLinks({
        verifiedUser: { uid: 'user-1' },
        enabled: true,
        scopeType: 'template',
        scopeId: 'tpl-strict',
        scopeName: 'Strict Template',
        fields: [],
        checkboxRules: [],
        setBannerNotice,
      });
      return null;
    }

    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(latestHook?.loadingLink).toBe(false);
      expect(latestHook?.currentLink?.id).toBe('link-strict');
      expect(latestHook?.responses.map((entry) => entry.respondentLabel)).toEqual(['Grace Hopper']);
    });
  });
});
