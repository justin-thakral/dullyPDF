import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BlogPostPage from '../../../../src/components/pages/BlogPostPage';

describe('BlogPostPage', () => {
  it('applies noindex metadata when the requested blog slug does not exist', () => {
    render(<BlogPostPage slug="not-a-real-post" />);

    expect(screen.getByRole('heading', { name: 'Post not found' })).toBeTruthy();
    expect(screen.getByText('/blog/not-a-real-post')).toBeTruthy();
    expect(document.title).toBe('Blog Post Not Found (404) | DullyPDF');
    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex,follow');
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://dullypdf.com/blog');
  });
});
