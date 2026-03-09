import { describe, expect, it } from 'vitest';
import {
  ACCOUNT_ACTION_ROUTE_PATH,
  LEGACY_ACCOUNT_ACTION_ROUTE_PATH,
  parseEmailActionSearch,
  readStoredEmailActionState,
  resolveSafeContinuePath,
} from '../../../src/utils/emailActions';

describe('emailActions utils', () => {
  it('keeps same-origin continue URLs and rejects external or recursive targets', () => {
    expect(resolveSafeContinuePath('https://dullypdf.com/profile?from=email')).toBe('/profile?from=email');
    expect(resolveSafeContinuePath('/usage-docs/getting-started')).toBe('/usage-docs/getting-started');
    expect(resolveSafeContinuePath('https://evil.example/path')).toBe('/');
    expect(resolveSafeContinuePath(`https://dullypdf.com${ACCOUNT_ACTION_ROUTE_PATH}?mode=verifyEmail`)).toBe('/');
    expect(resolveSafeContinuePath(`https://dullypdf.com${LEGACY_ACCOUNT_ACTION_ROUTE_PATH}?mode=verifyEmail`)).toBe('/');
    expect(resolveSafeContinuePath(null)).toBe('/');
  });

  it('parses valid verify-email action queries with a safe continue path', () => {
    expect(
      parseEmailActionSearch(
        '?mode=verifyEmail&oobCode=test-code&continueUrl=https%3A%2F%2Fdullypdf.com%2Fprofile%3Ffrom%3Demail',
      ),
    ).toEqual({
      status: 'ready',
      mode: 'verifyEmail',
      oobCode: 'test-code',
      continuePath: '/profile?from=email',
    });
  });

  it('parses valid reset-password action queries', () => {
    expect(parseEmailActionSearch('?mode=resetPassword&oobCode=reset-code')).toEqual({
      status: 'ready',
      mode: 'resetPassword',
      oobCode: 'reset-code',
      continuePath: '/',
    });
  });

  it('rejects unsupported modes and missing codes while preserving a safe fallback continue path', () => {
    expect(parseEmailActionSearch('?mode=recoverEmail&oobCode=test-code')).toEqual({
      status: 'invalid',
      reason: 'unsupported-mode',
      continuePath: '/',
    });
    expect(parseEmailActionSearch('?mode=verifyEmail')).toEqual({
      status: 'invalid',
      reason: 'missing-code',
      continuePath: '/',
    });
  });

  it('reads stored verification results from history state only when shape is valid', () => {
    expect(
      readStoredEmailActionState({
        dullypdfAccountAction: { kind: 'result', mode: 'verifyEmail', status: 'success', continuePath: '/profile' },
      }),
    ).toEqual({
      kind: 'result',
      mode: 'verifyEmail',
      status: 'success',
      continuePath: '/profile',
    });
    expect(
      readStoredEmailActionState({
        dullypdfAccountAction: {
          kind: 'pending-reset-password',
          oobCode: 'reset-code',
          email: 'reset@example.com',
          continuePath: '/',
        },
      }),
    ).toEqual({
      kind: 'pending-reset-password',
      oobCode: 'reset-code',
      email: 'reset@example.com',
      continuePath: '/',
    });
    expect(
      readStoredEmailActionState({
        dullypdfVerifyEmailAction: { kind: 'result', mode: 'verifyEmail', status: 'success', continuePath: '/legacy' },
      }),
    ).toEqual({
      kind: 'result',
      mode: 'verifyEmail',
      status: 'success',
      continuePath: '/legacy',
    });
    expect(readStoredEmailActionState({ dullypdfAccountAction: { kind: 'result', status: 'wat', continuePath: '/' } })).toBeNull();
    expect(readStoredEmailActionState(null)).toBeNull();
  });
});
