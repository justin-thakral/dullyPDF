import { lazy } from 'react';

/**
 * WorkspaceRuntime is the largest app chunk because it orchestrates many rare
 * screens and dialogs in one place. These lazy wrappers keep the runtime shell
 * synchronous while moving infrequently used UI islands into separate chunks.
 */
export const LazyHomepage = lazy(() => import('./components/pages/Homepage'));
export const LazyLoginPage = lazy(() => import('./components/pages/LoginPage'));
export const LazyProfilePage = lazy(() => import('./components/pages/ProfilePage'));
export const LazyVerifyEmailPage = lazy(() => import('./components/pages/VerifyEmailPage'));
export const LazySearchFillModal = lazy(() => import('./components/features/SearchFillModal'));
export const LazyFillLinkManagerDialog = lazy(() => import('./components/features/FillLinkManagerDialog'));
export const LazyApiFillManagerDialog = lazy(() => import('./components/features/ApiFillManagerDialog'));
export const LazySignatureRequestDialog = lazy(() => import('./components/features/SignatureRequestDialog'));
export const LazyDowngradeRetentionDialog = lazy(() => import('./components/features/DowngradeRetentionDialog'));
export const LazyUploadView = lazy(() => import('./components/features/UploadView'));
export const LazyProcessingView = lazy(() => import('./components/features/ProcessingView'));

export const LazyGroupUploadDialog = lazy(() =>
  import('./components/features/GroupUploadDialog').then((module) => ({
    default: module.GroupUploadDialog,
  })),
);

export const LazyDemoTour = lazy(() =>
  import('./components/demo/DemoTour').then((module) => ({
    default: module.DemoTour,
  })),
);
