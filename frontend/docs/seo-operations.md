# SEO Operations Playbook

This playbook covers ongoing work that complements route-level SEO implementation.

## Weekly Search Console workflow

Run this every week for the previous 7 days:

1. Open Google Search Console `Performance` report for `https://dullypdf.com`.
2. Export top queries, pages, clicks, impressions, CTR, and average position.
3. Segment by intent buckets:
   - `pdf to fillable form`
   - `pdf to database template`
   - `fill pdf from csv`
   - `fill information in pdf`
   - `fillable form field name`
   - `automate medical intake forms`
   - `acord form automation`
   - `automate rental application pdf`
   - `government form automation`
   - `loan application pdf automation`
   - `automate hr onboarding forms`
   - `legal pdf workflow automation`
   - `automate student application pdfs`
   - `nonprofit pdf form automation`
   - `transport pdf automation`
4. For each bucket, map query -> landing page and record:
   - Query
   - Target page
   - Current title
   - Current meta description
   - CTR
   - Position
   - Action
5. Apply changes when:
   - impressions are rising but CTR is weak (rewrite title/description),
   - position is improving but page intent mismatch is visible (update on-page copy + links),
   - query does not have a matching landing page (create a new intent page).

## Monthly authority signals plan

Authority growth is not a one-time code change. Use this recurring plan:

1. Publish one public workflow example per month:
   - source form type,
   - detection + mapping strategy,
   - search/fill validation approach,
   - output quality notes.
2. Turn each example into a short case-study post that links to the matching intent landing page.
3. Share each post in relevant communities and partner channels (healthcare ops, legal ops, intake automation, no-code ops).
4. Track referring domains and new backlinks in Search Console + GA referral traffic.
5. Keep internal links updated:
   - intent pages -> other intent pages,
   - intent pages -> docs sections,
   - docs sections -> matching intent pages.

## Query-to-page mapping

- `/pdf-to-fillable-form`: convert raw PDFs to fillable templates.
- `/pdf-to-database-template`: map fields to database/schema columns.
- `/fill-pdf-from-csv`: row-based PDF filling from CSV/XLSX/JSON.
- `/fill-information-in-pdf`: broad informational fill intent.
- `/fillable-form-field-name`: field naming normalization and mapping quality.
- `/healthcare-pdf-automation`: healthcare intake, registration, and HIPAA/consent forms.
- `/acord-form-automation`: insurance workflows including ACORD-style form automation.
- `/real-estate-pdf-automation`: rental, lease, and mortgage packet workflows.
- `/government-form-automation`: permit, tax, and licensing form workflows.
- `/finance-loan-pdf-automation`: loan application and financial disclosure workflows.
- `/hr-pdf-automation`: onboarding, benefits, and HR document workflows.
- `/legal-pdf-workflow-automation`: legal contracts, filings, and case packet workflows.
- `/education-form-automation`: student application and enrollment workflow coverage.
- `/nonprofit-pdf-form-automation`: grants, volunteer, and nonprofit intake workflows.
- `/logistics-pdf-automation`: bill of lading, delivery, and transport paperwork workflows.

## Reporting template

Use this table in weekly updates:

| Week | Query cluster | Landing page | Impressions | CTR | Position | Action taken | Result next week |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-02-25 | fill pdf from csv | /fill-pdf-from-csv | - | - | - | Initial launch | Pending |
