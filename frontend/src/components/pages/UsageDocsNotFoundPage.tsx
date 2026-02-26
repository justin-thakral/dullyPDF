import { useEffect } from 'react';
import './UsageDocsNotFoundPage.css';
import { applyNoIndexSeo } from '../../utils/seo';

type UsageDocsNotFoundPageProps = {
  requestedPath: string;
};

const UsageDocsNotFoundPage = ({ requestedPath }: UsageDocsNotFoundPageProps) => {
  useEffect(() => {
    applyNoIndexSeo({
      title: 'Usage Docs Not Found (404) | DullyPDF',
      description:
        'The requested DullyPDF usage docs page was not found. Use the canonical usage docs index to continue.',
      canonicalPath: '/usage-docs',
    });
  }, []);

  return (
    <div className="usage-docs-not-found-page">
      <div className="usage-docs-not-found-card">
        <p className="usage-docs-not-found-code">404</p>
        <h1>Usage docs page not found</h1>
        <p>
          No usage docs page exists at <code>{requestedPath}</code>.
        </p>
        <a href="/usage-docs" className="usage-docs-not-found-link">
          Go to Usage Docs Overview
        </a>
      </div>
    </div>
  );
};

export default UsageDocsNotFoundPage;
