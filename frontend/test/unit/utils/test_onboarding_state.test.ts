import { beforeEach, describe, expect, it } from 'vitest';

import {
  clearOnboardingPending,
  consumeOnboardingPending,
  hasOnboardingPending,
  markOnboardingPending,
  markPostVerificationOnboardingPending,
} from '../../../src/utils/onboardingState';

describe('onboardingState', () => {
  beforeEach(() => {
    window.localStorage.clear();
    clearOnboardingPending();
  });

  it('keeps signup onboarding scoped to the matching user id', () => {
    markOnboardingPending('user-1');

    expect(hasOnboardingPending('user-1')).toBe(true);
    expect(hasOnboardingPending('user-2')).toBe(false);
    expect(consumeOnboardingPending('user-2')).toBe(false);
    expect(consumeOnboardingPending('user-1')).toBe(true);
    expect(hasOnboardingPending('user-1')).toBe(false);
  });

  it('lets a successful email verification resume onboarding after a fresh sign-in on that browser', () => {
    markPostVerificationOnboardingPending();

    expect(hasOnboardingPending('any-user')).toBe(true);
    expect(consumeOnboardingPending('another-user')).toBe(true);
    expect(hasOnboardingPending('any-user')).toBe(false);
  });

  it('clearOnboardingPending removes both signup and post-verification markers', () => {
    markOnboardingPending('user-1');
    markPostVerificationOnboardingPending();

    clearOnboardingPending();

    expect(hasOnboardingPending('user-1')).toBe(false);
    expect(consumeOnboardingPending('user-1')).toBe(false);
  });
});
