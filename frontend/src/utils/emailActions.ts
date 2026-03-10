export const ACCOUNT_ACTION_ROUTE_PATH = '/account-action';
export const LEGACY_ACCOUNT_ACTION_ROUTE_PATH = '/verify-email';
const ACCOUNT_ACTION_HISTORY_KEY = 'dullypdfAccountAction';
const LEGACY_ACCOUNT_ACTION_HISTORY_KEY = 'dullypdfVerifyEmailAction';

export type SupportedEmailActionMode = 'verifyEmail' | 'resetPassword';

export type ParsedEmailAction =
  | {
      status: 'ready';
      mode: SupportedEmailActionMode;
      oobCode: string;
      continuePath: string;
    }
  | {
      status: 'invalid';
      reason: 'unsupported-mode' | 'missing-code';
      continuePath: string;
    };

export type StoredEmailActionState =
  | {
      kind: 'result';
      mode: SupportedEmailActionMode;
      status: 'success' | 'error';
      continuePath: string;
    }
  | {
      kind: 'pending-reset-password';
      continuePath: string;
    };

function replaceAccountActionHistoryState(nextStoredState: StoredEmailActionState | null): void {
  if (typeof window === 'undefined') {
    return;
  }

  const nextState =
    window.history.state && typeof window.history.state === 'object'
      ? { ...window.history.state }
      : {};

  delete nextState[ACCOUNT_ACTION_HISTORY_KEY];
  delete nextState[LEGACY_ACCOUNT_ACTION_HISTORY_KEY];

  if (nextStoredState) {
    nextState[ACCOUNT_ACTION_HISTORY_KEY] = nextStoredState;
    nextState[LEGACY_ACCOUNT_ACTION_HISTORY_KEY] = nextStoredState;
  }

  window.history.replaceState(nextState, '', ACCOUNT_ACTION_ROUTE_PATH);
}

function resolveBaseOrigin(): string {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  return 'https://dullypdf.com';
}

function resolveAllowedOrigins(): Set<string> {
  return new Set([resolveBaseOrigin(), 'https://dullypdf.com']);
}

function isReservedAccountActionPath(pathname: string): boolean {
  return pathname === ACCOUNT_ACTION_ROUTE_PATH || pathname === LEGACY_ACCOUNT_ACTION_ROUTE_PATH;
}

export function resolveSafeContinuePath(rawContinueUrl?: string | null): string {
  if (!rawContinueUrl) {
    return '/';
  }

  try {
    const parsed = new URL(rawContinueUrl, resolveBaseOrigin());
    if (!resolveAllowedOrigins().has(parsed.origin)) {
      return '/';
    }
    const normalizedPath = parsed.pathname || '/';
    if (isReservedAccountActionPath(normalizedPath)) {
      return '/';
    }
    return `${normalizedPath}${parsed.search}${parsed.hash}` || '/';
  } catch {
    return '/';
  }
}

export function parseEmailActionSearch(search: string): ParsedEmailAction {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  const continuePath = resolveSafeContinuePath(params.get('continueUrl'));
  const mode = (params.get('mode') || '').trim();
  const oobCode = (params.get('oobCode') || '').trim();

  if (mode !== 'verifyEmail' && mode !== 'resetPassword') {
    return { status: 'invalid', reason: 'unsupported-mode', continuePath };
  }
  if (!oobCode) {
    return { status: 'invalid', reason: 'missing-code', continuePath };
  }

  return {
    status: 'ready',
    mode,
    oobCode,
    continuePath,
  };
}

export function readStoredEmailActionState(historyState: unknown): StoredEmailActionState | null {
  if (!historyState || typeof historyState !== 'object') {
    return null;
  }
  const historyCandidate = historyState as Record<string, unknown>;
  const candidate =
    historyCandidate[ACCOUNT_ACTION_HISTORY_KEY] ?? historyCandidate[LEGACY_ACCOUNT_ACTION_HISTORY_KEY];
  if (!candidate || typeof candidate !== 'object') {
    return null;
  }
  const kind = (candidate as Record<string, unknown>).kind;
  if (kind === 'pending-reset-password') {
    const continuePath = (candidate as Record<string, unknown>).continuePath;
    if (typeof continuePath !== 'string' || !continuePath.startsWith('/')) {
      return null;
    }
    return {
      kind,
      continuePath,
    };
  }
  const status = (candidate as Record<string, unknown>).status;
  const mode = (candidate as Record<string, unknown>).mode;
  const continuePath = (candidate as Record<string, unknown>).continuePath;
  if (
    kind !== 'result' ||
    (status !== 'success' && status !== 'error') ||
    (mode !== 'verifyEmail' && mode !== 'resetPassword') ||
    typeof continuePath !== 'string' ||
    !continuePath.startsWith('/')
  ) {
    return null;
  }
  return {
    kind,
    mode,
    status,
    continuePath,
  };
}

export function writeStoredEmailActionState(result: StoredEmailActionState): void {
  replaceAccountActionHistoryState(result);
}

export function scrubEmailActionRoute(): void {
  replaceAccountActionHistoryState(readStoredEmailActionState(window.history.state));
}
