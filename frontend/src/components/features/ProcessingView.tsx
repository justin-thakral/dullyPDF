import './ProcessingView.css';

export interface ProcessingViewProps {
  heading: string;
  detail: string;
  showAd: boolean;
  adVideoUrl?: string;
  adPosterUrl?: string;
}

export default function ProcessingView({
  heading,
  detail,
  showAd,
  adVideoUrl,
  adPosterUrl,
}: ProcessingViewProps) {
  const hasDetail = detail.trim().length > 0;
  return (
    <div className="processing-indicator">
      <div className="spinner"></div>
      <h3>{heading}</h3>
      {hasDetail ? <p>{detail}</p> : null}
      {showAd && adVideoUrl ? (
        <div className="processing-ad" aria-live="polite">
          <video className="processing-ad__video" src={adVideoUrl}
            poster={adPosterUrl || undefined} autoPlay muted loop playsInline preload="auto" />
          <p className="processing-ad__note">This short video runs while field detection finishes on the backend. It helps cover hosting so the tool can stay free.</p>
        </div>
      ) : null}
    </div>
  );
}
