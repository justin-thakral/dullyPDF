import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const appState = vi.hoisted(() => ({
  authStateCallback: null as ((user: any) => void | Promise<void>) | null,
}));

const authMocks = vi.hoisted(() => ({
  onAuthStateChanged: vi.fn((callback: (user: any) => void | Promise<void>) => {
    appState.authStateCallback = callback;
    return vi.fn();
  }),
  signOut: vi.fn().mockResolvedValue(undefined),
}));

const apiServiceMocks = vi.hoisted(() => ({
  getSavedForms: vi.fn().mockResolvedValue([]),
  getProfile: vi.fn().mockResolvedValue(null),
  createBillingCheckoutSession: vi.fn(),
  reconcileBillingCheckoutFulfillment: vi.fn().mockResolvedValue({
    success: true,
    dryRun: false,
    scope: 'self',
    auditedEventCount: 0,
    candidateEventCount: 0,
    pendingReconciliationCount: 0,
    reconciledCount: 0,
    alreadyProcessedCount: 0,
    processingCount: 0,
    retryableCount: 0,
    failedCount: 0,
    invalidCount: 0,
    skippedForUserCount: 0,
    events: [],
  }),
  cancelBillingSubscription: vi.fn(),
  createTemplateSession: vi.fn().mockResolvedValue({ success: true, sessionId: 'session-1', fieldCount: 1 }),
  materializeFormPdf: vi.fn().mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' })),
  saveFormToProfile: vi.fn().mockResolvedValue({ success: true, id: 'saved-1' }),
  createSchema: vi.fn(),
  renameFields: vi.fn(),
  mapSchema: vi.fn(),
  createSavedFormSession: vi.fn(),
  loadSavedForm: vi.fn(),
  downloadSavedForm: vi.fn(),
  deleteSavedForm: vi.fn(),
  touchSession: vi.fn(),
}));

const detectionApiMocks = vi.hoisted(() => ({
  detectFields: vi.fn(),
  fetchDetectionStatus: vi.fn(),
  pollDetectionStatus: vi.fn(),
}));

const pdfMocks = vi.hoisted(() => ({
  loadPdfFromFile: vi.fn(),
  loadPageSizes: vi.fn(),
  extractFieldsFromPdf: vi.fn(),
}));

const uiMocks = vi.hoisted(() => ({
  headerBar: vi.fn((props: any) => (
    <div data-testid="header-bar">
      <button data-testid="save-profile" type="button" onClick={() => void props.onSaveToProfile?.()}>
        Save profile
      </button>
    </div>
  )),
  fieldListPanel: vi.fn((props: any) => (
    <div data-testid="field-list">{props.fields.map((field: any) => field.name).join('|')}</div>
  )),
  fieldInspector: vi.fn((props: any) => {
    const first = props.fields[0];
    return (
      <div data-testid="field-inspector">
        <button
          data-testid="rename-first"
          type="button"
          onClick={() => props.onUpdateField(first.id, { name: 'Renamed Name' })}
          disabled={!first}
        >
          Rename first
        </button>
        <button data-testid="undo" type="button" onClick={() => props.onUndo()} disabled={!props.canUndo}>
          Undo
        </button>
        <button data-testid="redo" type="button" onClick={() => props.onRedo()} disabled={!props.canRedo}>
          Redo
        </button>
      </div>
    );
  }),
}));

vi.mock('../../../src/services/auth', () => ({
  Auth: authMocks,
}));

vi.mock('../../../src/services/authTokenStore', () => ({
  setAuthToken: vi.fn(),
}));

vi.mock('../../../src/services/api', () => ({
  ApiService: apiServiceMocks,
}));

vi.mock('../../../src/services/detectionApi', () => ({
  detectFields: detectionApiMocks.detectFields,
  fetchDetectionStatus: detectionApiMocks.fetchDetectionStatus,
  pollDetectionStatus: detectionApiMocks.pollDetectionStatus,
}));

vi.mock('../../../src/utils/pdf', () => ({
  loadPdfFromFile: pdfMocks.loadPdfFromFile,
  loadPageSizes: pdfMocks.loadPageSizes,
  extractFieldsFromPdf: pdfMocks.extractFieldsFromPdf,
}));

vi.mock('../../../src/components/pages/Homepage', () => ({
  default: (props: any) => (
    <div data-testid="homepage">
      <button data-testid="start-workflow" type="button" onClick={() => props.onStartWorkflow?.()}>
        Start workflow
      </button>
    </div>
  ),
}));

vi.mock('../../../src/components/pages/LoginPage', () => ({
  default: () => <div data-testid="login-page">Login</div>,
}));

