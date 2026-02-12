import { beforeEach, describe, expect, it, vi } from 'vitest';

async function importRecaptchaModule() {
  return import('../../../src/utils/recaptcha');
}

describe('recaptcha utils', () => {
  beforeEach(() => {
    vi.resetModules();
    document.head.innerHTML = '';
    document.body.className = '';
    delete (window as any).grecaptcha;
  });

  it('reference-counts badge visibility by scope', async () => {
    const { enableRecaptchaBadge, disableRecaptchaBadge } = await importRecaptchaModule();

    enableRecaptchaBadge('login');
    enableRecaptchaBadge('login');
    enableRecaptchaBadge('contact');
    expect(document.body.classList.contains('recaptcha-badge-visible')).toBe(true);

    disableRecaptchaBadge('login');
    expect(document.body.classList.contains('recaptcha-badge-visible')).toBe(true);

    disableRecaptchaBadge('contact');
    expect(document.body.classList.contains('recaptcha-badge-visible')).toBe(false);
  });

  it('loads the script once per key and reuses the same in-flight promise', async () => {
    const { loadRecaptcha } = await importRecaptchaModule();

    const first = loadRecaptcha('site-key-a');
    const second = loadRecaptcha('site-key-a');
    const script = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;

    expect(first).toBe(second);
    expect(script).toBeTruthy();
    expect(script.src).toContain('https://www.google.com/recaptcha/enterprise.js?render=site-key-a');
    expect(document.querySelectorAll('script[data-recaptcha="enterprise"]')).toHaveLength(1);

    script.dispatchEvent(new Event('load'));
    await expect(first).resolves.toBeUndefined();
  });

  it('resets cached promise when the site key changes', async () => {
    const { loadRecaptcha } = await importRecaptchaModule();

    const first = loadRecaptcha('site-key-a');
    const firstScript = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;

    const second = loadRecaptcha('site-key-b');
    const secondScript = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;

    expect(first).not.toBe(second);
    expect(secondScript).not.toBe(firstScript);
    expect(document.querySelectorAll('script[data-recaptcha="enterprise"]')).toHaveLength(1);

    firstScript.dispatchEvent(new Event('load'));
    secondScript.dispatchEvent(new Event('load'));
    await expect(Promise.all([first, second])).resolves.toEqual([undefined, undefined]);
  });

  it('removes stale existing script element and creates a fresh one', async () => {
    const staleScript = document.createElement('script');
    staleScript.dataset.recaptcha = 'enterprise';
    document.head.appendChild(staleScript);

    const { loadRecaptcha } = await importRecaptchaModule();
    const promise = loadRecaptcha('site-key-a');

    expect(document.querySelectorAll('script[data-recaptcha="enterprise"]')).toHaveLength(1);
    const newScript = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;
    expect(newScript).not.toBe(staleScript);
    expect(newScript.src).toContain('site-key-a');

    newScript.dispatchEvent(new Event('load'));
    await expect(promise).resolves.toBeUndefined();
  });

  it('surfaces script-load errors from newly created script', async () => {
    const { loadRecaptcha } = await importRecaptchaModule();
    const promise = loadRecaptcha('site-key-a');

    const script = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;
    script.dispatchEvent(new Event('error'));
    await expect(promise).rejects.toThrow('Failed to load reCAPTCHA');
  });

  it('allows retrying after an initial script-load failure for the same key', async () => {
    const { loadRecaptcha } = await importRecaptchaModule();

    const first = loadRecaptcha('site-key-a');
    const firstScript = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;
    firstScript.dispatchEvent(new Event('error'));
    await expect(first).rejects.toThrow('Failed to load reCAPTCHA');

    firstScript.remove();

    const second = loadRecaptcha('site-key-a');
    const secondScript = document.querySelector('script[data-recaptcha="enterprise"]') as HTMLScriptElement;
    expect(secondScript).toBeTruthy();
    expect(secondScript).not.toBe(firstScript);

    secondScript.dispatchEvent(new Event('load'));
    await expect(second).resolves.toBeUndefined();
  });

  it('rejects when site key is missing', async () => {
    const { loadRecaptcha } = await importRecaptchaModule();

    await expect(loadRecaptcha('')).rejects.toThrow('Missing reCAPTCHA site key');
  });

  it('returns token on successful enterprise execute', async () => {
    const execute = vi.fn().mockResolvedValue('token-123');
    const ready = vi.fn((callback: () => void) => callback());
    (window as any).grecaptcha = {
      enterprise: {
        ready,
        execute,
      },
    };

    const { getRecaptchaToken } = await importRecaptchaModule();
    const token = await getRecaptchaToken('site-key-a', 'signup');

    expect(token).toBe('token-123');
    expect(ready).toHaveBeenCalledTimes(1);
    expect(execute).toHaveBeenCalledWith('site-key-a', { action: 'signup' });
  });

  it('propagates enterprise execute failures', async () => {
    const execute = vi.fn().mockRejectedValue(new Error('enterprise failed'));
    const ready = vi.fn((callback: () => void) => callback());
    (window as any).grecaptcha = {
      enterprise: {
        ready,
        execute,
      },
    };

    const { getRecaptchaToken } = await importRecaptchaModule();

    await expect(getRecaptchaToken('site-key-a', 'contact')).rejects.toThrow('enterprise failed');
  });
});
