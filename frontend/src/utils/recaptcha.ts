const RECAPTCHA_SCRIPT_SRC = 'https://www.google.com/recaptcha/enterprise.js';
const RECAPTCHA_BADGE_CLASS = 'recaptcha-badge-visible';

let recaptchaLoadPromise: Promise<void> | null = null;
let loadedSiteKey: string | null = null;
const activeBadgeScopes = new Set<string>();

function updateRecaptchaBadgeVisibility(): void {
  if (typeof document === 'undefined') {
    return;
  }
  const body = document.body;
  if (!body) return;
  if (activeBadgeScopes.size > 0) {
    body.classList.add(RECAPTCHA_BADGE_CLASS);
  } else {
    body.classList.remove(RECAPTCHA_BADGE_CLASS);
  }
}

export function enableRecaptchaBadge(scope: string): void {
  if (!scope) return;
  activeBadgeScopes.add(scope);
  updateRecaptchaBadgeVisibility();
}

export function disableRecaptchaBadge(scope: string): void {
  if (!scope) return;
  activeBadgeScopes.delete(scope);
  updateRecaptchaBadgeVisibility();
}

function hasRecaptcha(): boolean {
  return typeof window !== 'undefined' && Boolean(window.grecaptcha?.enterprise);
}

export function loadRecaptcha(siteKey: string): Promise<void> {
  if (!siteKey) {
    return Promise.reject(new Error('Missing reCAPTCHA site key'));
  }
  if (hasRecaptcha()) {
    return Promise.resolve();
  }
  if (recaptchaLoadPromise && loadedSiteKey === siteKey) {
    return recaptchaLoadPromise;
  }

  loadedSiteKey = siteKey;
  recaptchaLoadPromise = new Promise((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>('script[data-recaptcha="enterprise"]');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(), { once: true });
      existingScript.addEventListener('error', () => reject(new Error('Failed to load reCAPTCHA')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = `${RECAPTCHA_SCRIPT_SRC}?render=${encodeURIComponent(siteKey)}`;
    script.async = true;
    script.defer = true;
    script.dataset.recaptcha = 'enterprise';
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load reCAPTCHA'));
    document.head.appendChild(script);
  });

  return recaptchaLoadPromise;
}

export async function getRecaptchaToken(siteKey: string, action: string): Promise<string> {
  await loadRecaptcha(siteKey);
  const enterprise = window.grecaptcha?.enterprise;
  if (!enterprise) {
    throw new Error('reCAPTCHA is unavailable');
  }

  return new Promise((resolve, reject) => {
    enterprise.ready(() => {
      enterprise
        .execute(siteKey, { action })
        .then(resolve)
        .catch(reject);
    });
  });
}
