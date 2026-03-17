export type WorkspaceBrowserRoute =
  | { kind: 'homepage' }
  | { kind: 'upload-root' }
  | { kind: 'ui-root' }
  | { kind: 'profile' }
  | { kind: 'saved-form'; formId: string }
  | { kind: 'group'; groupId: string; templateId: string | null };

function normalizeRoutePath(pathname: string): string {
  return pathname.replace(/\/+$/, '') || '/';
}

export function parseWorkspaceBrowserRoute(
  pathname: string,
  search = '',
): WorkspaceBrowserRoute | null {
  const normalizedPath = normalizeRoutePath(pathname);
  if (normalizedPath === '/') {
    return { kind: 'homepage' };
  }
  if (normalizedPath === '/upload') {
    return { kind: 'upload-root' };
  }
  if (normalizedPath === '/ui') {
    return { kind: 'ui-root' };
  }
  if (normalizedPath === '/ui/profile') {
    return { kind: 'profile' };
  }
  if (normalizedPath.startsWith('/ui/forms/')) {
    const rawFormId = normalizedPath.slice('/ui/forms/'.length);
    if (!rawFormId || rawFormId.includes('/')) {
      return null;
    }
    return {
      kind: 'saved-form',
      formId: decodeURIComponent(rawFormId),
    };
  }
  if (normalizedPath.startsWith('/ui/groups/')) {
    const rawGroupId = normalizedPath.slice('/ui/groups/'.length);
    if (!rawGroupId || rawGroupId.includes('/')) {
      return null;
    }
    const params = new URLSearchParams(search);
    const rawTemplateId = params.get('template');
    return {
      kind: 'group',
      groupId: decodeURIComponent(rawGroupId),
      templateId: rawTemplateId ? decodeURIComponent(rawTemplateId) : null,
    };
  }
  return null;
}

export function buildWorkspaceBrowserHref(route: WorkspaceBrowserRoute): string {
  switch (route.kind) {
    case 'homepage':
      return '/';
    case 'upload-root':
      return '/upload';
    case 'ui-root':
      return '/ui';
    case 'profile':
      return '/ui/profile';
    case 'saved-form':
      return `/ui/forms/${encodeURIComponent(route.formId)}`;
    case 'group': {
      const basePath = `/ui/groups/${encodeURIComponent(route.groupId)}`;
      if (!route.templateId) {
        return basePath;
      }
      const params = new URLSearchParams();
      params.set('template', route.templateId);
      return `${basePath}?${params.toString()}`;
    }
    default:
      return '/';
  }
}

export function getWorkspaceBrowserRouteKey(route: WorkspaceBrowserRoute): string {
  return buildWorkspaceBrowserHref(route);
}

export function isWorkspaceWorkflowRoute(route: WorkspaceBrowserRoute): boolean {
  return (
    route.kind === 'upload-root' ||
    route.kind === 'ui-root' ||
    route.kind === 'saved-form' ||
    route.kind === 'group'
  );
}

export function areWorkspaceBrowserRoutesEqual(
  left: WorkspaceBrowserRoute | null | undefined,
  right: WorkspaceBrowserRoute | null | undefined,
): boolean {
  if (!left || !right) {
    return left === right;
  }
  return getWorkspaceBrowserRouteKey(left) === getWorkspaceBrowserRouteKey(right);
}
