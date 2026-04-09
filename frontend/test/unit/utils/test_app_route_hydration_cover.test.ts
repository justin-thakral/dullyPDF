import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { shouldActivateAppRouteHydrationCover } from '../../../src/utils/appRouteHydrationCover';

function samplePathForRewriteSource(source: string): string {
  return source
    .replace(':formId', 'sample-form')
    .replace(':groupId', 'sample-group')
    .replace(':token', 'sample-token');
}

describe('appRouteHydrationCover', () => {
  it.each([
    ['/account-action', '', true],
    ['/verify-email', '', true],
    ['/upload', '', true],
    ['/ui', '', true],
    ['/ui/profile', '', true],
    ['/ui/forms/saved-1', '', true],
    ['/ui/groups/group-1', '?template=saved-2', true],
    ['/respond/token-1', '', true],
    ['/sign/token-1', '', true],
    ['/verify-signing/token-1', '', true],
    ['/', '', false],
    ['/privacy', '', false],
    ['/terms', '', false],
    ['/workflows', '', false],
    ['/industries', '', false],
    ['/blog', '', false],
    ['/blog/post-slug', '', false],
    ['/usage-docs/getting-started', '', false],
    ['/ui/forms/nested/path', '', false],
    ['/respond/nested/token', '', false],
  ])('returns %s for %s%s', (pathname, search, expected) => {
    expect(shouldActivateAppRouteHydrationCover(pathname, search)).toBe(expected);
  });

  it('covers every app-shell rewrite declared in firebase hosting', () => {
    const firebasePath = resolve(process.cwd(), '../firebase.json');
    const payload = JSON.parse(readFileSync(firebasePath, 'utf8'));
    const rewrites = payload.hosting?.rewrites || [];

    const appShellRewriteSources = rewrites
      .filter((entry: { destination?: string }) => entry.destination === '/app-shell.html')
      .map((entry: { source: string }) => entry.source);

    expect(appShellRewriteSources.length).toBeGreaterThan(0);

    for (const source of appShellRewriteSources) {
      const samplePath = samplePathForRewriteSource(source);
      const search = source === '/ui/groups/:groupId' ? '?template=sample-template' : '';
      expect(
        shouldActivateAppRouteHydrationCover(samplePath, search),
        `Expected rewrite source ${source} to activate the app-route hydration cover`,
      ).toBe(true);
    }
  });
});
