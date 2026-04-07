import { useEffect } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const appState = vi.hoisted(() => ({
  authStateCallbacks: new Set<(user: any) => void | Promise<void>>(),
}));

type MatchMediaListener = (event: MediaQueryListEvent) => void;
type MatchMediaState = {
  matches: boolean;
  listeners: Set<MatchMediaListener>;
  legacyListeners: Set<MatchMediaListener>;
};

const originalMatchMedia = window.matchMedia;
const originalFileText = File.prototype.text;
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

const updateMatchMedia = (query: string, matches: boolean) => {
  const state = matchMediaStates.get(query);
  if (!state) {
    throw new Error(`No matchMedia state registered for ${query}`);
  }
  state.matches = matches;
  const event = { matches, media: query } as MediaQueryListEvent;
  state.listeners.forEach((listener) => listener(event));
  state.legacyListeners.forEach((listener) => listener(event));
};

const authMocks = vi.hoisted(() => ({
  onAuthStateChanged: vi.fn((callback: (user: any) => void | Promise<void>) => {
    appState.authStateCallbacks.add(callback);
    return vi.fn(() => {
      appState.authStateCallbacks.delete(callback);
    });
  }),
  signOut: vi.fn().mockResolvedValue(undefined),
}));

const apiServiceMocks = vi.hoisted(() => ({
  ensureBackendReady: vi.fn().mockResolvedValue(undefined),
  getSavedForms: vi.fn().mockResolvedValue([]),
  getGroups: vi.fn().mockResolvedValue([]),
  getGroup: vi.fn(),
  getProfile: vi.fn().mockResolvedValue(null),
  updateDowngradeRetention: vi.fn(),
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
  updateSavedFormEditorSnapshot: vi.fn(),
  loadSavedForm: vi.fn(),
  downloadSavedForm: vi.fn(),
  downloadSessionPdf: vi.fn(),
  deleteSavedForm: vi.fn(),
  touchSession: vi.fn(),
}));

