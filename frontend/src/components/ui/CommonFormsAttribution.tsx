export type CommonFormsAttributionProps = {
  className?: string;
  suffix?: string;
};

const COMMONFORMS_REPO_URL = 'https://github.com/jbarrow/commonforms';

export function CommonFormsAttribution({ className, suffix }: CommonFormsAttributionProps) {
  const label = suffix ? `CommonForms ${suffix}` : 'CommonForms';

  return (
    <span className={className}>
      {label} by{' '}
      <a className="commonforms-link" href={COMMONFORMS_REPO_URL} target="_blank" rel="noreferrer noopener">
        jbarrow
      </a>
    </span>
  );
}
