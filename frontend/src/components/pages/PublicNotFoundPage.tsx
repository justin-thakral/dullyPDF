import { useEffect } from 'react';
import './PublicNotFoundPage.css';
import { applyNoIndexSeo } from '../../utils/seo';

type PublicNotFoundPageProps = {
  requestedPath: string;
};

const PublicNotFoundPage = ({ requestedPath }: PublicNotFoundPageProps) => {
  useEffect(() => {
    applyNoIndexSeo({
      title: 'Page Not Found (404) | DullyPDF',
      description:
        'The requested DullyPDF page was not found. Return to the homepage, workflow library, or usage docs to continue.',
      canonicalPath: '/',
    });
  }, []);

  return (
    <div className="public-not-found-page">
      <div className="public-not-found-card">
        <p className="public-not-found-code">404</p>
        <h1>Page not found</h1>
        <p>
          No public page exists at <code>{requestedPath}</code>.
        </p>
        <div className="public-not-found-links">
          <a href="/">Go to Homepage</a>
          <a href="/workflows">Browse Workflows</a>
          <a href="/usage-docs">Open Usage Docs</a>
        </div>
      </div>
    </div>
  );
};

export default PublicNotFoundPage;