vi.mock('../../../src/components/pages/ProfilePage', () => ({
  default: (props: any) => (
    <div data-testid="profile-page">
      <div data-testid="billing-kind">{props.billingCheckoutInProgressKind ?? 'idle'}</div>
      <div data-testid="billing-cancel">{String(Boolean(props.billingCancelInProgress))}</div>
      <button
        data-testid="profile-start-monthly"
        type="button"
        onClick={() => props.onStartBillingCheckout?.('pro_monthly')}
        disabled={!props.onStartBillingCheckout}
      >
        Start monthly
      </button>
      <button
        data-testid="profile-cancel-subscription"
        type="button"
        onClick={() => props.onCancelBillingSubscription?.()}
        disabled={!props.onCancelBillingSubscription}
      >
        Cancel subscription
      </button>
      <button data-testid="profile-close" type="button" onClick={() => props.onClose?.()}>
        Close profile
      </button>
    </div>
  ),
}));

vi.mock('../../../src/components/pages/VerifyEmailPage', () => ({
  default: () => <div data-testid="verify-page">Verify</div>,
}));

vi.mock('../../../src/components/layout/HeaderBar', () => ({
  HeaderBar: uiMocks.headerBar,
}));

vi.mock('../../../src/components/layout/LegacyHeader', () => ({
  default: (props: any) => (
    <div data-testid="legacy-header">
      <button
        data-testid="open-profile"
        type="button"
        onClick={() => props.onOpenProfile?.()}
        disabled={!props.onOpenProfile}
      >
        Open profile
      </button>
    </div>
  ),
}));

vi.mock('../../../src/components/features/SearchFillModal', () => ({
  default: () => null,
}));

vi.mock('../../../src/components/demo/DemoTour', () => ({
  DemoTour: () => null,
}));

vi.mock('../../../src/components/panels/FieldInspectorPanel', () => ({
  FieldInspectorPanel: uiMocks.fieldInspector,
}));

vi.mock('../../../src/components/panels/FieldListPanel', () => ({
  FieldListPanel: uiMocks.fieldListPanel,
}));

vi.mock('../../../src/components/viewer/PdfViewer', () => ({
  PdfViewer: () => <div data-testid="pdf-viewer">Viewer</div>,
}));

vi.mock('../../../src/components/features/UploadComponent', () => ({
  default: (props: any) => (
    <button
      data-testid={`upload-${props.variant}`}
      type="button"
      onClick={() => props.onFileUpload?.(new File(['fake'], `${props.variant}.pdf`, { type: 'application/pdf' }))}
    >
      Upload {props.variant}
    </button>
  ),
}));

vi.mock('../../../src/components/ui/Alert', () => ({
  Alert: ({ message }: { message: string }) => <div role="alert">{message}</div>,
}));

vi.mock('../../../src/components/ui/Dialog', () => ({
  ConfirmDialog: () => null,
  PromptDialog: () => null,
  SavedFormsLimitDialog: () => null,
}));

vi.mock('../../../src/components/ui/CommonFormsAttribution', () => ({
  CommonFormsAttribution: () => <span>CommonForms</span>,
}));

const makeField = () => ({
  id: 'field-1',
  name: 'First Name',
  type: 'text',
  page: 1,
  rect: { x: 10, y: 10, width: 80, height: 12 },
  value: '',
});

const makePdfDoc = () => ({
  numPages: 1,
  destroy: vi.fn().mockResolvedValue(undefined),
  getData: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
});

const makeAuthUser = () => ({
  email: 'qa@example.com',
  emailVerified: true,
  providerData: [{ providerId: 'password' }],
  getIdTokenResult: vi.fn().mockResolvedValue({
    token: 'token-1',
    signInProvider: 'password',
  }),
});

const importApp = async () => {
  vi.resetModules();
  const module = await import('../../../src/App');
  return module.default;
};

const settleAuthAsSignedOut = async () => {
  await act(async () => {
    await appState.authStateCallback?.(null);
  });
};

