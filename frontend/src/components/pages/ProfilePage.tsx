/**
 * User profile overview with tier limits and saved forms.
 */
import React, { useMemo, useState } from 'react';
import './ProfilePage.css';
import type { ProfileLimits, SavedFormSummary } from '../../api';

interface ProfilePageProps {
  email?: string | null;
  role?: string | null;
  creditsRemaining?: number | null;
  isLoading?: boolean;
  limits: ProfileLimits;
  savedForms: SavedFormSummary[];
  onSelectSavedForm: (formId: string) => void;
  onDeleteSavedForm?: (formId: string) => void;
  deletingFormId?: string | null;
  onClose: () => void;
  onSignOut?: () => void;
}

/**
 * Render a dedicated profile screen with tier details and saved forms.
 */
const ProfilePage: React.FC<ProfilePageProps> = ({
  email,
  role,
  creditsRemaining,
  isLoading = false,
  limits,
  savedForms,
  onSelectSavedForm,
  onDeleteSavedForm,
  deletingFormId,
  onClose,
  onSignOut,
}) => {
  const [query, setQuery] = useState('');
  const normalizedRole = role === 'god' ? 'God' : 'Basic';
  const initial = (email || 'U').charAt(0).toUpperCase();
  const creditsLabel = role === 'god' ? 'Unlimited' : String(creditsRemaining ?? 0);

  const filteredForms = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    if (!trimmed) return savedForms;
    return savedForms.filter((form) => form.name.toLowerCase().includes(trimmed));
  }, [query, savedForms]);

  return (
    <div className="profile-page">
      <div className="profile-shell">
        <header className="profile-header">
          <button type="button" className="profile-back" onClick={onClose}>
            ← Back to workspace
          </button>
          <div className="profile-identity">
            <div className="profile-avatar" aria-hidden="true">
              {initial}
            </div>
            <div>
              <p className="profile-email">{email || 'User profile'}</p>
              <div className="profile-tier">
                <span>{normalizedRole} tier</span>
              </div>
            </div>
          </div>
          {onSignOut ? (
            <button type="button" className="profile-signout" onClick={onSignOut}>
              Sign out
            </button>
          ) : null}
        </header>

        {isLoading ? (
          <div className="profile-loading" role="status" aria-live="polite">
            Loading profile details…
          </div>
        ) : null}

        <section className="profile-metrics">
          <div className="metric-card">
            <span className="metric-label">OpenAI credits left</span>
            <span className="metric-value">{creditsLabel}</span>
            <p className="metric-note">Credits are consumed per page during rename or mapping.</p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Max pages per scan</span>
            <span className="metric-value">{limits.detectMaxPages}</span>
            <p className="metric-note">Detection uploads over this size are blocked.</p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Max fillable pages</span>
            <span className="metric-value">{limits.fillableMaxPages}</span>
            <p className="metric-note">Applies to local fillable template uploads.</p>
          </div>
          <div className="metric-card">
            <span className="metric-label">Saved forms limit</span>
            <span className="metric-value">{limits.savedFormsMax}</span>
            <p className="metric-note">Delete older forms to make room.</p>
          </div>
        </section>

        <section className="profile-saved">
          <div className="profile-saved-header">
            <div>
              <h2>Saved Forms (max {limits.savedFormsMax})</h2>
              <p>{savedForms.length} total saved</p>
            </div>
            <div className="profile-search">
              <input
                type="search"
                id="saved-form-search"
                name="saved-form-search"
                placeholder="Search saved forms"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search saved forms"
              />
            </div>
          </div>
          {filteredForms.length === 0 ? (
            <div className="profile-empty">
              <p>No saved forms match your search.</p>
            </div>
          ) : (
            <div className="profile-saved-list" role="list">
              {filteredForms.map((form) => {
                const isDeleting = deletingFormId === form.id;
                return (
                  <div key={form.id} className="saved-form-pill" role="listitem">
                    <button
                      type="button"
                      className="saved-form-pill__name"
                      onClick={() => onSelectSavedForm(form.id)}
                      title={form.name}
                      disabled={isDeleting}
                    >
                      {form.name}
                    </button>
                    {onDeleteSavedForm ? (
                      <button
                        type="button"
                        className="saved-form-pill__delete"
                        onClick={() => onDeleteSavedForm(form.id)}
                        aria-label={`Delete saved form ${form.name}`}
                        disabled={isDeleting}
                      >
                        X
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default ProfilePage;
