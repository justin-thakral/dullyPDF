import type { RouteSeoMetadata } from './routeSeo';
import { getBlogPosts, type BlogPost } from './blogPosts';
import { appendStructuredData, buildBreadcrumbSchema } from './seoHelpers';

export const BLOG_INDEX_SEO: RouteSeoMetadata = {
  title: 'PDF Automation Blog | DullyPDF',
  description:
    'Guides, tutorials, and best practices for converting PDFs to fillable forms, mapping fields to databases, and automating form-filling workflows.',
  canonicalPath: '/blog',
  keywords: ['pdf automation blog', 'fillable form guides', 'pdf form tutorials'],
  structuredData: [
    {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'DullyPDF Blog',
      url: 'https://dullypdf.com/blog',
      description:
        'Guides and tutorials for PDF form automation, field detection, schema mapping, and auto-fill workflows.',
    },
    buildBreadcrumbSchema([
      { label: 'Home', href: '/' },
      { label: 'Blog' },
    ]),
  ],
};

export const getBlogPostSeo = (post: BlogPost): RouteSeoMetadata => ({
  title: post.seoTitle,
  description: post.seoDescription,
  canonicalPath: `/blog/${post.slug}`,
  keywords: post.seoKeywords,
  structuredData: appendStructuredData([
    {
      '@context': 'https://schema.org',
      '@type': 'BlogPosting',
      headline: post.title,
      description: post.seoDescription,
      author: {
        '@type': 'Organization',
        name: post.author,
      },
      datePublished: post.publishedDate,
      dateModified: post.updatedDate,
      url: `https://dullypdf.com/blog/${post.slug}`,
      publisher: {
        '@type': 'Organization',
        name: 'DullyPDF',
        logo: {
          '@type': 'ImageObject',
          url: 'https://dullypdf.com/DullyPDFLogoImproved.png',
        },
      },
    },
  ], buildBreadcrumbSchema([
    { label: 'Home', href: '/' },
    { label: 'Blog', href: '/blog' },
    { label: post.title },
  ])),
});

export const resolveBlogSeo = (slug: string | undefined): RouteSeoMetadata | null => {
  if (!slug) return BLOG_INDEX_SEO;
  const posts = getBlogPosts();
  const post = posts.find((p) => p.slug === slug);
  if (!post) return null;
  return getBlogPostSeo(post);
};
