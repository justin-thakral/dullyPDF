import { useEffect, useMemo } from 'react';
import { getBlogPost } from '../../config/blogPosts';
import { getBlogPostSeo } from '../../config/blogSeo';
import { getIntentPage } from '../../config/intentPages';
import { getUsageDocsPage, usageDocsHref } from './usageDocsContent';
import { applyNoIndexSeo, applySeoMetadata } from '../../utils/seo';
import { Breadcrumbs } from '../ui/Breadcrumbs';
import { PublicSiteFrame } from '../ui/PublicSiteFrame';
import './BlogPostPage.css';

type BlogPostPageProps = {
  slug: string;
};

const formatDisplayDate = (date: string): string =>
  new Date(`${date}T00:00:00`).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

const BlogPostPage = ({ slug }: BlogPostPageProps) => {
  const post = getBlogPost(slug);
  const relatedIntentLinks = useMemo(
    () => (post
      ? post.relatedIntentPages.map((key) => {
        const page = getIntentPage(key);
        return { label: page.navLabel, href: page.path };
      })
      : []),
    [post],
  );
  const relatedDocsLinks = useMemo(
    () => (post
      ? post.relatedDocs.map((key) => {
        const page = getUsageDocsPage(key);
        return { label: page.navLabel, href: usageDocsHref(key) };
      })
      : []),
    [post],
  );
  const inlineResourceLinks = useMemo(
    () => [...relatedIntentLinks.slice(0, 2), ...relatedDocsLinks.slice(0, 2)],
    [relatedDocsLinks, relatedIntentLinks],
  );
  const nextStepLinks = useMemo(
    () => [...relatedIntentLinks, ...relatedDocsLinks].slice(0, 4),
    [relatedDocsLinks, relatedIntentLinks],
  );

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
      <PublicSiteFrame activeNavKey="blog" bodyClassName="blog-post__content">
        <div className="blog-post blog-post--not-found">
          <section className="blog-post__not-found">
            <p className="blog-post__not-found-code">404</p>
            <h1>Post not found</h1>
            <p>
              No DullyPDF blog post exists at <code>/blog/{slug}</code>. <a href="/blog">Back to blog</a>.
            </p>
          </section>
        </div>
      </PublicSiteFrame>
    );
  }

  const publishedDateLabel = formatDisplayDate(post.publishedDate);
  const updatedDateLabel = formatDisplayDate(post.updatedDate);
  const showUpdatedDate = post.updatedDate !== post.publishedDate;

  return (
    <PublicSiteFrame activeNavKey="blog" bodyClassName="blog-post__content">
      <div className="blog-post">
        <div className="blog-post__main">
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
                <span className="blog-post__meta-label">Published</span>
                <time dateTime={post.publishedDate}>{publishedDateLabel}</time>
                {showUpdatedDate ? (
                  <>
                    <span className="blog-post__meta-separator" aria-hidden="true">•</span>
                    <span className="blog-post__meta-label">Last updated</span>
                    <time dateTime={post.updatedDate}>{updatedDateLabel}</time>
                  </>
                ) : null}
                <span className="blog-post__author">by {post.author}</span>
              </div>
              <p className="blog-post__summary">{post.summary}</p>
              {inlineResourceLinks.length > 0 ? (
                <div className="blog-post__inline-links" aria-label="Key workflow links">
                  <span className="blog-post__inline-links-label">Key workflow links</span>
                  <div className="blog-post__inline-links-list">
                    {inlineResourceLinks.map((link) => (
                      <a key={link.href} href={link.href} className="blog-post__inline-link">
                        {link.label}
                      </a>
                    ))}
                  </div>
                </div>
              ) : null}
            </header>

            {post.sections.map((section) => (
              <section key={section.id} id={section.id} className="blog-post__section">
                <h2>{section.title}</h2>
                <p>{section.body}</p>
              </section>
            ))}

            <section className="blog-post__section">
              <h2>How to validate this workflow in DullyPDF</h2>
              <p>
                The fastest way to get value from this guide is to test one recurring PDF, not every variation at once.
                Build or reopen one representative template, review the risky fields first, and keep the first QA loop narrow.
              </p>
              <ol>
                <li>Choose one recurring document and clean the field set before you optimize for volume.</li>
                <li>Rename or map the template only after geometry, checkbox groups, and dates look stable.</li>
                <li>Fill one realistic record, inspect the output PDF, then clear and fill again.</li>
                <li>Only after that should you publish a link, group templates, or route the workflow into API Fill or signing.</li>
              </ol>
            </section>

            {nextStepLinks.length > 0 ? (
              <section className="blog-post__section">
                <h2>Choose the right next route</h2>
                <p>
                  Blog posts are strongest when they lead into a focused route or docs page. Use the links below to move
                  from the article into the exact workflow, operator guide, or product surface that matches your next step.
                </p>
                <ul>
                  {nextStepLinks.map((link) => (
                    <li key={link.href}>
                      <a href={link.href}>{link.label}</a>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </article>

          {(relatedIntentLinks.length > 0 || relatedDocsLinks.length > 0) && (
            <section className="blog-post__panel">
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
            </section>
          )}

          <section className="blog-post__panel blog-post__panel--cta">
            <h2>Continue into the product</h2>
            <p>
              Use the article as the starting point, then move into one focused DullyPDF workflow validation pass.
            </p>
            <div className="blog-post__cta">
              <a href="/" className="blog-post__cta-button">Try DullyPDF Now</a>
              <a href="/usage-docs/getting-started" className="blog-post__cta-link">View Getting Started Docs</a>
            </div>
          </section>
        </div>
      </div>
    </PublicSiteFrame>
  );
};

export default BlogPostPage;
