const ONBOARDING_PENDING_KEY = 'dullypdf.onboardingPending';
const VERIFIED_EMAIL_ONBOARDING_PENDING_KEY = 'dullypdf.verifiedEmailOnboardingPending';
const ONBOARDING_MAX_AGE_MS = 24 * 60 * 60 * 1000;

type UserScopedOnboardingRecord = {
  userId: string;
  ts: number;
};

type BrowserScopedOnboardingRecord = {
  ts: number;
};

function removePendingKey(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage access is best-effort only.
  }
}

function isFreshTimestamp(ts: unknown): ts is number {
  return typeof ts === 'number' && Number.isFinite(ts) && Date.now() - ts <= ONBOARDING_MAX_AGE_MS;
}

function readUserScopedRecord(): UserScopedOnboardingRecord | null {
  try {
    const raw = localStorage.getItem(ONBOARDING_PENDING_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (typeof data?.userId !== 'string' || !isFreshTimestamp(data?.ts)) {
      removePendingKey(ONBOARDING_PENDING_KEY);
      return null;
    }
    return data;
  } catch {
    removePendingKey(ONBOARDING_PENDING_KEY);
    return null;
  }
}

function readBrowserScopedRecord(): BrowserScopedOnboardingRecord | null {
  try {
    const raw = localStorage.getItem(VERIFIED_EMAIL_ONBOARDING_PENDING_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!isFreshTimestamp(data?.ts)) {
      removePendingKey(VERIFIED_EMAIL_ONBOARDING_PENDING_KEY);
      return null;
    }
    return data;
  } catch {
    removePendingKey(VERIFIED_EMAIL_ONBOARDING_PENDING_KEY);
    return null;
  }
}

export function markOnboardingPending(userId: string): void {
  try {
    localStorage.setItem(
      ONBOARDING_PENDING_KEY,
      JSON.stringify({ userId, ts: Date.now() }),
    );
  } catch {
    // Storage quota or private mode — silently skip.
  }
}

export function markPostVerificationOnboardingPending(): void {
  try {
    localStorage.setItem(
      VERIFIED_EMAIL_ONBOARDING_PENDING_KEY,
      JSON.stringify({ ts: Date.now() }),
    );
  } catch {
    // Storage quota or private mode — silently skip.
  }
}

export function consumeOnboardingPending(userId: string): boolean {
  const userScopedRecord = readUserScopedRecord();
  if (userScopedRecord?.userId === userId) {
    removePendingKey(ONBOARDING_PENDING_KEY);
    return true;
  }
  const browserScopedRecord = readBrowserScopedRecord();
  if (browserScopedRecord) {
    removePendingKey(VERIFIED_EMAIL_ONBOARDING_PENDING_KEY);
    return true;
  }
  return false;
}

export function hasOnboardingPending(userId: string): boolean {
  const userScopedRecord = readUserScopedRecord();
  if (userScopedRecord?.userId === userId) {
    return true;
  }
  return Boolean(readBrowserScopedRecord());
}

export function clearOnboardingPending(): void {
  removePendingKey(ONBOARDING_PENDING_KEY);
  removePendingKey(VERIFIED_EMAIL_ONBOARDING_PENDING_KEY);
}
