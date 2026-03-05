import { useEffect, useState } from 'react';
import './SiteFooter.css';

const PRODUCT_LINKS = [
  { label: 'Getting Started', href: '/usage-docs/getting-started' },
  { label: 'Usage Docs', href: '/usage-docs' },
];

const RESOURCE_LINKS = [
  { label: 'Blog', href: '/blog' },
  { label: 'Troubleshooting', href: '/usage-docs/troubleshooting' },
];

const LEGAL_LINKS = [
  { label: 'Privacy Policy', href: '/privacy' },
  { label: 'Terms of Service', href: '/terms' },
];

const SOLUTION_LINKS = [
  { label: 'Workflow Library', href: '/workflows' },
  { label: 'Industry Solutions', href: '/industries' },
];

const MOBILE_WORKFLOW_LINKS = [
  { label: 'Library', href: '/workflows' },
  { label: 'Industry Solutions', href: '/industries' },
];

type FooterLink = {
  label: string;
  href: string;
};

const MOBILE_FOOTER_QUERY = '(max-width: 900px)';

const InlineLinkGroup = ({
  title,
  links,
  className,
}: {
  title: string;
  links: FooterLink[];
  className?: string;
}) => (
  <div className={`site-footer__link-group${className ? ` ${className}` : ''}`}>
    <span className="site-footer__label">{title}:</span>
    <div className="site-footer__links">
      {links.map((link) => (
        <a key={link.href} href={link.href}>
          {link.label}
        </a>
      ))}
    </div>
  </div>
);

export const SiteFooter = () => {
  const [mobileFooter, setMobileFooter] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    return window.matchMedia(MOBILE_FOOTER_QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mediaQuery = window.matchMedia(MOBILE_FOOTER_QUERY);
    const handleChange = (event: MediaQueryListEvent) => {
      setMobileFooter(event.matches);
    };

    setMobileFooter(mediaQuery.matches);
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }

    const legacyMediaQuery = mediaQuery as MediaQueryList & {
      addListener: (listener: (event: MediaQueryListEvent) => void) => void;
      removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
    };
    legacyMediaQuery.addListener(handleChange);
    return () => legacyMediaQuery.removeListener(handleChange);
  }, []);

  return (
    <footer className="site-footer">
      {!mobileFooter ? (
        <div className="site-footer__bar">
          <InlineLinkGroup className="site-footer__group--product" title="Product" links={PRODUCT_LINKS} />
          <InlineLinkGroup className="site-footer__group--resources" title="Resources" links={RESOURCE_LINKS} />
          <div className="site-footer__center">
            &copy; {new Date().getFullYear()} DullyPDF
          </div>
          <InlineLinkGroup className="site-footer__group--legal" title="Legal" links={LEGAL_LINKS} />
          <InlineLinkGroup className="site-footer__group--solutions" title="Solutions" links={SOLUTION_LINKS} />
        </div>
      ) : (
        <div className="site-footer__mobile">
          <div className="site-footer__mobile-rows">
            <div className="site-footer__mobile-row">
              <InlineLinkGroup title="Product" links={PRODUCT_LINKS} />
              <InlineLinkGroup title="Workflows" links={MOBILE_WORKFLOW_LINKS} />
            </div>
            <div className="site-footer__mobile-row">
              <InlineLinkGroup title="Resources" links={RESOURCE_LINKS} />
              <InlineLinkGroup title="Legal" links={LEGAL_LINKS} />
            </div>
          </div>
          <div className="site-footer__mobile-bottom">&copy; {new Date().getFullYear()} DullyPDF</div>
        </div>
      )}
    </footer>
  );
};
