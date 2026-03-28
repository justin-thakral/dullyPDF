import { useEffect } from 'react';
import { getBlogPosts } from '../../config/blogPosts';
import { BLOG_INDEX_SEO } from '../../config/blogSeo';
import { applySeoMetadata } from '../../utils/seo';
import { Breadcrumbs } from '../ui/Breadcrumbs';
import { SiteFooter } from '../ui/SiteFooter';
import { resolveRouteSeoBodyContent } from '../../config/routeSeo';
import './BlogIndexPage.css';

const HEADER_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Usage Docs', href: '/usage-docs' },
  { label: 'Blog', href: '/blog' },
];

const BlogIndexPage = () => {
  const posts = getBlogPosts();
  const bodyContent = resolveRouteSeoBodyContent({ kind: 'blog-index' });

  useEffect(() => {
    applySeoMetadata(BLOG_INDEX_SEO);
  }, []);

  return (
    <div className="blog-index">
      <div className="blog-index__card">
        <header className="blog-index__header">
          <div className="blog-index__brand">
            <picture>
              <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
              <img src="/DullyPDFLogoImproved.png" alt="DullyPDF" className="blog-index__logo" decoding="async" />
            </picture>
            <div>
              <div className="blog-index__brand-name">DullyPDF</div>
              <div className="blog-index__brand-tagline">PDF automation workflows</div>
            </div>
          </div>
          <nav className="blog-index__nav" aria-label="Primary navigation">
            {HEADER_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className={link.href === '/blog' ? 'blog-index__nav-link blog-index__nav-link--active' : 'blog-index__nav-link'}
              >
                {link.label}
              </a>
            ))}
          </nav>
        </header>

        <main className="blog-index__content">
          <Breadcrumbs items={[{ label: 'Home', href: '/' }, { label: 'Blog' }]} />
          <section className="blog-index__hero">
            <p className="blog-index__kicker">{bodyContent?.heroKicker ?? 'Blog'}</p>
            <h1>{bodyContent?.heading ?? 'PDF Automation Guides & Tutorials'}</h1>
            <p>{bodyContent?.paragraphs?.[0] ?? 'Practical guides for converting PDFs to fillable forms, mapping fields to databases, and automating repetitive form-filling workflows.'}</p>
          </section>

          <section className="blog-index__support">
            {(bodyContent?.supportSections ?? []).map((section) => (
              <article key={section.title} className="blog-index__support-card">
                <h2>{section.title}</h2>
                {section.paragraphs?.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
                {section.links?.length ? (
                  <ul>
                    {section.links.map((link) => (
                      <li key={link.href}>
                        <a href={link.href}>{link.label}</a>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </article>
            ))}
          </section>

          <div className="blog-index__grid">
            {posts.map((post) => (
              <article key={post.slug} className="blog-index__post-card">
                <h2>
                  <a href={`/blog/${post.slug}`}>{post.title}</a>
                </h2>
                <time className="blog-index__date" dateTime={post.publishedDate}>
                  {new Date(post.publishedDate + 'T00:00:00').toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })}
                </time>
                <p>{post.summary}</p>
                <a href={`/blog/${post.slug}`} className="blog-index__read-more">
                  Read more
                </a>
              </article>
            ))}
          </div>
        </main>
        <SiteFooter />
      </div>
    </div>
  );
};

export default BlogIndexPage;
