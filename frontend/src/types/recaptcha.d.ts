type RecaptchaEnterprise = {
  ready: (callback: () => void) => void;
  execute: (siteKey: string, options: { action?: string }) => Promise<string>;
};

type Grecaptcha = {
  enterprise: RecaptchaEnterprise;
};

interface Window {
  grecaptcha?: Grecaptcha;
}
