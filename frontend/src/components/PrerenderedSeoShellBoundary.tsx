import { useLayoutEffect, type ReactNode } from 'react';

type PrerenderedSeoShellBoundaryProps = {
  enabled: boolean;
  children: ReactNode;
};

export function PrerenderedSeoShellBoundary({
  enabled,
  children,
}: PrerenderedSeoShellBoundaryProps) {
  useLayoutEffect(() => {
    if (!enabled || typeof document === 'undefined') {
      return;
    }

    document.body.removeAttribute('data-seo-shell-visible');
    document.getElementById('seo-static-shell')?.remove();
  }, [enabled]);

  return <>{children}</>;
}
