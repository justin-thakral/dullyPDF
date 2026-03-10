import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

type ContactDialogProps = {
  open: boolean;
  onClose: () => void;
  defaultEmail?: string | null;
};

vi.mock('../../../../src/components/features/ContactDialog', () => ({
  ContactDialog: ({ open, onClose, defaultEmail }: ContactDialogProps) => (
    <div data-testid="contact-dialog">
      <div>Contact open: {open ? 'yes' : 'no'}</div>
      <div>Default email: {defaultEmail ?? 'none'}</div>
      {open ? (
        <button type="button" onClick={onClose}>
          Close contact dialog
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock('../../../../src/components/ui/CommonFormsAttribution', () => ({
  CommonFormsAttribution: () => <span>CommonForms by jbarrow</span>,
}));

import Homepage from '../../../../src/components/pages/Homepage';

type MatchMediaListener = (event: MediaQueryListEvent) => void;
type MatchMediaState = {
  matches: boolean;
  listeners: Set<MatchMediaListener>;
  legacyListeners: Set<MatchMediaListener>;
};

const originalMatchMedia = window.matchMedia;
let matchMediaStates = new Map<string, MatchMediaState>();

const installMatchMedia = (initial: Record<string, boolean> = {}) => {
  matchMediaStates = new Map();
  window.matchMedia = ((query: string) => {
    let state = matchMediaStates.get(query);
    if (!state) {
      state = {
        matches: initial[query] ?? false,
        listeners: new Set<MatchMediaListener>(),
        legacyListeners: new Set<MatchMediaListener>(),
      };
      matchMediaStates.set(query, state);
    }

    return {
      get matches() {
        return state!.matches;
      },
      media: query,
      onchange: null,
      addEventListener: (_eventName: string, listener: MatchMediaListener) => {
        state!.listeners.add(listener);
      },
      removeEventListener: (_eventName: string, listener: MatchMediaListener) => {
        state!.listeners.delete(listener);
      },
      addListener: (listener: MatchMediaListener) => {
        state!.legacyListeners.add(listener);
      },
      removeListener: (listener: MatchMediaListener) => {
        state!.legacyListeners.delete(listener);
      },
      dispatchEvent: () => true,
    } as MediaQueryList;
  }) as typeof window.matchMedia;
};

const setMatchMedia = (query: string, matches: boolean) => {
  const state = matchMediaStates.get(query);
  if (!state) {
    throw new Error(`matchMedia query not registered: ${query}`);
  }
  state.matches = matches;
  const event = { matches, media: query } as MediaQueryListEvent;
  state.listeners.forEach((listener) => listener(event));
  state.legacyListeners.forEach((listener) => listener(event));
};

describe('Homepage', () => {
  beforeEach(() => {
    installMatchMedia({
      '(max-width: 1020px)': false,
      '(max-height: 749px)': false,
    });
    vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    document.documentElement.classList.remove('homepage-no-scroll');
    document.body.classList.remove('homepage-no-scroll');
  });

  it('wires Try Now and Demo CTAs to callbacks', async () => {
    const user = userEvent.setup();
    const onStartWorkflow = vi.fn();
    const onStartDemo = vi.fn();

    render(<Homepage onStartWorkflow={onStartWorkflow} onStartDemo={onStartDemo} />);

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'Automatic PDF Templates, Fill By Link, and Database Mapping',
      }),
    ).toBeTruthy();

    const ctaButtons = screen.getByRole('button', { name: 'Try Now' }).parentElement;
    if (!ctaButtons) {
      throw new Error('CTA button group not found');
    }

    await user.click(screen.getByRole('button', { name: 'Try Now' }));
    await user.click(within(ctaButtons).getByRole('button', { name: 'Demo' }));

    expect(onStartWorkflow).toHaveBeenCalledTimes(1);
    expect(onStartDemo).toHaveBeenCalledTimes(1);
  });

  it('renders compact feature-plan links in the quick info card', () => {
    render(<Homepage onStartWorkflow={vi.fn()} />);

    expect(screen.getByText('Supported:')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'View free features' }).getAttribute('href')).toBe('/free-features');
    expect(screen.getByRole('link', { name: 'View premium features' }).getAttribute('href')).toBe('/premium-features');
    expect(screen.getByText('Free Feats:')).toBeTruthy();
    expect(screen.getByText('Premium Feats:')).toBeTruthy();
  });

  it('navigates mobile walkthrough steps with proper boundaries', async () => {
    const user = userEvent.setup();
    render(<Homepage onStartWorkflow={vi.fn()} />);

    const prevButton = screen.getByRole('button', { name: 'Previous demo step' }) as HTMLButtonElement;
    const nextButton = screen.getByRole('button', { name: 'Next demo step' }) as HTMLButtonElement;

    expect(prevButton.disabled).toBe(true);
    expect(screen.getByText('Step 1 of 9')).toBeTruthy();

    for (let index = 0; index < 8; index += 1) {
      await user.click(nextButton);
    }

    expect(screen.getByText('Step 9 of 9')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Create groups for full document workflows' })).toBeTruthy();
    expect(nextButton.disabled).toBe(true);

    await user.click(prevButton);
    expect(screen.getByText('Step 8 of 9')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Respondents fill a mock form, not the PDF' })).toBeTruthy();
  });

  it('shows Sign in for signed-out users and Profile for signed-in users', async () => {
    const user = userEvent.setup();
    const onSignIn = vi.fn();
    const onOpenProfile = vi.fn();

    const { rerender } = render(<Homepage onStartWorkflow={vi.fn()} onSignIn={onSignIn} />);

    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(onSignIn).toHaveBeenCalledTimes(1);

    rerender(
      <Homepage
        onStartWorkflow={vi.fn()}
        userEmail="profile@example.com"
        onOpenProfile={onOpenProfile}
      />,
    );

    expect(screen.queryByRole('button', { name: 'Sign in' })).toBeNull();

    const profileButton = screen.getByRole('button', { name: /Profile/ });
    expect(profileButton.getAttribute('title')).toBe('profile@example.com');
    await user.click(profileButton);
    expect(onOpenProfile).toHaveBeenCalledTimes(1);
  });

  it('opens and closes contact dialog and passes defaultEmail', async () => {
    const user = userEvent.setup();

    render(<Homepage onStartWorkflow={vi.fn()} userEmail="owner@example.com" />);

    expect(screen.getByText('Contact open: no')).toBeTruthy();
    expect(screen.getByText('Default email: owner@example.com')).toBeTruthy();

    await user.click(screen.getAllByRole('button', { name: 'Contact' })[0]);
    expect(screen.getByText('Contact open: yes')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Close contact dialog' }));
    expect(screen.getByText('Contact open: no')).toBeTruthy();
  });

  it('renders mobile combined docs/legal link', () => {
    render(<Homepage onStartWorkflow={vi.fn()} />);

    const mobileCta = document.querySelector('.mobile-cta');
    expect(mobileCta).toBeTruthy();
    if (!mobileCta) return;

    const ctaLinks = within(mobileCta).getAllByRole('link');
    const combinedLink = within(mobileCta).getByRole('link', { name: 'Docs & Privacy & Terms' });

    expect(combinedLink.getAttribute('href')).toBe('/usage-docs');
    expect(ctaLinks.map((link) => link.textContent?.trim())).toEqual(['Docs & Privacy & Terms']);
  });

  it('hides Try DullyPDF footer link on mobile footer layout', () => {
    installMatchMedia({
      '(max-width: 1020px)': true,
      '(max-width: 900px)': true,
      '(max-height: 749px)': false,
    });

    render(<Homepage onStartWorkflow={vi.fn()} />);

    expect(screen.queryByRole('link', { name: 'Try DullyPDF' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Getting Started' }).getAttribute('href')).toBe(
      '/usage-docs/getting-started',
    );
  });

  it('renders footer hub links for workflows and industries', () => {
    render(<Homepage onStartWorkflow={vi.fn()} />);

    expect(screen.getByRole('link', { name: 'Workflow Library' }).getAttribute('href')).toBe('/workflows');
    expect(screen.getByRole('link', { name: 'Industry Solutions' }).getAttribute('href')).toBe('/industries');
  });

  it('does not render visible SEO intent sections on homepage', () => {
    render(<Homepage onStartWorkflow={vi.fn()} />);

    expect(screen.queryByRole('heading', { level: 3, name: 'Popular search intents' })).toBeNull();
    expect(screen.queryByRole('heading', { level: 3, name: 'Industry automation pages' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'PDF to fillable form conversion' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Healthcare and medical intake PDF automation' })).toBeNull();
  });

  it('toggles homepage-no-scroll class based on desktop/mobile media queries and cleans up on unmount', () => {
    const { unmount } = render(<Homepage onStartWorkflow={vi.fn()} />);

    expect(document.documentElement.classList.contains('homepage-no-scroll')).toBe(true);
    expect(document.body.classList.contains('homepage-no-scroll')).toBe(true);

    setMatchMedia('(max-width: 1020px)', true);
    expect(document.documentElement.classList.contains('homepage-no-scroll')).toBe(false);
    expect(document.body.classList.contains('homepage-no-scroll')).toBe(false);

    setMatchMedia('(max-width: 1020px)', false);
    expect(document.documentElement.classList.contains('homepage-no-scroll')).toBe(true);
    expect(document.body.classList.contains('homepage-no-scroll')).toBe(true);

    unmount();
    expect(document.documentElement.classList.contains('homepage-no-scroll')).toBe(false);
    expect(document.body.classList.contains('homepage-no-scroll')).toBe(false);
  });

  it('does not add homepage-no-scroll on mobile-sized viewports', () => {
    installMatchMedia({
      '(max-width: 1020px)': true,
      '(max-height: 749px)': false,
    });

    render(<Homepage onStartWorkflow={vi.fn()} />);

    expect(document.documentElement.classList.contains('homepage-no-scroll')).toBe(false);
    expect(document.body.classList.contains('homepage-no-scroll')).toBe(false);
  });
});
