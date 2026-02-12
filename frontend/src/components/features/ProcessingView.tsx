import './ProcessingView.css';

export interface ProcessingViewProps {
  detail: string;
  showAd: boolean;
  adVideoUrl?: string;
  adPosterUrl?: string;
}

export default function ProcessingView({ detail, showAd, adVideoUrl, adPosterUrl }: ProcessingViewProps) {
  return (
    <div className="processing-indicator">
      <div className="spinner"></div>
      <h3>Preparing your form…</h3>
      <p>{detail}</p>
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