const analyticsMocks = vi.hoisted(() => ({
  trackGoogleAdsBillingPurchase: vi.fn(),
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
      <button data-testid="sign-out" type="button" onClick={() => void props.onSignOut?.()}>
        Sign out
      </button>
    </div>
  )),
  fieldListPanel: vi.fn((props: any) => (
    <div data-testid="field-list-panel">
      <div data-testid="field-list">{props.fields.map((field: any) => field.name).join('|')}</div>
      <div data-testid="display-preset">{props.displayPreset}</div>
      <button data-testid="apply-review-preset" type="button" onClick={() => props.onApplyDisplayPreset?.('review')}>
        Review
      </button>
      <button data-testid="apply-fill-preset" type="button" onClick={() => props.onApplyDisplayPreset?.('fill')}>
        Fill
      </button>
      <button data-testid="toggle-transform" type="button" onClick={() => props.onTransformModeChange?.(true)}>
        Transform
      </button>
      <button data-testid="toggle-fields-off" type="button" onClick={() => props.onShowFieldsChange?.(false)}>
        Fields off
      </button>
    </div>
  )),
  fieldInspector: vi.fn((props: any) => {
    const first = props.fields[0];
    return (
      <div data-testid="field-inspector">
        <div data-testid="active-create-tool">{props.activeCreateTool ?? 'off'}</div>
        <button
          data-testid="activate-text-create-tool"
          type="button"
          onClick={() => props.onCreateToolChange?.('text')}
        >
          Activate text create tool
        </button>
        <button
          data-testid="rename-first"
          type="button"
          onClick={() => props.onUpdateField(first.id, { name: 'Renamed Name' })}
          disabled={!first}
        >
          Rename first
        </button>
        <button data-testid="delete-all" type="button" onClick={() => props.onDeleteAllFields?.()}>
          Delete all
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

vi.mock('../../../src/utils/googleAds', () => ({
  trackGoogleAdsBillingPurchase: analyticsMocks.trackGoogleAdsBillingPurchase,
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
  default: function MockHomepage(props: any) {
    useEffect(() => {
      const timeoutId = window.setTimeout(() => {
        props.onInitialRenderReady?.();
      }, 0);

      return () => {
        window.clearTimeout(timeoutId);
      };
    }, [props.onInitialRenderReady]);

    return (
      <div data-testid="homepage">
        <button data-testid="start-workflow" type="button" onClick={() => props.onStartWorkflow?.()}>
          Start workflow
        </button>
        <button data-testid="start-demo" type="button" onClick={() => props.onStartDemo?.()}>
          Start demo
        </button>
      </div>
    );
  },
}));

vi.mock('../../../src/components/pages/LoginPage', () => ({
  default: (props: any) => (
    <div data-testid="login-page">
      <button data-testid="login-authenticated" type="button" onClick={() => props.onAuthenticated?.()}>
        Authenticated
      </button>
      <button data-testid="login-cancel" type="button" onClick={() => props.onCancel?.()}>
        Cancel
      </button>
    </div>
  ),
}));

vi.mock('../../../src/components/pages/ProfilePage', () => ({
  default: (props: any) => (
    <div data-testid="profile-page">
      <div data-testid="billing-kind">{props.billingCheckoutInProgressKind ?? 'idle'}</div>
      <div data-testid="billing-cancel">{String(Boolean(props.billingCancelInProgress))}</div>
      <div data-testid="profile-allow-open">{String(props.allowSavedFormOpen !== false)}</div>
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
  default: () => null,
  DemoTour: () => null,
}));

vi.mock('../../../src/components/features/FillLinkManagerDialog', () => ({
  default: () => null,
  FillLinkManagerDialog: () => null,
}));

vi.mock('../../../src/components/features/DowngradeRetentionDialog', () => ({
  default: (props: any) => (
    props.open && props.retention ? (
      <div data-testid="retention-dialog">
        <div data-testid="retention-status">{props.retention.status}</div>
        <div data-testid="retention-kept">{(props.retention.keptTemplateIds || []).join('|')}</div>
        <div data-testid="retention-pending">{(props.retention.pendingDeleteTemplateIds || []).join('|')}</div>
        <button data-testid="retention-save" type="button" onClick={() => props.onSaveSelection?.(['tpl-1', 'tpl-2', 'tpl-4'])}>
          Save kept forms
        </button>
        <button data-testid="retention-close" type="button" onClick={() => props.onClose?.()}>
          Keep base plan
        </button>
      </div>
    ) : null
  ),
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
  DialogFrame: ({ open, children }: { open: boolean; children?: any }) => (open ? <div>{children}</div> : null),
  Dialog: ({ open, children }: { open: boolean; children?: any }) => (open ? <div>{children}</div> : null),
  DialogCloseButton: ({ onClick, label = 'Close dialog' }: { onClick?: () => void; label?: string }) => (
    <button type="button" aria-label={label} onClick={() => onClick?.()}>
      Close
    </button>
  ),
  ConfirmDialog: ({ open, confirmLabel = 'Confirm', cancelLabel = 'Cancel', onConfirm, onCancel }: any) => (
    open ? (
      <div data-testid="confirm-dialog">
        <button data-testid="confirm-action" type="button" onClick={() => onConfirm?.()}>
          {confirmLabel}
        </button>
        <button data-testid="confirm-cancel" type="button" onClick={() => onCancel?.()}>
          {cancelLabel}
        </button>
      </div>
    ) : null
  ),
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

const makeSavedFormMeta = (overrides: Record<string, unknown> = {}) => ({
  name: 'Saved Form.pdf',
  fillRules: {
    version: 1,
    checkboxRules: [],
    textTransformRules: [],
  },
  editorSnapshot: {
    version: 1,
    pageCount: 1,
    pageSizes: {
      '1': { width: 612, height: 792 },
    },
    fields: [makeField()],
    hasRenamedFields: false,
    hasMappedSchema: false,
  },
  ...overrides,
});

const defaultBillingReconcilePayload = {
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
};

const makeAuthUser = () => ({
  uid: 'user-1',
  email: 'qa@example.com',
  emailVerified: true,
  providerData: [{ providerId: 'password' }],
  getIdTokenResult: vi.fn().mockResolvedValue({
    token: 'token-1',
    signInProvider: 'password',
  }),
});

const makeRetentionProfile = (overrides: Record<string, unknown> = {}) => ({
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
  retention: {
    status: 'grace_period',
    policyVersion: 2,
    downgradedAt: '2026-03-01T00:00:00Z',
    graceEndsAt: null,
    daysRemaining: 0,
    savedFormsLimit: 3,
    keptTemplateIds: ['tpl-1', 'tpl-2', 'tpl-3'],
    pendingDeleteTemplateIds: ['tpl-4'],
    pendingDeleteLinkIds: ['link-4'],
    accessibleTemplateIds: ['tpl-1', 'tpl-2', 'tpl-3'],
    lockedTemplateIds: ['tpl-4'],
    lockedLinkIds: ['link-4'],
    selectionMode: 'oldest_created',
    manualSelectionAllowed: false,
    counts: {
      keptTemplates: 3,
      pendingTemplates: 1,
      affectedGroups: 1,
      pendingLinks: 1,
      closedLinks: 1,
    },
    templates: [
      { id: 'tpl-1', name: 'Template One', createdAt: '2026-01-01T00:00:00Z', status: 'kept', accessStatus: 'accessible' },
      { id: 'tpl-2', name: 'Template Two', createdAt: '2026-01-02T00:00:00Z', status: 'kept', accessStatus: 'accessible' },
      { id: 'tpl-3', name: 'Template Three', createdAt: '2026-01-03T00:00:00Z', status: 'kept', accessStatus: 'accessible' },
      { id: 'tpl-4', name: 'Template Four', createdAt: '2026-01-04T00:00:00Z', status: 'pending_delete', accessStatus: 'locked', locked: true },
    ],
    groups: [
      {
        id: 'group-1',
        name: 'Admissions Packet',
        templateCount: 4,
        pendingTemplateCount: 1,
        willDelete: false,
        accessStatus: 'locked',
        locked: true,
        lockedTemplateIds: ['tpl-4'],
      },
    ],
    links: [
      {
        id: 'link-4',
        title: 'Template Four Link',
        scopeType: 'template',
        status: 'closed',
        templateId: 'tpl-4',
        pendingDeleteReason: 'template_pending_delete',
        accessStatus: 'locked',
        locked: true,
      },
    ],
  },
  limits: {
    detectMaxPages: 10,
    fillableMaxPages: 20,
    savedFormsMax: 3,
    fillLinkResponsesMonthlyMax: 25,
  },
  ...overrides,
});

const importApp = async () => {
  const module = await import('../../../src/App');
  return module.default;
};

const settleAuthAsSignedOut = async () => {
  await waitFor(() => {
    expect(appState.authStateCallbacks.size).toBeGreaterThan(0);
  });
  await act(async () => {
    for (const callback of [...appState.authStateCallbacks]) {
      await callback(null);
    }
  });
};

const settleAuthAsSignedIn = async () => {
  await waitFor(() => {
    expect(appState.authStateCallbacks.size).toBeGreaterThan(0);
  });
  await act(async () => {
    for (const callback of [...appState.authStateCallbacks]) {
      await callback(makeAuthUser());
    }
  });
};

const openFillableWorkspace = async () => {
  fireEvent.click(await screen.findByTestId('start-workflow'));
  await screen.findByTestId('upload-detect', {}, { timeout: 10_000 });
  fireEvent.click(await screen.findByTestId('upload-fillable'));
};

describe('App', () => {
  beforeEach(() => {
    installMatchMedia({
      '(max-width: 900px)': false,
    });
    if (typeof File.prototype.text !== 'function') {
      Object.defineProperty(File.prototype, 'text', {
        configurable: true,
        value: function text(this: Blob) {
          return new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(reader.error || new Error('Failed to read File text.'));
            reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
            reader.readAsText(this);
          });
        },
      });
    }
    window.history.replaceState({}, '', '/');
    window.scrollTo = vi.fn();
    window.sessionStorage.clear();
    document.documentElement.classList.remove('workspace-no-scroll');
    document.body.classList.remove('workspace-no-scroll');
    document.getElementById('root')?.classList.remove('workspace-no-scroll');
    appState.authStateCallbacks.clear();
    authMocks.onAuthStateChanged.mockClear();
    authMocks.signOut.mockReset().mockResolvedValue(undefined);
    analyticsMocks.trackGoogleAdsBillingPurchase.mockClear();
    apiServiceMocks.ensureBackendReady.mockReset().mockResolvedValue(undefined);
    apiServiceMocks.getSavedForms.mockReset().mockResolvedValue([]);
    apiServiceMocks.getGroups.mockReset().mockResolvedValue([]);
    apiServiceMocks.getGroup.mockReset();
    apiServiceMocks.getProfile.mockReset().mockResolvedValue(null);
    apiServiceMocks.updateDowngradeRetention.mockReset();
    apiServiceMocks.createBillingCheckoutSession.mockReset();
    apiServiceMocks.reconcileBillingCheckoutFulfillment.mockReset().mockResolvedValue(defaultBillingReconcilePayload);
    apiServiceMocks.cancelBillingSubscription.mockReset();
    apiServiceMocks.createTemplateSession.mockReset().mockResolvedValue({ success: true, sessionId: 'session-1', fieldCount: 1 });
    apiServiceMocks.materializeFormPdf.mockReset().mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
    apiServiceMocks.saveFormToProfile.mockReset().mockResolvedValue({ success: true, id: 'saved-1' });
    apiServiceMocks.createSchema.mockReset();
    apiServiceMocks.renameFields.mockReset();
    apiServiceMocks.mapSchema.mockReset();
    apiServiceMocks.createSavedFormSession.mockReset();
    apiServiceMocks.updateSavedFormEditorSnapshot.mockReset();
    apiServiceMocks.loadSavedForm.mockReset();
    apiServiceMocks.downloadSavedForm.mockReset();
    apiServiceMocks.downloadSessionPdf.mockReset();
    apiServiceMocks.deleteSavedForm.mockReset();
    apiServiceMocks.touchSession.mockReset();
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
    vi.useRealTimers();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    if (typeof originalFileText === 'function') {
      Object.defineProperty(File.prototype, 'text', {
        configurable: true,
        value: originalFileText,
      });
    } else {
      delete (File.prototype as File & { text?: unknown }).text;
    }
    window.matchMedia = originalMatchMedia;
  });

  it('shows auth loading state until auth callback settles', async () => {
    const App = await importApp();
    render(<App />);

    expect(document.querySelector('.homepage-loading-overlay')).toBeTruthy();
    expect(authMocks.onAuthStateChanged).toHaveBeenCalledTimes(1);
  });

  it('removes the homepage splash once the landing page reports ready', async () => {
    const App = await importApp();
    render(<App />);

    expect(document.querySelector('.homepage-loading-overlay')).toBeTruthy();
    expect(await screen.findByTestId('homepage')).toBeTruthy();
    await waitFor(() => {
      expect(document.querySelector('.homepage-loading-overlay')).toBeNull();
    });
  });

  it('routes signed-out users to sign-in when they start workflow from homepage', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    fireEvent.click(screen.getByTestId('start-workflow'));

    expect(await screen.findByTestId('login-page', {}, { timeout: 10_000 })).toBeTruthy();
  }, 30_000);

  it('keeps routing signed-out users to sign-in from runtime homepage after canceling login', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    expect(await screen.findByTestId('login-page', {}, { timeout: 10_000 })).toBeTruthy();

    fireEvent.click(screen.getByTestId('login-cancel'));
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    fireEvent.click(screen.getByTestId('start-workflow'));
    expect(await screen.findByTestId('login-page', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.queryByTestId('upload-detect')).toBeNull();
  }, 30_000);

  it('releases workspace scroll lock when mobile users back out of the runtime login shell', async () => {
    installMatchMedia({
      '(max-width: 900px)': true,
    });

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    expect(await screen.findByTestId('login-page', {}, { timeout: 10_000 })).toBeTruthy();

    await waitFor(() => {
      expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
      expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);
    });

    fireEvent.click(screen.getByTestId('login-cancel'));
    expect(await screen.findByTestId('homepage')).toBeTruthy();
    expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
    expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);
  }, 15_000);

  it('transitions from homepage to upload view via start workflow for signed-in users', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    fireEvent.click(screen.getByTestId('start-workflow'));

    expect(await screen.findByTestId('upload-detect', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.getByTestId('upload-fillable')).toBeTruthy();
    expect(window.location.pathname).toBe('/upload');
  }, 15_000);

  it('keeps direct workflow routes on the homepage shell below the 900px breakpoint', async () => {
    installMatchMedia({
      '(max-width: 900px)': true,
    });
    window.history.replaceState({}, '', '/upload');

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'upload-root' }} />);

    await settleAuthAsSignedIn();

    expect(await screen.findByTestId('homepage', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.queryByTestId('upload-detect')).toBeNull();
    expect(window.location.pathname).toBe('/');
    expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
    expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);
  }, 15_000);

  it('falls back to the homepage when the live editor shrinks below the 900px breakpoint', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    await openFillableWorkspace();
    expect(await screen.findByTestId('field-list', {}, { timeout: 10_000 })).toBeTruthy();

    await act(async () => {
      updateMatchMedia('(max-width: 900px)', true);
    });

    expect(await screen.findByTestId('homepage', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.queryByTestId('field-list')).toBeNull();
    expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
    expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);
  }, 15_000);

  it('keeps the anonymous demo in the editor instead of tripping the redirect guard', async () => {
    const pdfBytes = '%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF';
    const demoFields = JSON.stringify([
      {
        id: 'demo-field-1',
        name: 'patient_name',
        type: 'text',
        page: 1,
        rect: [10, 10, 110, 30],
      },
    ]);
    const demoNameMap = JSON.stringify({ patient_name: 'patient_name' });
    const makeFetchResponse = (body: string, contentType: string, status = 200) => ({
      ok: status >= 200 && status < 300,
      status,
      blob: async () => new Blob([body], { type: contentType }),
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/demo/new_patient_forms_1915ccb015.pdf')) {
        return makeFetchResponse(pdfBytes, 'application/pdf');
      }
      if (url.includes('/demo/generated/baseFieldDetections.fields.json')) {
        return makeFetchResponse(demoFields, 'application/json');
      }
      if (
        url.includes('/demo/generated/baseToOpenAiRenameNameMap.json')
        || url.includes('/demo/generated/baseToOpenAiRemapNameMap.json')
      ) {
        return makeFetchResponse(demoNameMap, 'application/json');
      }
      if (url.includes('/demo/new_patient_forms_1915ccb015_mock.csv')) {
        return makeFetchResponse('patient_name\nJustin Thakral\n', 'text/csv');
      }
      return makeFetchResponse('not found', 'text/plain', 404);
    });
    vi.stubGlobal('fetch', fetchMock);

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    fireEvent.click(screen.getByTestId('start-demo'));

    expect(await screen.findByTestId('field-list', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.queryByText('Redirecting…')).toBeNull();
    expect(screen.queryByTestId('login-page')).toBeNull();
    await waitFor(() => {
      const lastHeaderBarProps = uiMocks.headerBar.mock.calls.at(-1)?.[0];
      expect(lastHeaderBarProps?.canDownload).toBe(true);
    });
  }, 15_000);

  it('keeps hidden schema picker inputs labeled for accessibility', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    expect(await screen.findByTestId('upload-detect', {}, { timeout: 10_000 })).toBeTruthy();

    expect(document.getElementById('csv-file-input')?.getAttribute('aria-label')).toBe('Upload CSV schema file');
    expect(document.getElementById('excel-file-input')?.getAttribute('aria-label')).toBe('Upload Excel schema file');
    expect(document.getElementById('json-file-input')?.getAttribute('aria-label')).toBe('Upload JSON schema file');
    expect(document.getElementById('txt-file-input')?.getAttribute('aria-label')).toBe('Upload TXT schema file');
  }, 15_000);

  it('restores a saved form directly from a /ui/forms route, reuses the matching resume session, and avoids duplicate restore fetches', async () => {
    window.history.replaceState({}, '', '/ui/forms/saved-1');
    window.sessionStorage.setItem(
      'dullypdf.workspaceResumeState',
      JSON.stringify({
        version: 1,
        userId: 'user-1',
        route: { kind: 'saved-form', formId: 'saved-1' },
        currentPage: 1,
        scale: 1.35,
        detectSessionId: 'resume-session-1',
        mappingSessionId: 'resume-session-1',
        fieldCount: 1,
        pageCount: 1,
        updatedAtMs: Date.now(),
      }),
    );
    apiServiceMocks.loadSavedForm.mockResolvedValue(makeSavedFormMeta());
    apiServiceMocks.downloadSavedForm.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
    apiServiceMocks.touchSession.mockResolvedValue({ success: true, sessionId: 'resume-session-1' });

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'saved-form', formId: 'saved-1' }} />);

    await settleAuthAsSignedIn();
    expect(await screen.findByTestId('field-list', {}, { timeout: 10_000 })).toBeTruthy();

    await waitFor(() => {
      expect(apiServiceMocks.loadSavedForm).toHaveBeenCalledWith('saved-1');
    });
    await waitFor(() => {
      expect(apiServiceMocks.touchSession).toHaveBeenCalledWith('resume-session-1');
    });
    expect(apiServiceMocks.loadSavedForm).toHaveBeenCalledTimes(1);
    expect(apiServiceMocks.downloadSavedForm).toHaveBeenCalledTimes(1);
    expect(apiServiceMocks.createSavedFormSession).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/ui/forms/saved-1');
    expect(await screen.findByTestId('field-list')).toBeTruthy();
  });

  it('restores a session-backed /ui workspace after reload instead of dropping back to /upload', async () => {
    window.history.replaceState({}, '', '/ui');
    window.sessionStorage.setItem(
      'dullypdf.workspaceResumeState',
      JSON.stringify({
        version: 1,
        userId: 'user-1',
        route: { kind: 'ui-root' },
        currentPage: 1,
        scale: 1.2,
        detectSessionId: 'resume-ui-session-1',
        mappingSessionId: 'resume-ui-session-1',
        fieldCount: 1,
        pageCount: 1,
        updatedAtMs: Date.now(),
      }),
    );
    detectionApiMocks.fetchDetectionStatus.mockResolvedValue({
      sessionId: 'resume-ui-session-1',
      status: 'complete',
      sourcePdf: 'Recovered Upload.pdf',
      pageCount: 1,
      fields: [{
        name: 'mapped_name',
        type: 'text',
        page: 1,
        rect: [10, 10, 90, 22],
        mappingConfidence: 0.9,
      }],
      checkboxRules: [{ databaseField: 'accept_terms', groupKey: 'accept_terms' }],
      textTransformRules: [{ targetField: 'mapped_name', operation: 'copy', sources: ['full_name'] }],
    });
    apiServiceMocks.downloadSessionPdf.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'ui-root' }} />);

    await settleAuthAsSignedIn();
    expect(await screen.findByTestId('field-list', {}, { timeout: 10_000 })).toBeTruthy();

    await waitFor(() => {
      expect(detectionApiMocks.fetchDetectionStatus).toHaveBeenCalledWith('resume-ui-session-1');
    });
    await waitFor(() => {
      expect(apiServiceMocks.downloadSessionPdf).toHaveBeenCalledWith('resume-ui-session-1');
    });
    expect(apiServiceMocks.downloadSessionPdf).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe('/ui');
    expect(screen.getByTestId('field-list').textContent).toContain('mapped_name');
  }, 30_000);

  it('restores a saved group directly from a /ui/groups route and opens the requested template first', async () => {
    window.history.replaceState({}, '', '/ui/groups/group-1?template=saved-2');
    window.sessionStorage.setItem(
      'dullypdf.workspaceResumeState',
      JSON.stringify({
        version: 1,
        userId: 'user-1',
        route: { kind: 'group', groupId: 'group-1', templateId: 'saved-2' },
        currentPage: 1,
        scale: 1.1,
        detectSessionId: 'group-resume-session',
        mappingSessionId: 'group-resume-session',
        fieldCount: 1,
        pageCount: 1,
        updatedAtMs: Date.now(),
      }),
    );
    apiServiceMocks.getSavedForms.mockResolvedValue([
      { id: 'saved-1', name: 'Alpha.pdf', createdAt: '2026-03-17T00:00:00Z' },
      { id: 'saved-2', name: 'Bravo.pdf', createdAt: '2026-03-17T00:00:00Z' },
    ]);
    apiServiceMocks.getGroups.mockResolvedValue([
      {
        id: 'group-1',
        name: 'Resume Group',
        templateIds: ['saved-1', 'saved-2'],
        templateCount: 2,
        templates: [
          { id: 'saved-1', name: 'Alpha.pdf', createdAt: '2026-03-17T00:00:00Z' },
          { id: 'saved-2', name: 'Bravo.pdf', createdAt: '2026-03-17T00:00:00Z' },
        ],
      },
    ]);
    apiServiceMocks.loadSavedForm.mockResolvedValue(makeSavedFormMeta({ name: 'Bravo.pdf' }));
    apiServiceMocks.downloadSavedForm.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
    apiServiceMocks.touchSession.mockResolvedValue({ success: true, sessionId: 'group-resume-session' });

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'group', groupId: 'group-1', templateId: 'saved-2' }} />);

    await settleAuthAsSignedIn();
    expect(await screen.findByTestId('field-list', {}, { timeout: 10_000 })).toBeTruthy();

    await waitFor(() => {
      expect(apiServiceMocks.loadSavedForm).toHaveBeenCalledWith('saved-2');
    });
    await waitFor(() => {
      expect(apiServiceMocks.touchSession).toHaveBeenCalledWith('group-resume-session');
    });
    expect(apiServiceMocks.loadSavedForm.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(apiServiceMocks.loadSavedForm.mock.calls[0]?.[0]).toBe('saved-2');
    expect(
      apiServiceMocks.loadSavedForm.mock.calls.every((call) => ['saved-1', 'saved-2'].includes(call[0])),
    ).toBe(true);
    expect(apiServiceMocks.downloadSavedForm.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(apiServiceMocks.downloadSavedForm.mock.calls[0]?.[0]).toBe('saved-2');
    expect(
      apiServiceMocks.downloadSavedForm.mock.calls.every((call) => ['saved-1', 'saved-2'].includes(call[0])),
    ).toBe(true);
    expect(apiServiceMocks.createSavedFormSession).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/ui/groups/group-1');
    expect(window.location.search).toBe('?template=saved-2');
  });

  it('shows a backend startup screen before mounting the signed-in runtime', async () => {
    let releaseBackendStartup: (() => void) | null = null;
    apiServiceMocks.ensureBackendReady.mockImplementationOnce(() => new Promise<void>((resolve) => {
      releaseBackendStartup = resolve;
    }));

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('start-workflow'));

    expect(await screen.findByText('Loading workspace…')).toBeTruthy();
    expect(screen.queryByTestId('legacy-header')).toBeNull();
    expect(screen.queryByTestId('header-bar')).toBeNull();
    expect(screen.queryByTestId('upload-detect')).toBeNull();

    await act(async () => {
      releaseBackendStartup?.();
    });

    expect(await screen.findByTestId('upload-detect', {}, { timeout: 10_000 })).toBeTruthy();
    expect(apiServiceMocks.ensureBackendReady).toHaveBeenCalledTimes(1);
  }, 15_000);

  it('keeps direct workspace routes on the loading screen until the runtime is ready', async () => {
    let releaseBackendStartup: (() => void) | null = null;
    apiServiceMocks.ensureBackendReady.mockImplementationOnce(() => new Promise<void>((resolve) => {
      releaseBackendStartup = resolve;
    }));
    window.history.replaceState({}, '', '/upload');

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'upload-root' }} />);

    await settleAuthAsSignedIn();

    expect(await screen.findByText('Loading workspace…')).toBeTruthy();
    expect(screen.queryByTestId('legacy-header')).toBeNull();
    expect(screen.queryByTestId('header-bar')).toBeNull();
    expect(screen.queryByTestId('homepage')).toBeNull();
    expect(screen.queryByTestId('upload-detect')).toBeNull();

    await act(async () => {
      releaseBackendStartup?.();
    });

    expect(await screen.findByTestId('upload-detect', {}, { timeout: 10_000 })).toBeTruthy();
    expect(apiServiceMocks.ensureBackendReady).toHaveBeenCalledTimes(1);
  }, 15_000);

  it('locks root scrolling while the workspace runtime is mounted', async () => {
    const App = await importApp();
    const { unmount } = render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    expect(await screen.findByTestId('upload-detect', {}, { timeout: 10_000 })).toBeTruthy();

    expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(true);
    expect(document.body.classList.contains('workspace-no-scroll')).toBe(true);

    unmount();

    expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
    expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);
  }, 15_000);

  it('keeps mobile profile saved-form reopening disabled and returns home without scroll lock', async () => {
    installMatchMedia({
      '(max-width: 900px)': true,
    });

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('open-profile'));

    expect(await screen.findByTestId('profile-page', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.getByTestId('profile-allow-open').textContent).toBe('false');
    expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
    expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);

    fireEvent.click(screen.getByTestId('profile-close'));
    expect(await screen.findByTestId('homepage')).toBeTruthy();
    await waitFor(() => {
      expect(document.documentElement.classList.contains('workspace-no-scroll')).toBe(false);
      expect(document.body.classList.contains('workspace-no-scroll')).toBe(false);
    });
  }, 15_000);

  it('keeps desktop profile saved-form reopening enabled', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('open-profile'));

    expect(await screen.findByTestId('profile-page', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.getByTestId('profile-allow-open').textContent).toBe('true');
  }, 15_000);

  it('does not register duplicate auth listeners after signed-in state updates', async () => {
    const App = await importApp();
    render(<App />);

    expect(authMocks.onAuthStateChanged).toHaveBeenCalledTimes(1);

    const user = makeAuthUser();
    await act(async () => {
      for (const callback of [...appState.authStateCallbacks]) {
        await callback(user);
      }
    });

    await waitFor(() => {
      expect(authMocks.onAuthStateChanged).toHaveBeenCalledTimes(1);
    });
  });

  it('keeps the signed-in homepage shell idle until the user launches the runtime', async () => {
    apiServiceMocks.getProfile.mockResolvedValue(makeRetentionProfile());

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    await act(async () => {
      await Promise.resolve();
    });

    expect(apiServiceMocks.ensureBackendReady).not.toHaveBeenCalled();
    expect(apiServiceMocks.getProfile).not.toHaveBeenCalled();
    expect(apiServiceMocks.getSavedForms).not.toHaveBeenCalled();
    expect(apiServiceMocks.getGroups).not.toHaveBeenCalled();
    expect(screen.queryByTestId('retention-dialog')).toBeNull();
  });

  it('shows the retention dialog after a signed-in downgraded user launches the workspace', async () => {
    apiServiceMocks.getProfile.mockResolvedValue(makeRetentionProfile());

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    expect(await screen.findByTestId('homepage')).toBeTruthy();

    fireEvent.click(screen.getByTestId('start-workflow'));

    expect(await screen.findByTestId('retention-dialog', {}, { timeout: 10_000 })).toBeTruthy();
    expect(screen.getByTestId('retention-status').textContent).toBe('grace_period');
    expect(apiServiceMocks.getProfile).toHaveBeenCalled();
  }, 15_000);

  it('keeps retention UI fresh after saving a new kept-template selection', async () => {
    const initialProfile = makeRetentionProfile();
    const updatedRetention = {
      ...(initialProfile.retention as Record<string, unknown>),
      keptTemplateIds: ['tpl-1', 'tpl-2', 'tpl-4'],
      pendingDeleteTemplateIds: ['tpl-3'],
    };
    apiServiceMocks.getProfile
      .mockResolvedValueOnce(initialProfile)
      .mockResolvedValueOnce({
        ...initialProfile,
        retention: updatedRetention,
      });
    apiServiceMocks.updateDowngradeRetention.mockResolvedValue(updatedRetention);

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    fireEvent.click(await screen.findByTestId('start-workflow'));
    expect(await screen.findByTestId('retention-dialog', {}, { timeout: 10_000 })).toBeTruthy();

    fireEvent.click(screen.getByTestId('retention-save'));

    await waitFor(() => {
      expect(apiServiceMocks.updateDowngradeRetention).toHaveBeenCalledWith(['tpl-1', 'tpl-2', 'tpl-4']);
    });
    await waitFor(() => {
      expect(screen.getByTestId('retention-kept').textContent).toBe('tpl-1|tpl-2|tpl-4');
      expect(screen.getByTestId('retention-pending').textContent).toBe('tpl-3');
    });
  }, 15_000);

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
    const openProfileButton = await screen.findByTestId('open-profile');
    await waitFor(() => {
      expect((openProfileButton as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(openProfileButton);
    expect(await screen.findByTestId('profile-page', {}, { timeout: 10_000 })).toBeTruthy();

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
  }, 15_000);

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

    let refreshArmed = false;
    let resolveRefresh: ((value: typeof profilePayload) => void) | null = null;
    const refreshPromise = new Promise<typeof profilePayload>((resolve) => {
      resolveRefresh = resolve;
    });
    apiServiceMocks.getProfile.mockImplementation(() => {
      if (!refreshArmed) {
        return Promise.resolve(profilePayload);
      }
      return refreshPromise;
    });
    apiServiceMocks.cancelBillingSubscription.mockImplementation(async () => {
      refreshArmed = true;
      return {
        success: true,
        subscriptionId: 'sub_123',
        status: 'active',
        cancelAtPeriodEnd: false,
      };
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

    await settleAuthAsSignedIn();
    expect((await screen.findByRole('alert')).textContent || '').toContain('Checkout was canceled.');
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('does not clear an existing pending checkout marker for a billing cancel return', async () => {
    window.history.replaceState({}, '', '/?billing=cancel');
    window.sessionStorage.setItem(
      'dullypdf.pendingBillingCheckout',
      JSON.stringify({
        userId: 'user-1',
        requestedKind: 'pro_monthly',
        sessionId: 'cs_cancel_pending_123',
        attemptId: 'attempt_cancel_pending_123',
        checkoutPriceId: 'price_monthly',
        startedAt: Date.now(),
      }),
    );
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    expect((await screen.findByRole('alert')).textContent || '').toContain('Checkout was canceled.');
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toContain('"sessionId":"cs_cancel_pending_123"');
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('ignores unknown billing query params without mounting the runtime', async () => {
    window.history.replaceState({}, '', '/?billing=foo');
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    expect(await screen.findByTestId('homepage')).toBeTruthy();
    expect(screen.queryByTestId('upload-detect')).toBeNull();
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('keeps signed-out billing success links on the lightweight homepage when no pending checkout exists', async () => {
    window.history.replaceState({}, '', '/?billing=success');
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedOut();
    expect(await screen.findByTestId('homepage')).toBeTruthy();
    expect(screen.queryByTestId('upload-detect')).toBeNull();
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('tracks successful Stripe billing returns against the matched checkout session', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem(
      'dullypdf.pendingBillingCheckout',
      JSON.stringify({
        userId: 'user-1',
        requestedKind: 'pro_yearly',
        sessionId: 'cs_completed_123',
        attemptId: 'attempt_completed_123',
        checkoutPriceId: 'price_monthly',
        startedAt,
      }),
    );
    apiServiceMocks.getProfile.mockResolvedValue({
      email: 'qa@example.com',
      role: 'pro',
      creditsRemaining: 100,
      availableCredits: 100,
      monthlyCreditsRemaining: 100,
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
          pro_yearly: {
            kind: 'pro_yearly',
            mode: 'subscription',
            priceId: 'price_yearly',
            label: 'Pro Yearly',
            currency: 'usd',
            unitAmount: 10000,
            interval: 'year',
            refillCredits: null,
          },
        },
      },
      limits: { detectMaxPages: 10, fillableMaxPages: 20, savedFormsMax: 5 },
    });
    apiServiceMocks.reconcileBillingCheckoutFulfillment.mockResolvedValue({
      success: true,
      dryRun: false,
      scope: 'self',
      auditedEventCount: 1,
      candidateEventCount: 0,
      pendingReconciliationCount: 0,
      reconciledCount: 0,
      alreadyProcessedCount: 1,
      processingCount: 0,
      retryableCount: 0,
      failedCount: 0,
      invalidCount: 0,
      skippedForUserCount: 0,
      events: [
        {
          eventId: 'evt_completed_123',
          checkoutSessionId: 'cs_completed_123',
          checkoutAttemptId: 'attempt_completed_123',
          checkoutKind: 'pro_monthly',
          checkoutPriceId: 'price_monthly',
          billingEventStatus: 'processed',
        },
      ],
    });

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();

    await waitFor(() => {
      expect(apiServiceMocks.reconcileBillingCheckoutFulfillment).toHaveBeenCalledTimes(1);
      expect(apiServiceMocks.reconcileBillingCheckoutFulfillment).toHaveBeenCalledWith({
        lookbackHours: 72,
        dryRun: false,
        sessionId: 'cs_completed_123',
        attemptId: 'attempt_completed_123',
      });
      expect(analyticsMocks.trackGoogleAdsBillingPurchase).toHaveBeenCalledWith({
        kind: 'pro_monthly',
        transactionId: 'cs_completed_123',
        value: 10,
        currency: 'usd',
      });
    });
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toBeNull();
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('does not reconcile or clear storage for billing success until a verified user exists', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem(
      'dullypdf.pendingBillingCheckout',
      JSON.stringify({
        userId: 'user-1',
        requestedKind: 'pro_monthly',
        sessionId: 'cs_wait_123',
        attemptId: 'attempt_wait_123',
        checkoutPriceId: 'price_monthly',
        startedAt,
      }),
    );

    const unverifiedUser = {
      email: 'qa@example.com',
      emailVerified: false,
      providerData: [{ providerId: 'password' }],
      getIdTokenResult: vi.fn().mockResolvedValue({
        token: 'token-1',
        signInProvider: 'password',
      }),
    };
    apiServiceMocks.getProfile.mockResolvedValue({
      email: 'qa@example.com',
      role: 'pro',
      creditsRemaining: 100,
      availableCredits: 100,
      monthlyCreditsRemaining: 100,
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
    });

    const App = await importApp();
    render(<App />);

    await waitFor(() => {
      expect(appState.authStateCallbacks.size).toBeGreaterThan(0);
    });
    await act(async () => {
      for (const callback of [...appState.authStateCallbacks]) {
        await callback(unverifiedUser);
      }
    });

    await waitFor(() => {
      expect(screen.getByTestId('verify-page')).toBeTruthy();
    });
    expect(apiServiceMocks.reconcileBillingCheckoutFulfillment).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).not.toBeNull();
    expect(window.location.search).toContain('billing=success');
  });

  it('keeps the pending checkout marker and avoids a success banner when billing confirmation is still pending', async () => {
    const startedAt = Date.now();
    window.history.replaceState({}, '', '/?billing=success');
    window.sessionStorage.setItem(
      'dullypdf.pendingBillingCheckout',
      JSON.stringify({
        userId: 'user-1',
        requestedKind: 'pro_monthly',
        sessionId: 'cs_pending_confirm_123',
        attemptId: 'attempt_pending_confirm_123',
        checkoutPriceId: 'price_monthly',
        startedAt,
      }),
    );
    apiServiceMocks.getProfile.mockResolvedValue({
      email: 'qa@example.com',
      role: 'pro',
      creditsRemaining: 100,
      availableCredits: 100,
      monthlyCreditsRemaining: 100,
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
    });
    apiServiceMocks.reconcileBillingCheckoutFulfillment.mockResolvedValue({
      success: true,
      dryRun: false,
      scope: 'self',
      auditedEventCount: 1,
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
    });

    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();

    await waitFor(() => {
      expect(apiServiceMocks.reconcileBillingCheckoutFulfillment).toHaveBeenCalledTimes(1);
    });
    expect((await screen.findByRole('alert')).textContent || '').toContain('could not be confirmed yet');
    expect(window.sessionStorage.getItem('dullypdf.pendingBillingCheckout')).toContain('"sessionId":"cs_pending_confirm_123"');
    expect(window.location.search.includes('billing=')).toBe(false);
  });

  it('returns the editor to the homepage after auth transitions to signed-out', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    await openFillableWorkspace();

    expect(await screen.findByTestId('header-bar')).toBeTruthy();
    await settleAuthAsSignedOut();
    expect(await screen.findByTestId('homepage')).toBeTruthy();
    expect(screen.queryByTestId('save-profile')).toBeNull();
    expect(document.querySelector('.auth-loading-screen')).toBeNull();
    expect(window.location.pathname).toBe('/');
    expect(apiServiceMocks.saveFormToProfile).not.toHaveBeenCalled();
  }, 15_000);

  it('skips the blank homepage splash when signing out from the live editor', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    await openFillableWorkspace();

    fireEvent.click(await screen.findByTestId('sign-out'));

    expect(await screen.findByTestId('homepage')).toBeTruthy();
    await waitFor(() => {
      expect(document.querySelector('.homepage-loading-overlay')).toBeNull();
    });
    expect(authMocks.signOut).toHaveBeenCalledTimes(1);
  }, 15_000);

  it('supports undo/redo for field edits in editor history', async () => {
    window.history.replaceState({}, '', '/ui/forms/saved-1');
    apiServiceMocks.loadSavedForm.mockResolvedValue(makeSavedFormMeta());
    apiServiceMocks.downloadSavedForm.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'saved-form', formId: 'saved-1' }} />);

    await settleAuthAsSignedIn();

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

  it('supports bulk field deletion as one undoable editor history action', async () => {
    window.history.replaceState({}, '', '/ui/forms/saved-1');
    apiServiceMocks.loadSavedForm.mockResolvedValue(makeSavedFormMeta());
    apiServiceMocks.downloadSavedForm.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));

    const App = await importApp();
    render(<App initialBrowserRoute={{ kind: 'saved-form', formId: 'saved-1' }} />);

    await settleAuthAsSignedIn();

    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toContain('First Name');
    });

    fireEvent.click(screen.getByTestId('delete-all'));
    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toBe('');
    });

    fireEvent.click(screen.getByTestId('undo'));
    await waitFor(() => {
      expect(screen.getByTestId('field-list').textContent).toContain('First Name');
    });
  });

  it('clears the active create tool when transform mode is enabled', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    await openFillableWorkspace();

    await waitFor(() => {
      expect(screen.getByTestId('display-preset').textContent).toBe('edit');
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });

    await act(async () => {
      await Promise.resolve();
    });

    fireEvent.click(await screen.findByTestId('apply-review-preset'));
    await waitFor(() => {
      expect(screen.getByTestId('display-preset').textContent).toBe('review');
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });

    fireEvent.keyDown(window, { key: 't' });
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('text');
    });

    fireEvent.click(await screen.findByTestId('toggle-transform'));
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });
  });

  it('clears the active create tool when review or fill modes replace editor creation state', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    await openFillableWorkspace();
    await waitFor(() => {
      expect(screen.getByTestId('display-preset').textContent).toBe('edit');
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });

    fireEvent.keyDown(window, { key: 't' });
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('text');
    });

    fireEvent.click(await screen.findByTestId('apply-review-preset'));
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });

    fireEvent.click(await screen.findByTestId('activate-text-create-tool'));
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('text');
    });

    fireEvent.click(await screen.findByTestId('apply-fill-preset'));
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });
  });

  it('clears the active create tool when field overlays are hidden', async () => {
    const App = await importApp();
    render(<App />);

    await settleAuthAsSignedIn();
    await openFillableWorkspace();
    await waitFor(() => {
      expect(screen.getByTestId('display-preset').textContent).toBe('edit');
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
    });

    fireEvent.keyDown(window, { key: 't' });
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('text');
    });

    fireEvent.click(await screen.findByTestId('toggle-fields-off'));
    await waitFor(() => {
      expect(screen.getByTestId('active-create-tool').textContent).toBe('off');
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
          detectionServiceUrl: 'https://dullypdf-detector-light-abc.a.run.app',
        });
        window.setTimeout(() => {
          options?.onStatus?.({
            status: 'running',
            detectionProfile: 'light',
            detectionServiceUrl: 'https://dullypdf-detector-light-abc.a.run.app',
          });
        }, 50);
        return pendingDetection;
      });
      const App = await importApp();
      const { unmount } = render(<App />);

      await settleAuthAsSignedIn();
      fireEvent.click(await screen.findByTestId('start-workflow'));
      fireEvent.click(await screen.findByTestId('upload-detect'));
      fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));

      await waitFor(() => {
        expect(
          screen.queryByText('Waiting for standard CPU to start...') ||
          screen.queryByText('Detecting fields on the standard CPU...')
        ).toBeTruthy();
      });
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

  it(
    'shows GPU detection messaging when the active detector service is GPU-backed',
    async () => {
      const pendingDetection = new Promise<never>(() => {});
      detectionApiMocks.detectFields.mockImplementation(async (_file, options) => {
        options?.onStatus?.({
          status: 'queued',
          detectionProfile: 'light',
          detectionQueuedAt: new Date().toISOString(),
          detectionServiceUrl: 'https://dullypdf-detector-light-gpu-abc.a.run.app',
        });
        window.setTimeout(() => {
          options?.onStatus?.({
            status: 'running',
            detectionProfile: 'light',
            detectionServiceUrl: 'https://dullypdf-detector-light-gpu-abc.a.run.app',
          });
        }, 50);
        return pendingDetection;
      });
      const App = await importApp();
      const { unmount } = render(<App />);

      await settleAuthAsSignedIn();
      fireEvent.click(await screen.findByTestId('start-workflow'));
      fireEvent.click(await screen.findByTestId('upload-detect'));
      fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));

      expect(await screen.findByText('Waiting for GPU detector to start...')).toBeTruthy();
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 250));
      });
      expect(await screen.findByText('Detecting fields on the GPU...')).toBeTruthy();
      unmount();
    },
    25_000,
  );
});
