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

type FooterLink = {
  label: string;
  href: string;
};

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
  return (
    <footer className="site-footer">
      <div className="site-footer__bar">
        <InlineLinkGroup className="site-footer__group--product" title="Product" links={PRODUCT_LINKS} />
        <InlineLinkGroup className="site-footer__group--resources" title="Resources" links={RESOURCE_LINKS} />
        <div className="site-footer__center">
          &copy; {new Date().getFullYear()} DullyPDF
        </div>
        <InlineLinkGroup className="site-footer__group--legal" title="Legal" links={LEGAL_LINKS} />
        <InlineLinkGroup className="site-footer__group--solutions" title="Solutions" links={SOLUTION_LINKS} />
      </div>
    </footer>
  );
};
