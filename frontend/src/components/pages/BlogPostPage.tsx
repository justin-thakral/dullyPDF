import { useEffect, useMemo } from 'react';
import { getBlogPost } from '../../config/blogPosts';
import { getBlogPostSeo } from '../../config/blogSeo';
import { getIntentPage } from '../../config/intentPages';
import { getUsageDocsPage, usageDocsHref } from './usageDocsContent';
import { applyNoIndexSeo, applySeoMetadata } from '../../utils/seo';
import { Breadcrumbs } from '../ui/Breadcrumbs';
import { SiteFooter } from '../ui/SiteFooter';
import './BlogPostPage.css';

type BlogPostPageProps = {
  slug: string;
};

const HEADER_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Blog', href: '/blog' },
  { label: 'Usage Docs', href: '/usage-docs' },
];

const BlogPostPage = ({ slug }: BlogPostPageProps) => {
  const post = getBlogPost(slug);

  useEffect(() => {
    if (post) {
      applySeoMetadata(getBlogPostSeo(post));
      return;
    }
    applyNoIndexSeo({
      title: 'Blog Post Not Found (404) | DullyPDF',
      description: 'The requested DullyPDF blog post was not found. Use the blog index to continue browsing guides.',
      canonicalPath: '/blog',
    });
  }, [post]);

  if (!post) {
    return (
      <div className="blog-post">
        <div className="blog-post__card">
          <main className="blog-post__content">
            <p className="blog-post__not-found-code">404</p>
            <h1>Post not found</h1>
            <p>
              No DullyPDF blog post exists at <code>/blog/{slug}</code>. <a href="/blog">Back to blog</a>.
            </p>
          </main>
        </div>
      </div>
    );
  }

  const relatedIntentLinks = useMemo(
    () =>
      post.relatedIntentPages.map((key) => {
        const page = getIntentPage(key);
        return { label: page.navLabel, href: page.path };
      }),
    [post.relatedIntentPages],
  );

  const relatedDocsLinks = useMemo(
    () =>
      post.relatedDocs.map((key) => {
        const page = getUsageDocsPage(key);
        return { label: page.navLabel, href: usageDocsHref(key) };
      }),
    [post.relatedDocs],
  );

  return (
    <div className="blog-post">
      <div className="blog-post__card">
        <header className="blog-post__header">
          <div className="blog-post__brand">
            <picture>
              <source srcSet="/DullyPDFLogoImproved.webp" type="image/webp" />
              <img src="/DullyPDFLogoImproved.png" alt="DullyPDF" className="blog-post__logo" decoding="async" />
            </picture>
            <div>
              <div className="blog-post__brand-name">DullyPDF</div>
              <div className="blog-post__brand-tagline">PDF automation workflows</div>
            </div>
          </div>
          <nav className="blog-post__nav" aria-label="Primary navigation">
            {HEADER_LINKS.map((link) => (
              <a key={link.href} href={link.href} className="blog-post__nav-link">
                {link.label}
              </a>
            ))}
          </nav>
        </header>

        <main className="blog-post__content">
          <Breadcrumbs
            items={[
              { label: 'Home', href: '/' },
              { label: 'Blog', href: '/blog' },
              { label: post.title },
            ]}
          />

          <article className="blog-post__article">
            <header className="blog-post__article-header">
              <h1>{post.title}</h1>
              <div className="blog-post__meta">
                <time dateTime={post.publishedDate}>
                  {new Date(post.publishedDate + 'T00:00:00').toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })}
                </time>
                <span className="blog-post__author">by {post.author}</span>
              </div>
              <p className="blog-post__summary">{post.summary}</p>
            </header>

            {post.sections.map((section) => (
              <section key={section.id} id={section.id} className="blog-post__section">
                <h2>{section.title}</h2>
                <p>{section.body}</p>
              </section>
            ))}
          </article>

          {(relatedIntentLinks.length > 0 || relatedDocsLinks.length > 0) && (
            <aside className="blog-post__related">
              <h2>Related resources</h2>
              <div className="blog-post__related-grid">
                {relatedIntentLinks.length > 0 && (
                  <div>
                    <h3>Workflow pages</h3>
                    <ul>
                      {relatedIntentLinks.map((link) => (
                        <li key={link.href}>
                          <a href={link.href}>{link.label}</a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {relatedDocsLinks.length > 0 && (
                  <div>
                    <h3>Documentation</h3>
                    <ul>
                      {relatedDocsLinks.map((link) => (
                        <li key={link.href}>
                          <a href={link.href}>{link.label}</a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </aside>
          )}

          <div className="blog-post__cta">
            <a href="/" className="blog-post__cta-button">Try DullyPDF Now</a>
            <a href="/usage-docs/getting-started" className="blog-post__cta-link">View Getting Started Docs</a>
          </div>
        </main>
        <SiteFooter />
      </div>
    </div>
  );
};

export default BlogPostPage;
