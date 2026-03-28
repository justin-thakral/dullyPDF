import type { ChangeEvent } from 'react';
import { Alert } from '../../ui/Alert';
import type { SigningAdoptedMode } from '../../../services/api';
import { PublicSigningSignaturePad } from './PublicSigningSignaturePad';
import { getSigningStepLabel } from './publicSigningHelpers';
import type { PublicSigningFlowState } from './usePublicSigningFlow';

const VERIFICATION_CODE_INPUT_ID = 'public-signing-verification-code';
const ACCESS_CODE_INPUT_ID = 'public-signing-access-code';
const ADOPTED_NAME_INPUT_ID = 'public-signing-adopted-name';
const UPLOADED_SIGNATURE_INPUT_ID = 'public-signing-uploaded-signature';
const INTENT_CHECKBOX_ID = 'public-signing-intent-confirmed';

const SIGNATURE_MODE_OPTIONS: Array<{
  key: SigningAdoptedMode;
  label: string;
  description: string;
}> = [
  {
    key: 'typed',
    label: 'Type name',
    description: 'Type the name you want to adopt as your signature.',
  },
  {
    key: 'default',
    label: 'Use legal name',
    description: 'Use the signer name already recorded on this request.',
  },
  {
    key: 'drawn',
    label: 'Draw signature',
    description: 'Draw a handwritten mark that DullyPDF places in the signature field.',
  },
  {
    key: 'uploaded',
    label: 'Upload image',
    description: 'Upload a PNG or JPEG signature image.',
  },
];

type PublicSigningCeremonyProps = {
  flow: PublicSigningFlowState;
};

