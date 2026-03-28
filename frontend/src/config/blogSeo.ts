import type { BlogPost } from './blogPosts';
import {
  BLOG_INDEX_SEO,
  resolveBlogRouteSeo,
  type RouteSeoMetadata,
} from './routeSeo';

export { BLOG_INDEX_SEO };

export const getBlogPostSeo = (post: BlogPost): RouteSeoMetadata =>
  resolveBlogRouteSeo(post.slug) ?? BLOG_INDEX_SEO;

export const resolveBlogSeo = (slug: string | undefined): RouteSeoMetadata | null =>
  resolveBlogRouteSeo(slug);
