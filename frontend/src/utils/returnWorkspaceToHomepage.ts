import type { WorkspaceBrowserRoute } from './workspaceRoutes';
import { clearWorkspaceResumeState } from './workspaceResumeState';

type WorkspaceRouteNavigator = (
  route: WorkspaceBrowserRoute,
  options?: { replace?: boolean },
) => void;

/**
 * Centralize the common "leave the workspace and reopen the homepage" flow so
 * sign-out and runtime recovery paths clear the resume manifest consistently.
 */
export function returnWorkspaceToHomepage(
  navigate: WorkspaceRouteNavigator | null | undefined,
): void {
  clearWorkspaceResumeState();
  navigate?.({ kind: 'homepage' }, { replace: true });
}