export function PublicSigningCeremony({ flow }: PublicSigningCeremonyProps) {
  if (!flow.request || !flow.showInteractiveCeremony) {
    return null;
  }

  async function handleSignatureUpload(event: ChangeEvent<HTMLInputElement>) {
    const [file] = Array.from(event.target.files || []);
    if (!file) {
      flow.setSignatureImageDataUrl(null);
      return;
    }
    if (!/^image\/(png|jpeg)$/i.test(file.type)) {
      flow.setActionError('Upload a PNG or JPEG signature image.');
      event.target.value = '';
      return;
    }
    const imageDataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('Unable to read the uploaded signature image.'));
      reader.readAsDataURL(file);
    }).catch((error: unknown) => {
      flow.setActionError(error instanceof Error ? error.message : 'Unable to read the uploaded signature image.');
      return '';
    });
    if (imageDataUrl) {
      flow.setActionError(null);
      flow.setSignatureImageDataUrl(imageDataUrl);
    }
    event.target.value = '';
  }

  return (
    <>
      <div className="public-signing-page__card public-signing-page__progress-card">
        {!flow.signingLocked ? (
          <ol className="public-signing-page__steps" aria-label="Signing progress">
            {flow.steps.map((step, index) => {
              const active = step === flow.currentStep;
              const completed = flow.steps.indexOf(flow.currentStep) > index;
              return (
                <li
                  key={step}
                  className={[
                    'public-signing-page__step',
                    active ? 'public-signing-page__step--active' : '',
                    completed ? 'public-signing-page__step--complete' : '',
                  ].filter(Boolean).join(' ')}
                >
                  <span>{index + 1}</span>
                  <strong>{getSigningStepLabel(step)}</strong>
                </li>
              );
            })}
          </ol>
        ) : flow.consentWithdrawnLocked ? (
          <Alert
            tone="warning"
            variant="inline"
            message="Electronic consent was withdrawn for this signing request. Contact the sender to proceed with a paper or manual alternative."
          />
        ) : (
          <Alert
            tone="success"
            variant="inline"
            message="A paper/manual fallback request was recorded for this signer. Electronic signing is now paused until the sender follows up."
          />
        )}

        <div className="public-signing-page__button-group public-signing-page__button-group--secondary">
          {flow.request.status !== 'completed' && flow.request.signatureMode === 'consumer' && flow.request.consentedAt && !flow.request.consentWithdrawnAt && !flow.request.completedAt ? (
            <button
              className="ui-button ui-button--ghost"
              type="button"
              disabled={flow.busyAction !== null || flow.missingSession}
              onClick={flow.handleWithdrawConsent}
            >
              Withdraw electronic consent
            </button>
          ) : null}

          {flow.request.status !== 'completed' && flow.request.manualFallbackEnabled ? (
            flow.request.manualFallbackRequestedAt ? null : (
              <button
                className="ui-button ui-button--ghost"
                type="button"
                disabled={flow.busyAction !== null || flow.missingSession}
                onClick={flow.handleManualFallback}
              >
                Request paper/manual fallback
              </button>
            )
          ) : null}

          {flow.canOpenSourceDocument ? (
            <button
              className="ui-button ui-button--ghost"
              type="button"
              disabled={flow.artifactBusyKey !== null || !flow.documentObjectUrl || flow.documentLoading}
              onClick={() => flow.handleOpenDocument('The immutable signing document is not available yet.')}
            >
              {flow.documentLoading ? 'Loading document…' : 'Open document in new tab'}
            </button>
          ) : null}
        </div>
      </div>

      {flow.actionError ? <Alert tone="error" variant="inline" message={flow.actionError} /> : null}
      {flow.missingSession ? <Alert tone="warning" variant="inline" message={flow.sessionErrorMessage} /> : null}

      {!flow.signingLocked && flow.currentStep === 'verify' ? (
        <div className="public-signing-page__card">
          <h2>Verify your email</h2>
          <p className="public-signing-page__support">
            Before DullyPDF reveals the frozen signing record, verify the signer inbox on file.
            {flow.request.signerEmailHint ? ` The code will be sent to ${flow.request.signerEmailHint}.` : ''}
          </p>
          {flow.session?.verificationSentAt ? (
            <p className="public-signing-page__support">
              A 6-digit code was sent{flow.verificationExpiresLabel ? ` and expires at ${flow.verificationExpiresLabel}` : ''}.
              {flow.resendBlocked && flow.resendAvailableLabel ? ` You can request another code after ${flow.resendAvailableLabel}.` : ''}
            </p>
          ) : (
            <p className="public-signing-page__support">
              Request a one-time 6-digit code, then enter it below to continue into the signing ceremony.
            </p>
          )}
          <label className="public-signing-page__field">
            <span>Verification code</span>
            <input
              id={VERIFICATION_CODE_INPUT_ID}
              name="verificationCode"
              value={flow.verificationCode}
              onChange={(event) => flow.setVerificationCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="Enter the 6-digit code"
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
            />
          </label>
          <div className="public-signing-page__button-group">
            <button
              className="ui-button ui-button--ghost"
              type="button"
              disabled={flow.busyAction !== null || flow.missingSession || flow.resendBlocked}
              onClick={flow.handleSendCode}
            >
              {flow.busyAction === 'sendCode'
                ? 'Sending code…'
                : flow.session?.verificationSentAt
                  ? 'Resend code'
                  : 'Send code'}
            </button>
            <button
              className="ui-button ui-button--primary"
              type="button"
              disabled={flow.busyAction !== null || flow.missingSession || flow.verificationCodeTrimmed.length !== 6}
              onClick={flow.handleVerifyCode}
            >
              {flow.busyAction === 'verifyCode' ? 'Verifying…' : 'Verify code'}
            </button>
          </div>
        </div>
      ) : null}

      {!flow.signingLocked && flow.currentStep === 'consent' ? (
        <div className="public-signing-page__card">
          <h2>Consent to electronic records</h2>
          <p className="public-signing-page__support">
            Consumer signing requests require a separate electronic-records consent before DullyPDF continues to the immutable document review.
          </p>
          {flow.request.senderDisplayName || flow.request.senderContactEmail ? (
            <p className="public-signing-page__support">
              <strong>Sender:</strong>{' '}
              {[flow.request.senderDisplayName, flow.request.senderContactEmail].filter(Boolean).join(' · ')}
            </p>
          ) : null}
          <ul className="public-signing-page__list">
            {flow.consumerDisclosureLines.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {flow.consumerDisclosure?.scope ? (
            <p className="public-signing-page__support"><strong>Scope:</strong> {flow.consumerDisclosure.scope}</p>
          ) : null}
          {flow.consumerDisclosure?.withdrawal?.instructions ? (
            <p className="public-signing-page__support">
              <strong>Withdrawal:</strong> {flow.consumerDisclosure.withdrawal.instructions}
            </p>
          ) : null}
          {flow.consumerDisclosure?.withdrawal?.consequences ? (
            <p className="public-signing-page__support">
              <strong>Consequence:</strong> {flow.consumerDisclosure.withdrawal.consequences}
            </p>
          ) : null}
          {flow.consumerDisclosure?.contactUpdates ? (
            <p className="public-signing-page__support">
              <strong>Contact updates:</strong> {flow.consumerDisclosure.contactUpdates}
            </p>
          ) : null}
          {flow.consumerDisclosure?.paperCopy ? (
            <p className="public-signing-page__support">
              <strong>Paper copy:</strong> {flow.consumerDisclosure.paperCopy}
            </p>
          ) : null}
          {flow.consumerDisclosure?.paperOption?.instructions ? (
            <p className="public-signing-page__support">
              <strong>Paper/manual option:</strong> {flow.consumerDisclosure.paperOption.instructions}
            </p>
          ) : null}
          {flow.consumerDisclosure?.paperOption?.fees ? (
            <p className="public-signing-page__support">
              <strong>Fees:</strong> {flow.consumerDisclosure.paperOption.fees}
            </p>
          ) : null}
          {flow.consumerHardwareRequirements.length ? (
            <>
              <p className="public-signing-page__support"><strong>Hardware and software requirements</strong></p>
              <ul className="public-signing-page__list">
                {flow.consumerHardwareRequirements.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
          {flow.consumerAccessPath ? (
            <>
              <p className="public-signing-page__support">
                <strong>Access check:</strong>{' '}
                {flow.consumerDisclosure?.accessCheck?.instructions || 'Open the PDF access check and enter the code shown there.'}
              </p>
              <div className="public-signing-page__document-frame">
                <iframe title="Consumer access check PDF" src={flow.consumerAccessPath} />
              </div>
              <div className="public-signing-page__button-group public-signing-page__button-group--secondary">
                <a className="ui-button ui-button--ghost" href={flow.consumerAccessPath} target="_blank" rel="noreferrer">
                  Open access-check PDF in new tab
                </a>
              </div>
            </>
          ) : null}
          <label className="public-signing-page__field">
            <span>Access code</span>
            <input
              id={ACCESS_CODE_INPUT_ID}
              name="accessCode"
              value={flow.accessCode}
              onChange={(event) => flow.setAccessCode(event.target.value.toUpperCase())}
              placeholder="Enter the 6-character code from the PDF"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <button
            className="ui-button ui-button--primary"
            type="button"
            disabled={flow.busyAction !== null || flow.missingSession || !flow.accessCode.trim()}
            onClick={flow.handleConsent}
          >
            {flow.busyAction === 'consent' ? 'Saving consent…' : 'I consent to electronic records'}
          </button>
        </div>
      ) : null}

      {!flow.signingLocked && flow.currentStep === 'review' ? (
        <div className="public-signing-page__card">
          <h2>Review the exact record</h2>
          <p className="public-signing-page__support">
            Review the immutable PDF below. Your signature will be tied to this exact source hash and version.
          </p>
          {flow.documentError ? <Alert tone="error" variant="inline" message={flow.documentError} /> : null}
          {flow.documentLoading ? <p className="public-signing-page__support">Loading the immutable signing document…</p> : null}
          {flow.documentObjectUrl ? (
            <div className="public-signing-page__document-frame">
              <iframe title="Signing document preview" src={flow.documentObjectUrl} />
            </div>
          ) : null}
          <button
            className="ui-button ui-button--primary"
            type="button"
            disabled={flow.busyAction !== null || flow.missingSession || flow.documentLoading || !flow.documentObjectUrl}
            onClick={flow.handleReview}
          >
            {flow.busyAction === 'review' ? 'Recording review…' : 'I reviewed this document'}
          </button>
        </div>
      ) : null}

      {!flow.signingLocked && flow.currentStep === 'adopt' ? (
        <div className="public-signing-page__card">
          <h2>Adopt your signature</h2>
          <p className="public-signing-page__support">
            Choose how you want DullyPDF to render your signature on this request, then adopt that exact signature before the final sign action.
          </p>
          <div className="public-signing-page__signature-mode-grid" role="radiogroup" aria-label="Signature style">
            {SIGNATURE_MODE_OPTIONS.map((option) => (
              <button
                key={option.key}
                className={[
                  'public-signing-page__signature-mode',
                  flow.signatureType === option.key ? 'public-signing-page__signature-mode--active' : '',
                ].filter(Boolean).join(' ')}
                type="button"
                role="radio"
                aria-checked={flow.signatureType === option.key}
                onClick={() => flow.setSignatureType(option.key)}
              >
                <strong>{option.label}</strong>
                <span>{option.description}</span>
              </button>
            ))}
          </div>
          {flow.signatureType === 'typed' ? (
            <label className="public-signing-page__field">
              <span>Adopted signature name</span>
              <input
                id={ADOPTED_NAME_INPUT_ID}
                name="adoptedSignatureName"
                value={flow.adoptedName}
                onChange={(event) => flow.setAdoptedName(event.target.value)}
                placeholder={flow.request.signerName}
                autoComplete="name"
                maxLength={200}
              />
            </label>
          ) : null}
          {flow.signatureType === 'default' ? (
            <div className="public-signing-page__signature-helper">
              DullyPDF will use the signer name on this request: <strong>{flow.request.signerName}</strong>.
            </div>
          ) : null}
          {flow.signatureType === 'drawn' ? (
            <PublicSigningSignaturePad
              value={flow.signatureImageDataUrl}
              onChange={flow.setSignatureImageDataUrl}
            />
          ) : null}
          {flow.signatureType === 'uploaded' ? (
            <div className="public-signing-page__upload-shell">
              <label className="public-signing-page__field">
                <span>Upload signature image</span>
                <input
                  id={UPLOADED_SIGNATURE_INPUT_ID}
                  name="uploadedSignatureImage"
                  type="file"
                  accept="image/png,image/jpeg"
                  onChange={handleSignatureUpload}
                />
              </label>
              <p className="public-signing-page__support">
                Upload a tightly cropped PNG or JPEG signature image. DullyPDF normalizes the image before it is written into the signed PDF.
              </p>
              {flow.signatureImageDataUrl ? (
                <div className="public-signing-page__button-group public-signing-page__button-group--secondary">
                  <button
                    className="ui-button ui-button--ghost"
                    type="button"
                    onClick={() => flow.setSignatureImageDataUrl(null)}
                  >
                    Remove uploaded image
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="public-signing-page__signature-preview" aria-live="polite">
            <span>Signature preview</span>
            {flow.signatureType === 'drawn' || flow.signatureType === 'uploaded' ? (
              flow.signatureImageDataUrl ? (
                <img
                  className="public-signing-page__signature-preview-image"
                  src={flow.signatureImageDataUrl}
                  alt="Signature preview"
                />
              ) : (
                <strong>Awaiting signature image</strong>
              )
            ) : (
              <strong>{flow.previewSignatureName}</strong>
            )}
          </div>
          <button
            className="ui-button ui-button--primary"
            type="button"
            disabled={flow.busyAction !== null || flow.missingSession || !flow.canSubmitAdoptedSignature}
            onClick={flow.handleAdopt}
          >
            {flow.busyAction === 'adopt' ? 'Saving signature…' : 'Adopt this signature'}
          </button>
        </div>
      ) : null}

      {!flow.signingLocked && flow.currentStep === 'complete' ? (
        <div className="public-signing-page__card">
          <h2>Finish signing</h2>
          <p className="public-signing-page__support">
            This is the final signing action. DullyPDF records the timestamp, secure signing session, device information, and document hash for this request.
          </p>
          <label className="public-signing-page__checkbox">
            <input
              id={INTENT_CHECKBOX_ID}
              name="intentConfirmed"
              type="checkbox"
              checked={flow.intentConfirmed}
              onChange={(event) => flow.setIntentConfirmed(event.target.checked)}
            />
            <span>I adopt this signature and sign this exact record electronically.</span>
          </label>
          <button
            className="ui-button ui-button--primary"
            type="button"
            disabled={flow.busyAction !== null || flow.missingSession || !flow.intentConfirmed}
            onClick={flow.handleComplete}
          >
            {flow.busyAction === 'complete' ? 'Finishing signing…' : 'Finish Signing'}
          </button>
        </div>
      ) : null}
    </>
  );
}