const settleAuthAsSignedIn = async () => {
  await act(async () => {
    await appState.authStateCallback?.(makeAuthUser());
  });
};

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
    window.scrollTo = vi.fn();
    appState.authStateCallback = null;
    authMocks.onAuthStateChanged.mockClear();
    authMocks.signOut.mockClear();
    for (const mock of Object.values(apiServiceMocks)) {
      if ('mockClear' in mock) {
        (mock as unknown as { mockClear: () => void }).mockClear();
      }
    }
    for (const mock of Object.values(detectionApiMocks)) {
      if ('mockReset' in mock) {
        (mock as unknown as { mockReset: () => void }).mockReset();
      }
    }
    pdfMocks.loadPdfFromFile.mockReset().mockResolvedValue(makePdfDoc());
    pdfMocks.loadPageSizes.mockReset().mockResolvedValue({ 1: { width: 612, height: 792 } });
    pdfMocks.extractFieldsFromPdf.mockReset().mockResolvedValue([makeField()]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows auth loading state until auth callback settles', async () => {
    const App = await importApp();
    render(<App />);

    expect(screen.getByText('Loading workspace…')).toBeTruthy();
    expect(authMocks.onAuthStateChanged).toHaveBeenCalledTimes(1);
  });

  it('transitions from homepage to upload view via start workflow', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    fireEvent.click(screen.getByTestId('start-workflow'));

    expect(await screen.findByTestId('upload-detect')).toBeTruthy();
    expect(screen.getByTestId('upload-fillable')).toBeTruthy();
  });

  it('does not register duplicate auth listeners after signed-in state updates', async () => {
    const App = await importApp();
    render(<App />);

    expect(authMocks.onAuthStateChanged).toHaveBeenCalledTimes(1);

    const user = makeAuthUser();
    await act(async () => {
      await appState.authStateCallback?.(user);
    });

    await waitFor(() => {
      expect(authMocks.onAuthStateChanged).toHaveBeenCalledTimes(1);
    });
  });

  it('runs checkout flow from profile and surfaces checkout errors gracefully', async () => {
    apiServiceMocks.getProfile.mockResolvedValue({
      email: 'qa@example.com',
      role: 'base',
      creditsRemaining: 10,
      availableCredits: 10,
      monthlyCreditsRemaining: 0,
      refillCreditsRemaining: 0,
      refillCreditsLocked: false,
      creditPricing: {
        pageBucketSize: 5,
        renameBaseCost: 1,
        remapBaseCost: 1,
        renameRemapBaseCost: 2,
      },
      billing: {
        enabled: true,
        plans: {
          pro_monthly: {
            kind: 'pro_monthly',
            mode: 'subscription',
            priceId: 'price_monthly',
            label: 'Pro Monthly',
            currency: 'usd',
            unitAmount: 1000,
            interval: 'month',
            refillCredits: null,
          },
        },
      },
      limits: { detectMaxPages: 10, fillableMaxPages: 20, savedFormsMax: 5 },
    });
    let rejectCheckout: ((reason?: unknown) => void) | null = null;
    const checkoutPromise = new Promise((_resolve, reject) => {
      rejectCheckout = reject;
    });
    apiServiceMocks.createBillingCheckoutSession.mockReturnValue(checkoutPromise);
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('open-profile'));
    expect(await screen.findByTestId('profile-page')).toBeTruthy();

    fireEvent.click(screen.getByTestId('profile-start-monthly'));
    await waitFor(() => {
      expect(apiServiceMocks.createBillingCheckoutSession).toHaveBeenCalledWith('pro_monthly');
    });
    expect(screen.getByTestId('billing-kind').textContent).toBe('pro_monthly');

    await act(async () => {
      rejectCheckout?.(new Error('checkout down'));
    });
    const checkoutAlert = await screen.findByRole('alert');
    expect(checkoutAlert.textContent || '').toContain('checkout down');
    await waitFor(() => {
      expect(screen.getByTestId('billing-kind').textContent).toBe('idle');
    });
  });

  it('keeps cancel state active until profile refresh resolves', async () => {
    const profilePayload = {
      email: 'qa@example.com',
      role: 'pro',
      creditsRemaining: 10,
      availableCredits: 10,
      monthlyCreditsRemaining: 10,
      refillCreditsRemaining: 0,
      refillCreditsLocked: false,
      creditPricing: {
        pageBucketSize: 5,
        renameBaseCost: 1,
        remapBaseCost: 1,
        renameRemapBaseCost: 2,
      },
      billing: {
        enabled: true,
        hasSubscription: true,
        plans: {
          pro_monthly: {
            kind: 'pro_monthly',
            mode: 'subscription',
            priceId: 'price_monthly',
            label: 'Pro Monthly',
            currency: 'usd',
            unitAmount: 1000,
            interval: 'month',
            refillCredits: null,
          },
        },
      },
      limits: { detectMaxPages: 10, fillableMaxPages: 20, savedFormsMax: 5 },
    };

    let profileCallCount = 0;
    let resolveRefresh: ((value: typeof profilePayload) => void) | null = null;
    const refreshPromise = new Promise<typeof profilePayload>((resolve) => {
      resolveRefresh = resolve;
    });
    apiServiceMocks.getProfile.mockImplementation(() => {
      profileCallCount += 1;
      if (profileCallCount === 1) {
        return Promise.resolve(profilePayload);
      }
      return refreshPromise;
    });
    apiServiceMocks.cancelBillingSubscription.mockResolvedValue({
      success: true,
      subscriptionId: 'sub_123',
      status: 'active',
      cancelAtPeriodEnd: false,
    });

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('open-profile'));
    expect(await screen.findByTestId('profile-page')).toBeTruthy();

    fireEvent.click(screen.getByTestId('profile-cancel-subscription'));
    await waitFor(() => {
      expect(apiServiceMocks.cancelBillingSubscription).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId('billing-cancel').textContent).toBe('true');

    await act(async () => {
      resolveRefresh?.(profilePayload);
    });

    await waitFor(() => {
      expect(screen.getByTestId('billing-cancel').textContent).toBe('false');
    });
  });

  it('shows already-cancelled info when cancellation is already scheduled', async () => {
    const profilePayload = {
      email: 'qa@example.com',
      role: 'pro',
      creditsRemaining: 10,
      availableCredits: 10,
      monthlyCreditsRemaining: 10,
      refillCreditsRemaining: 0,
      refillCreditsLocked: false,
      creditPricing: {
        pageBucketSize: 5,
        renameBaseCost: 1,
        remapBaseCost: 1,
        renameRemapBaseCost: 2,
      },
      billing: {
        enabled: true,
        hasSubscription: true,
        subscriptionStatus: 'active',
        cancelAtPeriodEnd: true,
        cancelAt: 1775000000,
        currentPeriodEnd: 1775000000,
        plans: {
          pro_monthly: {
            kind: 'pro_monthly',
            mode: 'subscription',
            priceId: 'price_monthly',
            label: 'Pro Monthly',
            currency: 'usd',
            unitAmount: 1000,
            interval: 'month',
            refillCredits: null,
          },
        },
      },
      limits: { detectMaxPages: 10, fillableMaxPages: 20, savedFormsMax: 5 },
    };
    apiServiceMocks.getProfile.mockResolvedValue(profilePayload);
    apiServiceMocks.cancelBillingSubscription.mockResolvedValue({
      success: true,
      subscriptionId: 'sub_123',
      status: 'active',
      cancelAtPeriodEnd: true,
      alreadyCanceled: true,
    });

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('open-profile'));
    expect(await screen.findByTestId('profile-page')).toBeTruthy();

    fireEvent.click(screen.getByTestId('profile-cancel-subscription'));

    await waitFor(() => {
      expect(apiServiceMocks.cancelBillingSubscription).not.toHaveBeenCalled();
    });
    expect((await screen.findByRole('alert')).textContent || '').toContain(
      'Subscription is already cancelled for period end.',
    );
  });

  it('shows checkout cancel banner from billing query param and clears it from URL', async () => {
    window.history.replaceState({}, '', '/?billing=cancel');
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    expect((await screen.findByRole('alert')).textContent || '').toContain('Checkout was canceled.');
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('gates save action for signed-out users after loading a fillable PDF', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    fireEvent.click(await screen.findByTestId('upload-fillable'));

    expect(await screen.findByTestId('header-bar')).toBeTruthy();
    fireEvent.click(screen.getByTestId('save-profile'));

    expect((await screen.findByRole('alert')).textContent).toContain('Sign in to save this form to your profile.');
    expect(apiServiceMocks.saveFormToProfile).not.toHaveBeenCalled();
  });

  it('supports undo/redo for field edits in editor history', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    fireEvent.click(await screen.findByTestId('upload-fillable'));

    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toContain('First Name');
    });

    fireEvent.click(screen.getByTestId('rename-first'));
    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toContain('Renamed Name');
    });

    fireEvent.click(screen.getByTestId('undo'));
    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toContain('First Name');
    });

    fireEvent.click(screen.getByTestId('redo'));
    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toContain('Renamed Name');
    });
  });

  it(
    'does not show OpenAI warmup messaging for detection-only uploads',
    async () => {
      const pendingDetection = new Promise<never>(() => {});
      detectionApiMocks.detectFields.mockImplementation(async (_file, options) => {
        options?.onStatus?.({
          status: 'queued',
          detectionProfile: 'light',
          detectionQueuedAt: new Date().toISOString(),
        });
        window.setTimeout(() => {
          options?.onStatus?.({
            status: 'running',
            detectionProfile: 'light',
          });
        }, 50);
        return pendingDetection;
      });
      const App = await importApp();
      const { unmount } = render(<App />);

      await settleAuthAsSignedOut();
      fireEvent.click(await screen.findByTestId('start-workflow'));
      fireEvent.click(await screen.findByTestId('upload-detect'));
      fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));

      expect(await screen.findByText('Waiting for standard CPU to start...')).toBeTruthy();
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 250));
      });
      expect(await screen.findByText('Detecting fields on the standard CPU...')).toBeTruthy();
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 3_100));
      });
      expect(screen.queryByText('Warming up rename detector')).toBeNull();
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 5_100));
      });
      expect(screen.queryByText('Warming up rename detector')).toBeNull();
      expect(await screen.findByText('Detecting fields on the standard CPU...')).toBeTruthy();
      unmount();
    },
    25_000,
  );
});
