import { useMemo } from 'react';
import { getIntentPages } from '../../config/intentPages';
import './SiteFooter.css';

const PRODUCT_LINKS = [
  { label: 'Try DullyPDF', href: '/' },
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

const FooterColumn = ({ title, links }: { title: string; links: { label: string; href: string }[] }) => (
  <div className="site-footer__column">
    <h3 className="site-footer__column-title">{title}</h3>
    <ul className="site-footer__link-list">
      {links.map((link) => (
        <li key={link.href}>
          <a href={link.href}>{link.label}</a>
        </li>
      ))}
    </ul>
  </div>
);

export const SiteFooter = () => {
  const intentPages = useMemo(() => getIntentPages(), []);
  const workflowLinks = useMemo(
    () => intentPages.filter((p) => p.category === 'workflow').map((p) => ({ label: p.navLabel, href: p.path })),
    [intentPages],
  );
  const industryLinks = useMemo(
    () => intentPages.filter((p) => p.category === 'industry').map((p) => ({ label: p.navLabel, href: p.path })),
    [intentPages],
  );

  return (
    <footer className="site-footer">
      <div className="site-footer__grid">
        <FooterColumn title="Product" links={PRODUCT_LINKS} />
        <FooterColumn title="Workflows" links={workflowLinks} />
        <FooterColumn title="Industries" links={industryLinks} />
        <FooterColumn title="Resources" links={RESOURCE_LINKS} />
        <FooterColumn title="Legal" links={LEGAL_LINKS} />
      </div>
      <div className="site-footer__bottom">
        <span>&copy; {new Date().getFullYear()} DullyPDF</span>
        <a href="mailto:justin@ttcommercial.com" className="site-footer__contact">
          justin@ttcommercial.com
        </a>
      </div>
    </footer>
  );
};
