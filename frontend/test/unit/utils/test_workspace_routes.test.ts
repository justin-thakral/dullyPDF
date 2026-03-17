import { describe, expect, it } from 'vitest';

import {
  areWorkspaceBrowserRoutesEqual,
  buildWorkspaceBrowserHref,
  getWorkspaceBrowserRouteKey,
  parseWorkspaceBrowserRoute,
} from '../../../src/utils/workspaceRoutes';

describe('workspaceRoutes', () => {
  it('parses the supported workspace routes', () => {
    expect(parseWorkspaceBrowserRoute('/', '')).toEqual({ kind: 'homepage' });
    expect(parseWorkspaceBrowserRoute('/upload', '')).toEqual({ kind: 'upload-root' });
    expect(parseWorkspaceBrowserRoute('/ui', '')).toEqual({ kind: 'ui-root' });
    expect(parseWorkspaceBrowserRoute('/ui/profile', '')).toEqual({ kind: 'profile' });
    expect(parseWorkspaceBrowserRoute('/ui/forms/saved-1', '')).toEqual({
      kind: 'saved-form',
      formId: 'saved-1',
    });
    expect(parseWorkspaceBrowserRoute('/ui/groups/group-1', '?template=saved-2')).toEqual({
      kind: 'group',
      groupId: 'group-1',
      templateId: 'saved-2',
    });
  });

  it('rejects malformed workspace routes', () => {
    expect(parseWorkspaceBrowserRoute('/ui/forms/', '')).toBeNull();
    expect(parseWorkspaceBrowserRoute('/ui/groups/', '')).toBeNull();
    expect(parseWorkspaceBrowserRoute('/ui/unknown', '')).toBeNull();
  });

  it('builds canonical hrefs and stable route keys', () => {
    const route = { kind: 'group', groupId: 'group 1', templateId: 'saved/2' } as const;
    expect(buildWorkspaceBrowserHref(route)).toBe('/ui/groups/group%201?template=saved%2F2');
    expect(getWorkspaceBrowserRouteKey(route)).toBe('/ui/groups/group%201?template=saved%2F2');
    expect(areWorkspaceBrowserRoutesEqual(route, {
      kind: 'group',
      groupId: 'group 1',
      templateId: 'saved/2',
    })).toBe(true);
  });
});
