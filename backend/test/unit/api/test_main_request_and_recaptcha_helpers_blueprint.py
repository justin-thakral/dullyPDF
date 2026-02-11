"""Blueprint for unit tests of contact + reCAPTCHA helpers in `backend/main.py`.

Required coverage:
- Pydantic validators for `ContactRequest` and `RecaptchaAssessmentRequest`
- `_resolve_client_ip`, `_is_public_ip`
- `_recaptcha_hostname_allowed`
- `_verify_recaptcha_token` validation flow
- `_resolve_contact_subject`, `_resolve_contact_body`
- `_sanitize_email_header_value`, `_format_reply_to_header`
- `_send_contact_email` failure and success paths

Edge cases:
- action mismatch, score too low, invalid token reason
- missing recaptcha config in required vs optional mode
- CRLF header injection in subject/reply-to data

Important context:
- These are public endpoints and high-risk for abuse/misconfiguration.
"""
