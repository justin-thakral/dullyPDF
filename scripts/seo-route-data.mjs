/**
 * SEO route data module — plain JS export of all route metadata and body content.
 * Used by generate-static-html.mjs and generate-sitemap.mjs at build time.
 *
 * Sources:
 *  - routeSeo.ts (titles, descriptions, keywords, canonical paths, structured data)
 *  - intentPages.ts (heroTitle, heroSummary, valuePoints, proofPoints, faqs)
 *  - usageDocsContent.tsx (section titles and summaries)
 */

export const SITE_ORIGIN = 'https://dullypdf.com';
export const DEFAULT_SOCIAL_IMAGE_PATH = '/DullyPDFLogoImproved.png';

// ---------------------------------------------------------------------------
// Intent pages
// ---------------------------------------------------------------------------

const INTENT_PAGES = [
  {
    key: 'pdf-to-fillable-form',
    category: 'workflow',
    path: '/pdf-to-fillable-form',
    navLabel: 'PDF to Fillable Form',
    heroTitle: 'Convert PDF to Fillable Form Templates in Minutes',
    heroSummary:
      'Upload a raw PDF, detect candidate fields, clean geometry in the editor, and save a reusable fillable template for repeat workflows.',
    seoTitle: 'PDF to Fillable Form Workflow for Reusable Templates | DullyPDF',
    seoDescription:
      'Convert PDF files into fillable form templates with a PDF form builder workflow built for existing documents, validate field geometry, and reuse saved forms for repeat workflows in DullyPDF.',
    seoKeywords: ['pdf to fillable form', 'pdf form builder', 'build fillable form from pdf', 'fillable pdf builder', 'convert pdf to fillable template', 'fillable form template workflow'],
    valuePoints: [
      'Convert scanned or native PDFs into editable fillable templates.',
      'Review field candidates with confidence scoring before finalizing.',
      'Use visual tools to resize, rename, and type fields with precision.',
    ],
    proofPoints: [
      'Supports PDF uploads up to 50MB.',
      'Search & Fill uses local CSV/XLSX/JSON rows in-browser.',
      'Templates can be saved and reopened for repeat intake cycles.',
    ],
    faqs: [
      { question: 'Can DullyPDF convert non-fillable PDFs into fillable forms?', answer: 'Yes. DullyPDF detects likely field regions, then lets you refine and save them as a fillable template.' },
      { question: 'Do I need to edit the PDF file directly?', answer: 'No. You edit overlay field metadata and geometry in the app, without changing the source PDF layout.' },
      { question: 'Can I reuse a converted fillable template later?', answer: 'Yes. Saved forms preserve PDF bytes and field metadata so you can reopen and refill without rerunning full setup.' },
    ],
  },
  {
    key: 'pdf-to-database-template',
    category: 'workflow',
    path: '/pdf-to-database-template',
    navLabel: 'PDF to Database Template',
    heroTitle: 'Map PDF Fields to Database Template Columns',
    heroSummary:
      'Standardize field names, align them to schema headers, and build repeatable PDF-to-database templates for intake operations.',
    seoTitle: 'PDF to Database Template Mapping Guide | DullyPDF',
    seoDescription:
      'Map PDF field names to database template columns and maintain repeatable PDF fill workflows with schema-aligned templates.',
    seoKeywords: ['pdf to database template', 'map pdf fields to database columns', 'pdf schema mapping workflow'],
    valuePoints: [
      'Map detected fields to CSV/XLSX/JSON schema headers.',
      'Use OpenAI rename + mapping for faster standardization.',
      'Keep checkbox groups and option keys aligned to data columns.',
    ],
    proofPoints: [
      'Schema metadata can be persisted for template remap workflows.',
      'Mapping and rename confidence outputs are visible for review.',
      'Works for recurring packets where naming is inconsistent.',
    ],
    faqs: [
      { question: 'How is a PDF database template different from a normal fillable PDF?', answer: 'A database template is explicitly mapped to data headers so rows can be filled predictably instead of manually.' },
      { question: 'Can I map checkboxes to database values?', answer: 'Yes. DullyPDF supports checkbox grouping metadata and rule-based mapping for boolean, enum, and list-style values.' },
      { question: 'Can I update mappings later?', answer: 'Yes. Saved templates can be reopened, remapped, and retested as your schema evolves.' },
    ],
  },
  {
    key: 'fill-pdf-from-csv',
    category: 'workflow',
    path: '/fill-pdf-from-csv',
    navLabel: 'Fill PDF From CSV',
    heroTitle: 'Fill PDF From CSV, Excel, or JSON Data',
    heroSummary:
      'Search your records, pick a row, and fill mapped PDF templates in seconds for repeat data-entry workflows.',
    seoTitle: 'Fill PDF From CSV, Excel, and JSON Records | DullyPDF',
    seoDescription:
      'Fill mapped PDF templates from CSV, Excel, and JSON records with search-based row selection and controlled validation loops.',
    seoKeywords: ['fill pdf from csv', 'fill pdf from excel', 'fill pdf from json'],
    valuePoints: [
      'Load CSV, XLSX, or JSON rows and search records quickly.',
      'Choose contains/equals matching and fill by selected row.',
      'Use clear + refill loops to validate mapping quality before export.',
    ],
    proofPoints: [
      'Search result sets are capped for controlled review workflows.',
      'Parser guardrails handle duplicate headers and schema normalization.',
      'Filled output can be downloaded immediately or saved to profile.',
    ],
    faqs: [
      { question: 'Can I fill a PDF directly from CSV rows?', answer: 'Yes. After mapping, select a row in Search & Fill and DullyPDF writes matching values into PDF fields.' },
      { question: 'Does DullyPDF support Excel files too?', answer: 'Yes. XLSX is supported alongside CSV and JSON for row-based Search & Fill workflows.' },
      { question: 'What if some fields do not fill correctly?', answer: 'Review mappings and checkbox rules, then run a clear-and-refill verification pass before production output.' },
    ],
  },
  {
    key: 'fill-pdf-by-link',
    category: 'workflow',
    path: '/fill-pdf-by-link',
    navLabel: 'Fill PDF By Link',
    heroTitle: 'Collect PDF Answers With Native Fill By Link',
    heroSummary:
      'Start from a saved DullyPDF template, publish a mobile-friendly form link, collect respondent answers, and generate the filled PDF only when you need it.',
    seoTitle: 'Fill PDF By Link With Shareable Respondent Forms | DullyPDF',
    seoDescription:
      'Publish a native Fill By Link from a saved PDF template, collect respondent answers in a DullyPDF-hosted HTML form, and generate the filled PDF from the response list when needed.',
    seoKeywords: ['fill pdf by link', 'shareable pdf form link', 'pdf form respondent link', 'collect pdf form responses', 'html form to fill pdf'],
    valuePoints: [
      'Publish a DullyPDF-hosted HTML form from any saved template.',
      'Store respondent answers as structured records under the template owner account.',
      'Pick a respondent later in the workspace and fill the source PDF on demand.',
    ],
    proofPoints: [
      'Free includes 1 active published link and up to 5 accepted responses.',
      'Premium unlocks a shareable link for every saved template with up to 10,000 responses per link.',
      'Respondent records can be reused through the same Search & Fill workflow before download.',
    ],
    faqs: [
      { question: 'Does the respondent fill the actual PDF?', answer: 'No. The respondent fills a DullyPDF-hosted mobile-friendly HTML form, and the owner generates the final PDF from the saved response later.' },
      { question: 'How many Fill By Link responses are allowed on free and premium?', answer: 'Free includes 1 active link with 5 accepted responses. Premium supports a shareable link on every saved template and up to 10,000 accepted responses per link.' },
      { question: 'Can I publish one link for every template?', answer: 'Premium users can publish a shareable link for every saved template they keep in DullyPDF. Free users are limited to 1 active published link at a time.' },
    ],
  },
  {
    key: 'fill-information-in-pdf',
    category: 'workflow',
    path: '/fill-information-in-pdf',
    navLabel: 'Fill Information in PDF',
    heroTitle: 'Fill Information in PDF Forms With Structured Data',
    heroSummary:
      'If you need to fill information in PDF forms repeatedly, DullyPDF helps you map once and populate forms from searchable records.',
    seoTitle: 'Fill Information in PDF Forms With Structured Data | DullyPDF',
    seoDescription:
      'Fill information in PDF forms using mapped templates and structured records so repeat form entry workflows stay consistent.',
    seoKeywords: ['fill information in pdf', 'fill data in pdf forms', 'automated pdf form filling'],
    valuePoints: [
      'Turn manual copy/paste workflows into reusable mapped templates.',
      'Fill name, date, checkbox, and text fields from structured rows.',
      'Validate output with deterministic search and fill guardrails.',
    ],
    proofPoints: [
      'Date and checkbox handling include normalization and rule logic.',
      'Field edits can be audited through the editor and inspector panels.',
      'Templates can be reused across repeated packets and updates.',
    ],
    faqs: [
      { question: 'Can I fill patient or client information into a PDF quickly?', answer: 'Yes. DullyPDF is designed for repeated intake and form workflows where data comes from structured records.' },
      { question: 'Do I have to re-map fields every time?', answer: 'No. Once saved, templates retain mapping metadata so you can run repeat fills with less setup.' },
      { question: 'Does this work for checkbox-heavy forms?', answer: 'Yes. Checkbox metadata and rule precedence are part of the mapping and fill workflow.' },
    ],
  },
  {
    key: 'fillable-form-field-name',
    category: 'workflow',
    path: '/fillable-form-field-name',
    navLabel: 'Fillable Form Field Name',
    heroTitle: 'Standardize Fillable Form Field Names for Reliable Auto-Fill',
    heroSummary:
      'Normalize fillable form field names, map them to schema columns, and keep naming consistent across complex PDF packets.',
    seoTitle: 'Fillable Form Field Name Standardization and Mapping | DullyPDF',
    seoDescription:
      'Standardize fillable form field names, map them to schema columns, and improve downstream PDF auto-fill reliability.',
    seoKeywords: ['fillable form field name', 'pdf field naming standardization', 'pdf field rename mapping'],
    valuePoints: [
      'Use AI-assisted rename to convert inconsistent labels into stable names.',
      'Align renamed fields with schema headers for dependable fill behavior.',
      'Improve downstream search and fill quality with clean field naming.',
    ],
    proofPoints: [
      'Rename and map flows expose confidence output for QA review.',
      'Field naming updates can be verified before template save.',
      'Supports mixed field types including text, date, signature, and checkbox.',
    ],
    faqs: [
      { question: 'Why does fillable form field naming matter?', answer: 'Consistent field names improve mapping accuracy and reduce missing values during automated fill runs.' },
      { question: 'Can I rename fields without changing PDF appearance?', answer: 'Yes. Naming changes happen in template metadata and do not alter the visual PDF source layout.' },
      { question: 'Can I combine field rename with database mapping?', answer: 'Yes. DullyPDF supports rename-only, map-only, and combined rename-plus-map workflows.' },
    ],
  },
  {
    key: 'healthcare-pdf-automation',
    category: 'industry',
    path: '/healthcare-pdf-automation',
    navLabel: 'Healthcare PDF Automation',
    heroTitle: 'Automate Medical Intake and Healthcare PDF Form Workflows',
    heroSummary:
      'Convert medical and dental intake, registration, history, consent, and HIPAA release PDFs into reusable templates that map directly to structured data columns.',
    seoTitle: 'Healthcare and Dental Intake PDF Form Automation | DullyPDF',
    seoDescription:
      'Automate medical and dental intake forms, map patient intake PDFs to database-ready templates, and fill healthcare PDFs from structured records.',
    seoKeywords: ['automate medical intake forms', 'dental intake form automation', 'dental patient intake pdf automation', 'patient intake pdf to database', 'healthcare pdf form automation', 'patient registration form automation', 'hipaa release form automation'],
    valuePoints: [
      'Build reusable templates for medical and dental intake, registration, history, and consent packets.',
      'Normalize field names so front-desk teams can map once and reuse consistently.',
      'Support checkbox-heavy workflows for symptoms, disclosures, and releases.',
    ],
    proofPoints: [
      'CSV/XLSX/JSON rows are searchable in-browser for controlled patient record lookup.',
      'Detection plus editor cleanup helps handle scanned and native healthcare PDFs.',
      'Templates can be saved and reused for recurring appointment workflows.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate patient and dental intake PDFs and registration forms?', answer: 'Yes. You can detect fields, refine them in the editor, map to schema headers, and then fill medical or dental intake forms from structured data.' },
      { question: 'Does DullyPDF work for HIPAA release and consent forms?', answer: 'Yes. Checkbox and text field mapping supports release and consent-style healthcare forms.' },
      { question: 'Can healthcare teams reuse the same mapped template daily?', answer: 'Yes. Saved templates retain PDF bytes, field metadata, and mapping context for repeat usage.' },
    ],
  },
  {
    key: 'acord-form-automation',
    category: 'industry',
    path: '/acord-form-automation',
    navLabel: 'ACORD Form Automation',
    heroTitle: 'Automate ACORD Insurance PDF Forms With Mapped Data',
    heroSummary:
      'Handle ACORD workflows such as ACORD 25, 24, 27, 28, 126, and 140 by mapping form fields to structured data and reducing repetitive manual entry.',
    seoTitle: 'ACORD Form Automation for Insurance Certificate Workflows | DullyPDF',
    seoDescription:
      'Automate ACORD forms (25, 24, 27, 28, 126, and 140), auto-fill certificate of insurance PDFs, and map insurance data to structured templates.',
    seoKeywords: ['acord form automation', 'auto fill acord 25 pdf', 'certificate of insurance automation', 'acord certificate automation', 'insurance pdf automation', 'acord 24 automation', 'acord 27 automation', 'acord 28 automation', 'acord 126 automation', 'acord 140 automation'],
    valuePoints: [
      'Standardize repetitive ACORD field naming across brokers and account teams.',
      'Map ACORD certificate and liability forms to shared schema headers from AMS exports.',
      'Reduce rekeying errors for policy, insured, and coverage blocks.',
    ],
    proofPoints: [
      'Template workflows support repeat filling from CSV, XLSX, and JSON records.',
      'Field confidence and inspector-based QA provide pre-fill verification.',
      'Docs include rename/mapping and Search & Fill validation guidance for ACORD packets.',
    ],
    faqs: [
      { question: 'Can DullyPDF auto-fill ACORD 25 and similar insurance forms?', answer: 'Yes. DullyPDF supports mapped template workflows for common ACORD-style PDF forms.' },
      { question: 'Can insurance teams map ACORD fields to internal database columns?', answer: 'Yes. Schema mapping aligns PDF fields with your preferred naming and column structure.' },
      { question: 'Does this support ACORD renewals and recurring certificate requests?', answer: 'Yes. Teams can map once and fill repeatedly instead of retyping policy and certificate data every cycle.' },
    ],
  },
  {
    key: 'insurance-pdf-automation',
    category: 'industry',
    path: '/insurance-pdf-automation',
    navLabel: 'Insurance PDF Automation',
    heroTitle: 'Insurance PDF Automation for ACORD and Certificate Workflows',
    heroSummary:
      'Automate certificate of insurance, policy summary, endorsement, and claims intake PDFs by mapping form fields to structured insurance data exports.',
    seoTitle: 'Insurance PDF Automation for ACORD and Certificate Forms | DullyPDF',
    seoDescription:
      'Automate insurance PDF forms, including ACORD workflows and certificate of insurance documents, by mapping fields to structured agency or broker data.',
    seoKeywords: ['insurance pdf automation', 'insurance form automation', 'certificate of insurance automation', 'insurance certificate pdf automation', 'auto fill insurance forms', 'acord form automation'],
    valuePoints: [
      'Build reusable templates for ACORD packets and carrier-specific insurance forms.',
      'Map insured, producer, policy, and coverage fields to AMS or broker export columns.',
      'Standardize field naming across renewal cycles and form revisions.',
    ],
    proofPoints: [
      'Works with CSV, XLSX, and JSON exports from insurance operations systems.',
      'Supports checkbox, date, and text cleanup for carrier-specific PDF variants.',
      'Saved templates accelerate recurring certificate and renewal workflows.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate insurance PDFs beyond ACORD 25?', answer: 'Yes. Teams use it for ACORD 24/27/28/126/140 and carrier-specific insurance PDFs that require repeat filling.' },
      { question: 'Can insurance teams map form fields to agency management exports?', answer: 'Yes. Map once to your export schema, then run repeat fills from structured records in Search & Fill.' },
      { question: 'Is this useful for certificate of insurance turnaround speed?', answer: 'Yes. Reusable mapped templates reduce manual retyping and help teams produce certificates faster with fewer entry errors.' },
    ],
  },
  {
    key: 'real-estate-pdf-automation',
    category: 'industry',
    path: '/real-estate-pdf-automation',
    navLabel: 'Real Estate PDF Automation',
    heroTitle: 'Real Estate and Mortgage PDF Form Automation',
    heroSummary:
      'Automate rental applications, lease packets, mortgage forms, and inspection PDFs by converting them into mapped, reusable fillable templates.',
    seoTitle: 'Real Estate and Mortgage PDF Automation | DullyPDF',
    seoDescription:
      'Automate rental application PDFs, map mortgage forms to database templates, and streamline real estate form filling workflows.',
    seoKeywords: ['automate rental application pdf', 'mortgage pdf to database', 'real estate form automation', 'lease agreement pdf automation', 'property inspection form automation'],
    valuePoints: [
      'Support rental intake packets, mortgage documents, and lease workflows.',
      'Map tenant and borrower fields to shared CRM or operational schemas.',
      'Reuse templates across properties, units, and recurring transaction packets.',
    ],
    proofPoints: [
      'Search & Fill supports row-based record selection for fast form completion.',
      'Editor tools help resolve geometry mismatch in legacy property forms.',
      'Template reuse reduces repetitive office data entry across teams.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate rental application PDF workflows?', answer: 'Yes. Rental application and lease-style forms can be mapped and filled from structured tenant data.' },
      { question: 'Does it work for mortgage-related PDF forms?', answer: 'Yes. Mortgage and lending packets can be converted into reusable mapped templates.' },
      { question: 'Can real estate teams reuse templates across properties?', answer: 'Yes. Saved templates can be reloaded and reused for recurring packet types.' },
    ],
  },
  {
    key: 'government-form-automation',
    category: 'industry',
    path: '/government-form-automation',
    navLabel: 'Government Form Automation',
    heroTitle: 'Government and Public Service PDF Form Automation',
    heroSummary:
      'Convert permit, tax, licensing, and social services forms into mapped templates to reduce manual entry and improve consistency in public-sector workflows.',
    seoTitle: 'Government PDF Permit and Tax Form Automation | DullyPDF',
    seoDescription:
      'Automate government PDF forms, map permit and tax paperwork to structured schemas, and improve public service document workflows.',
    seoKeywords: ['government form automation', 'pdf permit automation', 'tax form database mapping', 'public sector pdf automation', 'license renewal form automation'],
    valuePoints: [
      'Handle standardized permit, licensing, tax, and public service forms.',
      'Map required fields to internal tracking columns for consistent intake.',
      'Use repeatable templates for recurring citizen application workflows.',
    ],
    proofPoints: [
      'Structured data mapping helps avoid inconsistent field naming across departments.',
      'Search-based fill supports quick retrieval of known record values.',
      'Troubleshooting docs support QA for edge-case form behaviors.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate permit and license PDF forms?', answer: 'Yes. Permit and license forms can be converted, mapped, and reused as structured templates.' },
      { question: 'Does this help with tax and compliance form workflows?', answer: 'Yes. Standardized mapping and row-based fill reduce repetitive manual entry for recurring forms.' },
      { question: 'Can agencies keep one canonical template per form type?', answer: 'Yes. Saved template workflows support a canonical setup per recurring government form.' },
    ],
  },
  {
    key: 'finance-loan-pdf-automation',
    category: 'industry',
    path: '/finance-loan-pdf-automation',
    navLabel: 'Finance and Loan PDF Automation',
    heroTitle: 'Finance and Loan Origination PDF Automation Workflows',
    heroSummary:
      'Automate loan applications, financial disclosures, and compliance documents by mapping PDF fields to structured lending and underwriting data.',
    seoTitle: 'Loan Application PDF Automation and Mapping | DullyPDF',
    seoDescription:
      'Automate loan PDF forms, fill financial disclosure documents from mapped records, and streamline lending document workflows.',
    seoKeywords: ['loan pdf automation', 'loan application pdf automation', 'fill pdf financial form from database', 'financial disclosure pdf automation', 'kyc aml pdf automation'],
    valuePoints: [
      'Map borrower and underwriting fields to lending schema columns.',
      'Reduce rekeying on loan applications and disclosure packets.',
      'Support repeat workflows across product lines and document versions.',
    ],
    proofPoints: [
      'Search & Fill supports fast row selection for borrower profile data.',
      'Rename and mapping assist with inconsistent legacy field labels.',
      'Saved templates preserve mapping context for repeat monthly workflows.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate loan application PDFs?', answer: 'Yes. Loan application templates can be mapped to structured data and reused for repetitive fill tasks.' },
      { question: 'Does DullyPDF support financial disclosure form filling?', answer: 'Yes. Disclosure and related finance forms can be filled from mapped record fields.' },
      { question: 'Can lenders use this for KYC and AML paperwork workflows?', answer: 'Yes. Mapped template workflows can support recurring compliance document preparation.' },
    ],
  },
  {
    key: 'hr-pdf-automation',
    category: 'industry',
    path: '/hr-pdf-automation',
    navLabel: 'HR PDF Automation',
    heroTitle: 'HR Onboarding and Employee PDF Form Automation',
    heroSummary:
      'Automate job application, onboarding, benefits, and tax-document PDFs by mapping recurring HR forms to structured employee records.',
    seoTitle: 'HR Onboarding PDF Form Automation | DullyPDF',
    seoDescription:
      'Automate HR onboarding forms, map employee PDF paperwork to structured data, and streamline repetitive HR document entry.',
    seoKeywords: ['automate hr onboarding forms', 'pdf employee form automation', 'onboarding packet pdf automation', 'benefits enrollment form automation', 'w4 1099 pdf automation'],
    valuePoints: [
      'Use one mapped template set for common onboarding packet forms.',
      'Fill employee details from structured HR records instead of retyping.',
      'Support checkbox and text-field heavy benefits documents.',
    ],
    proofPoints: [
      'Repeat-fill workflows reduce turnaround time for HR operations teams.',
      'Mapped templates improve consistency across locations and recruiters.',
      'Template save/reload supports recurring hiring cycles.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate onboarding PDF packets?', answer: 'Yes. HR teams can map onboarding templates once and fill forms from structured employee records.' },
      { question: 'Does it support employee tax and benefits forms?', answer: 'Yes. HR-focused PDF templates can include tax and benefits form workflows.' },
      { question: 'Can HR teams reuse templates for every new hire?', answer: 'Yes. Saved templates support repeat onboarding runs with minimal setup.' },
    ],
  },
  {
    key: 'legal-pdf-workflow-automation',
    category: 'industry',
    path: '/legal-pdf-workflow-automation',
    navLabel: 'Legal PDF Workflow Automation',
    heroTitle: 'Legal Document PDF Workflow Automation',
    heroSummary:
      'Automate contract packets, affidavits, motions, and other legal PDF templates by mapping common fields to case or client record data.',
    seoTitle: 'Legal PDF Workflow and Court Document Automation | DullyPDF',
    seoDescription:
      'Automate legal PDF workflows, map contract and court document templates, and fill recurring legal forms from structured records.',
    seoKeywords: ['legal pdf workflow automation', 'court document automation', 'contract pdf to database', 'legal intake form automation', 'affidavit template automation'],
    valuePoints: [
      'Reuse mapped templates for legal intake, contracts, and filing workflows.',
      'Reduce repetitive copy/paste across recurring court or client packets.',
      'Keep field naming consistent for better downstream case-data mapping.',
    ],
    proofPoints: [
      'Search & Fill supports row-based client/case data population.',
      'Editor cleanup handles variable legacy form geometry before production.',
      'Troubleshooting docs provide fast validation steps for misfills.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate legal contract and filing PDFs?', answer: 'Yes. Legal teams can map recurring templates and fill them from structured client and case records.' },
      { question: 'Does this work for affidavit and declaration form templates?', answer: 'Yes. Affidavit and declaration-style PDFs can be standardized and reused as mapped templates.' },
      { question: 'Can law firms maintain consistent field naming across templates?', answer: 'Yes. Rename plus mapping workflows are designed to normalize inconsistent field labels.' },
    ],
  },
  {
    key: 'education-form-automation',
    category: 'industry',
    path: '/education-form-automation',
    navLabel: 'Education Form Automation',
    heroTitle: 'Education and Admissions PDF Form Automation',
    heroSummary:
      'Automate student application, enrollment, consent, and transcript-request PDFs with reusable templates mapped to admissions data fields.',
    seoTitle: 'Education and Student Application PDF Automation | DullyPDF',
    seoDescription:
      'Automate student application PDFs, map enrollment forms to structured data columns, and streamline education document workflows.',
    seoKeywords: ['automate student application pdfs', 'university form pdf automation', 'education pdf automation', 'enrollment form automation', 'transcript request form automation'],
    valuePoints: [
      'Handle recurring admissions packets and enrollment form workflows.',
      'Map common student data fields once and reuse across terms.',
      'Improve consistency in consent and transcript-request document filling.',
    ],
    proofPoints: [
      'Search-based record selection supports quick admissions form completion.',
      'Template reuse reduces repetitive office operations overhead.',
      'Structured mapping reduces mismatch across multi-form packets.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate admissions and enrollment PDFs?', answer: 'Yes. Admissions teams can map and reuse student form templates for repeat cycles.' },
      { question: 'Does this support transcript request and consent forms?', answer: 'Yes. Education teams can automate repetitive transcript and consent form workflows.' },
      { question: 'Can schools use one template across semesters?', answer: 'Yes. Saved templates can be reused and adjusted as forms evolve.' },
    ],
  },
  {
    key: 'nonprofit-pdf-form-automation',
    category: 'industry',
    path: '/nonprofit-pdf-form-automation',
    navLabel: 'Nonprofit PDF Form Automation',
    heroTitle: 'Nonprofit and Human Services PDF Form Automation',
    heroSummary:
      'Automate grant, volunteer, intake, and funding-compliance PDFs with reusable templates mapped to your structured nonprofit program data.',
    seoTitle: 'Nonprofit PDF Form and Grant Workflow Automation | DullyPDF',
    seoDescription:
      'Automate nonprofit PDF forms, streamline grant and volunteer paperwork, and map recurring human services documents to structured data.',
    seoKeywords: ['nonprofit pdf form automation', 'grant pdf automation', 'volunteer registration pdf automation', 'human services form automation', 'nonprofit intake pdf automation'],
    valuePoints: [
      'Support grant packets, volunteer onboarding, and program intake forms.',
      'Reduce repetitive manual entry in resource-constrained operations teams.',
      'Map recurring fields to shared data columns for repeat submissions.',
    ],
    proofPoints: [
      'Saved templates keep frequent submission workflows consistent.',
      'Search & Fill supports quick record lookup before form output.',
      'Docs provide practical troubleshooting for mapping and fill issues.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate grant and volunteer PDF workflows?', answer: 'Yes. Nonprofit teams can map recurring forms and populate them from structured records.' },
      { question: 'Is this useful for human services intake packets?', answer: 'Yes. Intake-style packet templates can be standardized and reused across programs.' },
      { question: 'Can smaller teams benefit from template reuse?', answer: 'Yes. Template reuse reduces repetitive manual entry and improves consistency.' },
    ],
  },
  {
    key: 'logistics-pdf-automation',
    category: 'industry',
    path: '/logistics-pdf-automation',
    navLabel: 'Logistics PDF Automation',
    heroTitle: 'Logistics and Transportation PDF Form Automation',
    heroSummary:
      'Automate bill of lading, safety inspection, and delivery receipt PDFs by mapping logistics form fields to structured shipment and operations data.',
    seoTitle: 'Logistics and Transportation PDF Automation | DullyPDF',
    seoDescription:
      'Automate logistics PDF forms, map transportation paperwork to database templates, and streamline recurring shipping document workflows.',
    seoKeywords: ['transport pdf automation', 'logistics form to database', 'bill of lading automation', 'delivery receipt pdf automation', 'safety inspection form automation'],
    valuePoints: [
      'Standardize recurring shipping, inspection, and delivery document templates.',
      'Map shipment and carrier fields to structured operations data.',
      'Reduce repetitive manual entry for dispatch and back-office teams.',
    ],
    proofPoints: [
      'Search & Fill supports rapid row selection for route or shipment records.',
      'Field editor and inspector tools handle template quality checks.',
      'Template reuse supports repeated daily form output operations.',
    ],
    faqs: [
      { question: 'Can DullyPDF automate bill of lading and delivery receipt PDFs?', answer: 'Yes. Logistics teams can map those recurring forms and fill them from structured records.' },
      { question: 'Does this support transportation safety inspection forms?', answer: 'Yes. Inspection forms can be standardized and reused as mapped templates.' },
      { question: 'Can operations teams maintain one template per document type?', answer: 'Yes. Saved template workflows support canonical forms for recurring logistics tasks.' },
    ],
  },
  {
    key: 'batch-fill-pdf-forms',
    category: 'workflow',
    path: '/batch-fill-pdf-forms',
    navLabel: 'Batch Fill PDF Forms',
    heroTitle: 'Batch Fill PDF Forms From Multiple Records',
    heroSummary: 'Fill the same PDF template with multiple records from your CSV, Excel, or JSON data. Map once, then fill form after form in seconds.',
    seoTitle: 'Batch Fill PDF Forms From CSV, Excel, and JSON | DullyPDF',
    seoDescription: 'Batch fill PDF forms by mapping a template once and populating it from multiple records in CSV, Excel, or JSON data sources.',
    seoKeywords: ['batch fill pdf forms', 'bulk pdf filling', 'fill multiple pdfs from spreadsheet', 'batch pdf form automation'],
    valuePoints: ['Map a PDF template once and fill it from any number of records.', 'Search and select rows individually for controlled batch output.', 'Clear and refill between records to verify mapping quality.'],
    proofPoints: ['Search & Fill supports fast row switching for sequential form filling.', 'Templates persist mapping context between fill sessions.', 'Filled output can be downloaded immediately for each record.'],
    faqs: [
      { question: 'Can I fill the same PDF form with different records?', answer: 'Yes. After mapping, use Search & Fill to select any row and populate the template, then clear and fill with the next record.' },
      { question: 'Does DullyPDF support bulk PDF generation?', answer: 'DullyPDF fills one record at a time through Search & Fill for controlled output. Map once, then fill repeatedly from your data rows.' },
      { question: 'What data sources work for batch filling?', answer: 'CSV, XLSX, and JSON files with row data. Each row represents one form to fill.' },
    ],
  },
  {
    key: 'pdf-checkbox-automation',
    category: 'workflow',
    path: '/pdf-checkbox-automation',
    navLabel: 'PDF Checkbox Automation',
    heroTitle: 'Automate PDF Checkbox Fields With Rule-Based Logic',
    heroSummary: 'DullyPDF handles complex checkbox scenarios including yes/no pairs, enum selections, multi-select lists, and presence-based toggles with configurable rule logic.',
    seoTitle: 'PDF Checkbox Automation With Rule-Based Fill Logic | DullyPDF',
    seoDescription: 'Automate PDF checkbox filling with yes/no, enum, presence, and list rules. Map checkbox groups to data columns for reliable automated form output.',
    seoKeywords: ['pdf checkbox automation', 'auto fill checkboxes pdf', 'pdf checkbox rules', 'checkbox form automation'],
    valuePoints: ['Support four checkbox rule types: yes_no, presence, enum, and list.', 'Map checkbox groups and option keys to structured data columns.', 'Handle multi-select checkbox fields with list-based splitting.'],
    proofPoints: ['Checkbox rule precedence follows a defined six-step resolution order.', 'Built-in alias fallback groups handle common medical and HR patterns.', 'Boolean token normalization covers yes/no, true/false, 1/0, and variants.'],
    faqs: [
      { question: 'Can DullyPDF auto-fill checkboxes in PDF forms?', answer: 'Yes. DullyPDF supports rule-based checkbox automation with yes/no, presence, enum, and list modes.' },
      { question: 'How does checkbox group mapping work?', answer: 'Each checkbox has a groupKey and optionKey. Map the group to a data column, and DullyPDF selects the correct option based on the cell value and rule type.' },
      { question: 'Does this work for forms with dozens of checkboxes?', answer: 'Yes. Checkbox-heavy forms like medical intake and benefits enrollment are common use cases for rule-based automation.' },
    ],
  },
  {
    key: 'pdf-field-detection-tool',
    category: 'workflow',
    path: '/pdf-field-detection-tool',
    navLabel: 'PDF Field Detection Tool',
    heroTitle: 'Detect Form Fields in Any PDF With AI',
    heroSummary: 'Upload any PDF and let AI detect text fields, checkboxes, date fields, and signature areas automatically. Review confidence scores and refine in the visual editor.',
    seoTitle: 'AI PDF Field Detection Tool for Form Automation | DullyPDF',
    seoDescription: 'Detect form fields in any PDF with AI-powered field detection. Identify text, checkbox, date, and signature fields with confidence scoring.',
    seoKeywords: ['pdf field detection', 'detect form fields in pdf', 'pdf field detection tool', 'ai form field detection'],
    valuePoints: ['Detect text, date, checkbox, and signature fields automatically.', 'Review confidence scores to prioritize fields needing manual review.', 'Refine detection results with visual editor tools.'],
    proofPoints: ['Supports PDF uploads up to 50MB with multi-page detection.', 'Confidence tiers: high (80%+), medium (65-80%), low (below 65%).', 'Field geometry uses normalized top-left origin coordinates.'],
    faqs: [
      { question: 'Can DullyPDF detect fields in scanned PDFs?', answer: 'Yes. The AI model analyzes rendered page images and works with both native and scanned PDFs.' },
      { question: 'How accurate is field detection?', answer: 'Detection quality depends on PDF clarity. High-confidence detections (80%+) are typically accurate. Low-confidence items should be reviewed.' },
      { question: 'Can I add fields the AI missed?', answer: 'Yes. The editor lets you add text, date, checkbox, and signature fields manually for regions the detector did not identify.' },
    ],
  },
  {
    key: 'construction-pdf-automation',
    category: 'industry',
    path: '/construction-pdf-automation',
    navLabel: 'Construction PDF Automation',
    heroTitle: 'Construction Permit and Safety Form PDF Automation',
    heroSummary: 'Automate construction permits, safety inspection forms, change orders, and daily logs by mapping PDF fields to project and subcontractor data.',
    seoTitle: 'Construction PDF Form Automation for Permits and Safety | DullyPDF',
    seoDescription: 'Automate construction permit PDFs, safety inspection forms, and change orders with mapped templates and structured project data.',
    seoKeywords: ['construction pdf automation', 'permit form automation', 'safety inspection form pdf', 'construction change order automation', 'daily log pdf automation'],
    valuePoints: ['Standardize permit, inspection, and change order form templates.', 'Map project and subcontractor data fields to form inputs.', 'Reuse templates across job sites and recurring submission cycles.'],
    proofPoints: ['Search & Fill supports fast row selection from project records.', 'Editor tools handle variable legacy form layouts from different agencies.', 'Template reuse reduces repetitive data entry for field office teams.'],
    faqs: [
      { question: 'Can DullyPDF automate construction permit PDF forms?', answer: 'Yes. Upload permit forms, detect fields, map to your project data, and fill them from structured records.' },
      { question: 'Does this work for safety inspection and daily log forms?', answer: 'Yes. Safety inspection and daily log PDFs can be standardized as mapped templates.' },
      { question: 'Can GCs reuse templates across multiple job sites?', answer: 'Yes. Saved templates can be reused for recurring form types across projects.' },
    ],
  },
  {
    key: 'accounting-tax-pdf-automation',
    category: 'industry',
    path: '/accounting-tax-pdf-automation',
    navLabel: 'Accounting & Tax PDF Automation',
    heroTitle: 'Accounting and Tax Form PDF Automation Workflows',
    heroSummary: 'Automate W-9s, 1099s, engagement letters, and other accounting-related PDFs by mapping form fields to client records and tax preparation data.',
    seoTitle: 'Accounting and Tax PDF Form Automation | DullyPDF',
    seoDescription: 'Automate accounting and tax PDF forms, fill W-9 and 1099 templates from client data, and streamline CPA firm document workflows.',
    seoKeywords: ['accounting pdf automation', 'tax form pdf automation', 'w9 form automation', '1099 pdf automation', 'cpa firm pdf automation'],
    valuePoints: ['Map client and entity data to recurring tax and engagement forms.', 'Reduce rekeying for W-9 collection, 1099 preparation, and engagement letters.', 'Support repeat workflows across clients and tax seasons.'],
    proofPoints: ['Template reuse supports high-volume tax season processing.', 'Search & Fill handles quick client record lookup from data exports.', 'Rename and mapping improve consistency for inconsistent legacy form labels.'],
    faqs: [
      { question: 'Can DullyPDF automate W-9 and 1099 PDF forms?', answer: 'Yes. Tax document templates can be mapped to client data and filled from structured records.' },
      { question: 'Does this work for CPA firm engagement letters?', answer: 'Yes. Engagement letter templates can be standardized and reused across clients.' },
      { question: 'Can accounting teams handle tax season volume with templates?', answer: 'Yes. Saved templates support repeat filling from client data exports for high-volume processing.' },
    ],
  },
];

// ---------------------------------------------------------------------------
// Usage docs
// ---------------------------------------------------------------------------

const USAGE_DOCS_PAGES = [
  {
    key: 'index',
    slug: '',
    path: '/usage-docs',
    navLabel: 'Overview',
    title: 'DullyPDF Usage Docs',
    summary: 'Implementation-level guide for the full DullyPDF workflow, including concrete limits, matching rules, and checkbox behavior.',
    sectionTitles: ['Pipeline overview', 'Before you start', 'Choose the right docs page', 'Hard numbers used by the app'],
  },
  {
    key: 'getting-started',
    slug: 'getting-started',
    path: '/usage-docs/getting-started',
    navLabel: 'Getting Started',
    title: 'Getting Started',
    summary: 'A practical quick-start from upload to filled output, including when to pause and review results.',
    sectionTitles: ['Quick-start path', 'Best-practice order', 'First-run checklist', 'What good output looks like'],
  },
  {
    key: 'detection',
    slug: 'detection',
    path: '/usage-docs/detection',
    navLabel: 'Detection',
    title: 'Detection',
    summary: 'How CommonForms detection works, how confidence levels are used, and what to adjust when candidates look wrong.',
    sectionTitles: ['What detection returns', 'Confidence review', 'Common limitations and fixes', 'Geometry values and editor constraints'],
  },
  {
    key: 'rename-mapping',
    slug: 'rename-mapping',
    path: '/usage-docs/rename-mapping',
    navLabel: 'Rename + Mapping',
    title: 'Rename + Mapping',
    summary: 'How to choose Rename, Map, or Rename + Map and how OpenAI outputs appear in the editor.',
    sectionTitles: ['When to run each action', 'OpenAI data boundaries', 'Interpreting results', 'Checkbox rules and precedence', 'Boolean token values used by Search & Fill', 'Rename-only warning'],
  },
  {
    key: 'editor-workflow',
    slug: 'editor-workflow',
    path: '/usage-docs/editor-workflow',
    navLabel: 'Editor Workflow',
    title: 'Editor Workflow',
    summary: 'How to use overlay, field list, and inspector together for fast, high-confidence template cleanup.',
    sectionTitles: ['Three-panel model', 'Editing actions', 'Recommended quality loop', 'History and clear behavior'],
  },
  {
    key: 'search-fill',
    slug: 'search-fill',
    path: '/usage-docs/search-fill',
    navLabel: 'Search & Fill',
    title: 'Search & Fill',
    summary: 'Connect local data sources, search a record, and populate mapped fields with predictable behavior.',
    sectionTitles: ['Data source support', 'Fill flow', 'Guardrails', 'Field resolution heuristics (non-checkbox)', 'Checkbox groups and aliases'],
  },
  {
    key: 'fill-by-link',
    slug: 'fill-by-link',
    path: '/usage-docs/fill-by-link',
    navLabel: 'Fill By Link',
    title: 'Fill By Link',
    summary: 'Publish a DullyPDF-hosted form from a saved template or open group, share the generated link, and turn stored respondent answers into PDFs when needed.',
    sectionTitles: ['What gets published', 'Owner publishing flow', 'What respondents see', 'Reviewing responses and generating PDFs', 'Limits and sharing guidance'],
  },
  {
    key: 'create-group',
    slug: 'create-group',
    path: '/usage-docs/create-group',
    navLabel: 'Create Group',
    title: 'Create Group and Group Workflows',
    summary: 'Use groups to organize multi-document packets, switch between saved templates quickly, and run full document workflows across the group.',
    sectionTitles: ['What a group is', 'Create and open groups', 'Search and fill full groups', 'Rename and remap entire groups', 'Group Fill By Link and packet publishing'],
  },
  {
    key: 'save-download-profile',
    slug: 'save-download-profile',
    path: '/usage-docs/save-download-profile',
    navLabel: 'Save / Download',
    title: 'Save, Download, and Profile',
    summary: 'Understand when to download immediately versus saving templates to your profile for reuse.',
    sectionTitles: ['Download vs save', 'Saved form workflow', 'Limits and credits', 'Stripe billing plans', 'Replace vs new save'],
  },
  {
    key: 'troubleshooting',
    slug: 'troubleshooting',
    path: '/usage-docs/troubleshooting',
    navLabel: 'Troubleshooting',
    title: 'Troubleshooting',
    summary: 'Systematic checks for detection quality, OpenAI steps, mapping mismatches, and fill output issues.',
    sectionTitles: ['Detection issues', 'Rename and mapping issues', 'Fill output issues', 'Common validation and runtime messages', 'Support'],
  },
];

const FEATURE_PLAN_PAGES = [
  {
    key: 'free-features',
    path: '/free-features',
    navLabel: 'Free Features',
    heroTitle: 'Free DullyPDF Features for PDF-to-Form Setup',
    heroSummary:
      'Start with unlimited PDF-to-form setup and the form builder, then validate your workflow before upgrading for higher usage.',
    seoTitle: 'Free PDF Form Builder Features | DullyPDF',
    seoDescription:
      'Review the free DullyPDF feature set, including unlimited PDF-to-form setup, form builder access, and the free Fill By Link limits before upgrading.',
    seoKeywords: ['free pdf form builder', 'free pdf to form tool', 'free fillable pdf builder', 'free pdf workflow software'],
    valuePoints: [
      'Unlimited PDF-to-form setup and access to the form builder.',
      'A practical free tier for validating field detection, cleanup, and saved-template workflows.',
      'Native Fill By Link support with 1 active published link and up to 5 accepted responses.',
    ],
    detailSections: [
      { title: 'Best fit for', items: ['Teams validating one workflow before rolling out larger intake or packet automation.', 'Owners who want to test field detection, editor cleanup, and mapping quality on real documents.', 'Users who need one live respondent link instead of a larger link portfolio.'] },
      { title: 'Included workflow access', items: ['Upload PDFs up to 50MB and convert them into editable templates.', 'Use the form builder, field inspector, list panel, and saved-template workflow.', 'Run Search & Fill with local CSV, Excel, JSON, or stored respondent records once your template is mapped.'] },
      { title: 'Free-tier limits that stay visible', items: ['Fill By Link: 1 active published link and 5 accepted responses per link.', 'OpenAI credits and some effective profile limits are enforced server-side and shown in Profile.', 'When you need higher usage, premium expands link capacity and monthly OpenAI credit access.'] },
    ],
    faqs: [
      { question: 'Does free still let me convert PDFs into fillable templates?', answer: 'Yes. Free includes unlimited PDF-to-form setup plus the form builder so you can detect, clean up, and save reusable templates.' },
      { question: 'What is the main free-tier Fill By Link limit?', answer: 'Free supports 1 active published link at a time, and each link accepts up to 5 responses before it closes.' },
      { question: 'Where do I confirm my current limits?', answer: 'The signed-in Profile view shows your effective account limits, billing status, and remaining credits.' },
    ],
  },
  {
    key: 'premium-features',
    path: '/premium-features',
    navLabel: 'Premium Features',
    heroTitle: 'Premium DullyPDF Features for Higher-Usage Workflows',
    heroSummary:
      'Premium is the higher-usage tier for teams running repeat PDF automation, larger Fill By Link traffic, and Stripe-backed account billing.',
    seoTitle: 'Premium PDF Automation Features and Billing | DullyPDF',
    seoDescription:
      'Review premium DullyPDF features, including higher usage across the platform, expanded Fill By Link capacity, monthly OpenAI credits, and sign-in purchase options.',
    seoKeywords: ['premium pdf automation software', 'pdf form builder subscription', 'fill by link premium plan', 'stripe pdf software billing'],
    valuePoints: [
      'Higher usage across DullyPDF workflows instead of the lighter free-tier guardrails.',
      'A shareable Fill By Link on every saved template with up to 10,000 accepted responses per link.',
      'Stripe-backed monthly or yearly purchase options when you are signed in.',
    ],
    detailSections: [
      { title: 'Premium unlocks', items: ['Higher-usage access across PDF detection, template reuse, mapping, and Fill By Link workflows.', 'One shareable Fill By Link per saved template instead of the free single-link cap.', 'Up to 10,000 accepted responses per link for respondent-driven workflows.'] },
      { title: 'OpenAI and billing', items: ['Pro billing actions run through Stripe Checkout with monthly and yearly subscriptions.', 'Premium profiles receive a monthly OpenAI credit pool, and refill packs remain available from Profile.', 'Cancellation is managed from the signed-in profile billing section and is scheduled for period end.'] },
      { title: 'Best fit for', items: ['Teams operating repeat intake or packet workflows across many saved templates.', 'Owners publishing multiple public respondent links at once.', 'Accounts that need higher sustained usage instead of one-off free-tier validation.'] },
    ],
    faqs: [
      { question: 'What is the biggest premium Fill By Link difference?', answer: 'Premium removes the single-link cap by allowing a shareable link on every saved template and raises response capacity to 10,000 per link.' },
      { question: 'Can I buy premium from this page?', answer: 'Yes. When you are signed in and billing is available, this page can launch the Stripe Checkout flow for monthly or yearly premium.' },
      { question: 'What if I already have premium?', answer: 'The page will show that the current account already has premium access instead of offering another upgrade button.' },
    ],
  },
];

// ---------------------------------------------------------------------------
// Consolidated SEO metadata for all routes
// ---------------------------------------------------------------------------

const toFaqSchema = (faqs) => [{
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: faqs.map((faq) => ({
    '@type': 'Question',
    name: faq.question,
    acceptedAnswer: { '@type': 'Answer', text: faq.answer },
  })),
}];

const HOME_ROUTE_SEO = {
  title: 'DullyPDF | Convert PDFs to Fillable Forms & Map to Database',
  description:
    'DullyPDF is a PDF form builder for existing documents. Convert PDFs into fillable templates with AI field detection, map fields to database columns, and auto-fill from CSV, Excel, or JSON. Free to start.',
  canonicalPath: '/',
  keywords: ['pdf to fillable form', 'pdf form builder', 'fillable pdf builder', 'pdf to database template', 'fillable pdf template generator', 'map pdf fields to database columns', 'auto fill pdf from csv'],
  structuredData: [
    {
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      name: 'DullyPDF',
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Web',
      url: 'https://dullypdf.com/',
      description: 'DullyPDF is a PDF form builder for existing documents. It converts PDFs into fillable templates, maps fields to schema headers, and fills mapped fields from structured data rows.',
      offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
      featureList: ['PDF form builder for existing PDFs', 'PDF field detection', 'Fillable form template editing', 'Schema mapping for CSV/XLSX/JSON', 'Search and fill workflows'],
    },
    {
      '@context': 'https://schema.org',
      '@type': 'Organization',
      name: 'DullyPDF',
      url: 'https://dullypdf.com/',
      logo: 'https://dullypdf.com/DullyPDFLogoImproved.png',
      contactPoint: { '@type': 'ContactPoint', contactType: 'customer support', email: 'justin@dullypdf.com' },
    },
  ],
  bodyContent: {
    heading: 'DullyPDF | Convert PDFs to Fillable Forms & Map to Database',
    paragraphs: [
      'DullyPDF converts raw PDFs into fillable templates with AI field detection. Map fields to database columns and auto-fill from CSV, Excel, or JSON. Free to start.',
      'Upload a PDF, detect form fields automatically, refine in the visual editor, map to your schema, and fill from structured data in seconds.',
    ],
    sections: [
      { title: 'Upload PDF Document', description: 'Upload any PDF with text fields, checkboxes, or signature areas. Supports files up to 50MB.' },
      { title: 'AI-Powered Field Detection', description: 'The detection pipeline identifies potential form fields with confidence scoring and context hints.' },
      { title: 'Interactive Visual Editing', description: 'Resize, rename, reposition, and adjust field properties with precision tools.' },
      { title: 'Schema Mapping & Auto-Fill', description: 'Upload a CSV/Excel/JSON schema, map PDF field names, and populate forms from selected records.' },
    ],
  },
};

const LEGAL_ROUTE_SEO = {
  privacy: {
    title: 'Privacy Policy | DullyPDF',
    description: 'Read how DullyPDF handles account data, uploaded PDFs, schema metadata, optional AI processing, and billing information.',
    canonicalPath: '/privacy',
    keywords: ['dullypdf privacy policy', 'pdf form automation privacy'],
    bodyContent: {
      heading: 'Privacy Policy',
      paragraphs: ['Read the DullyPDF privacy policy to understand how your data is collected, used, and protected.'],
    },
  },
  terms: {
    title: 'Terms of Service | DullyPDF',
    description: 'Review DullyPDF service terms covering accounts, AI-assisted workflows, billing, acceptable use, and platform limitations.',
    canonicalPath: '/terms',
    keywords: ['dullypdf terms', 'pdf automation terms of service'],
    bodyContent: {
      heading: 'Terms of Service',
      paragraphs: ['Review the DullyPDF terms of service governing accounts, features, billing, and acceptable use.'],
    },
  },
};

const USAGE_DOCS_FAQ_SCHEMAS = {
  'getting-started': [{
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: [
      { '@type': 'Question', name: 'How do I convert a PDF into a fillable template in DullyPDF?', acceptedAnswer: { '@type': 'Answer', text: 'Upload a PDF, run field detection, review/edit field geometry and names, then save the template for reuse.' } },
      { '@type': 'Question', name: 'Do I need mapping before Search and Fill?', acceptedAnswer: { '@type': 'Answer', text: 'Mapping is strongly recommended for reliable output, especially for checkbox groups and non-trivial schemas.' } },
    ],
  }],
  'rename-mapping': [{
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: [
      { '@type': 'Question', name: 'What is PDF field to database mapping?', acceptedAnswer: { '@type': 'Answer', text: 'It links PDF field identifiers to schema headers so row data can populate the correct fields during fill operations.' } },
      { '@type': 'Question', name: 'Should I run rename before map?', acceptedAnswer: { '@type': 'Answer', text: 'When labels are inconsistent, rename first improves field naming consistency and typically improves mapping quality.' } },
    ],
  }],
  'search-fill': [{
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: [
      { '@type': 'Question', name: 'Can DullyPDF fill PDF fields from CSV rows?', acceptedAnswer: { '@type': 'Answer', text: 'Yes. After mapping, Search and Fill lets you select a row and populate mapped PDF fields from CSV, XLSX, or JSON data.' } },
      { '@type': 'Question', name: 'What data sources are supported for row-based fill?', acceptedAnswer: { '@type': 'Answer', text: 'CSV, XLSX, and JSON support row-based fill. TXT is schema-only and does not provide row data for filling.' } },
    ],
  }],
  'fill-by-link': [{
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: [
      { '@type': 'Question', name: 'Does Fill By Link publish the PDF itself?', acceptedAnswer: { '@type': 'Answer', text: 'No. DullyPDF publishes a hosted HTML form and generates the final PDF later from the saved respondent submission.' } },
      { '@type': 'Question', name: 'Can one group publish a single shared respondent form?', acceptedAnswer: { '@type': 'Answer', text: 'Yes. An open group can publish one merged Fill By Link that includes every distinct respondent-facing field across the group.' } },
    ],
  }],
  'create-group': [{
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: [
      { '@type': 'Question', name: 'What does a DullyPDF group do?', acceptedAnswer: { '@type': 'Answer', text: 'A group bundles saved templates into one packet so teams can switch documents quickly, fill the packet from one record, and run batch rename and mapping actions.' } },
      { '@type': 'Question', name: 'Can Rename + Map run across the whole group?', acceptedAnswer: { '@type': 'Answer', text: 'Yes. Rename + Map Group runs across every saved template in the open group and overwrites each template on success.' } },
    ],
  }],
};

const USAGE_DOCS_ROUTE_SEO = {};
for (const page of USAGE_DOCS_PAGES) {
  const seoLookup = {
    index: {
      title: 'PDF Form Automation Docs and Workflow Guide | DullyPDF',
      description: 'Learn the full DullyPDF workflow: PDF field detection, OpenAI rename and mapping, editor cleanup, and Search & Fill output steps.',
      keywords: ['pdf form automation docs', 'fillable form workflow', 'pdf template workflow'],
    },
    'getting-started': {
      title: 'How to Convert PDF to Fillable Form Template | DullyPDF Docs',
      description: 'Follow a practical quick-start for turning a PDF into a reusable fillable template with mapping and Search & Fill validation.',
      keywords: ['convert pdf to fillable form', 'fillable pdf setup guide'],
    },
    detection: {
      title: 'AI PDF Form Field Detection Guide | DullyPDF Docs',
      description: 'Understand PDF field detection confidence, geometry constraints, and cleanup strategies for accurate fillable templates.',
      keywords: ['pdf form field detection', 'ai pdf detection', 'detect fillable fields in pdf'],
    },
    'rename-mapping': {
      title: 'Map PDF Fields to Database Template Columns | DullyPDF Docs',
      description: 'Use OpenAI rename and schema mapping to align detected PDF fields with database headers for repeatable auto-fill workflows.',
      keywords: ['map pdf fields to database', 'pdf to database template', 'pdf schema mapping'],
    },
    'editor-workflow': {
      title: 'Edit Fillable PDF Fields and Template Geometry | DullyPDF Docs',
      description: 'Use overlay, field list, and inspector tools to refine field names, types, and coordinates before production use.',
      keywords: ['editable fillable pdf template', 'pdf field editor workflow'],
    },
    'search-fill': {
      title: 'Auto Fill PDF from CSV, Excel, and JSON | DullyPDF Docs',
      description: 'Connect local data rows, search records, and auto-fill mapped PDF templates from CSV, Excel, or JSON sources.',
      keywords: ['auto fill pdf from csv', 'fill pdf from excel', 'fill pdf from json'],
    },
    'fill-by-link': {
      title: 'Fill By Link Workflow and Respondent Forms | DullyPDF Docs',
      description: 'Publish native DullyPDF Fill By Link forms from saved templates or groups, share respondent links, and generate PDFs later from stored submissions.',
      keywords: ['fill by link pdf', 'shareable pdf form link', 'respondent form workflow', 'html form to fill pdf'],
    },
    'create-group': {
      title: 'Create Group Workflows for Full PDF Packets | DullyPDF Docs',
      description: 'Create groups of saved templates, switch packet members quickly, Search and Fill full document sets, and batch Rename + Map every template in the group.',
      keywords: ['create group pdf templates', 'group pdf workflow', 'batch rename map pdf packet', 'pdf packet automation'],
    },
    'save-download-profile': {
      title: 'Save Reusable PDF Templates and Download Outputs | DullyPDF Docs',
      description: 'Learn when to download generated files or save templates to your DullyPDF profile for reuse, billing, and collaboration.',
      keywords: ['save pdf template', 'download filled pdf', 'reusable pdf templates'],
    },
    troubleshooting: {
      title: 'PDF Form Automation Troubleshooting Guide | DullyPDF Docs',
      description: 'Diagnose detection, mapping, and fill issues with targeted checks and known validation errors in DullyPDF workflows.',
      keywords: ['pdf automation troubleshooting', 'fillable pdf mapping issues'],
    },
  };

  const seo = seoLookup[page.key];
  USAGE_DOCS_ROUTE_SEO[page.key] = {
    title: seo.title,
    description: seo.description,
    canonicalPath: page.path,
    keywords: seo.keywords,
    structuredData: USAGE_DOCS_FAQ_SCHEMAS[page.key] || undefined,
    bodyContent: {
      heading: page.title,
      paragraphs: [page.summary],
      sectionTitles: page.sectionTitles,
    },
  };
}

const INTENT_ROUTE_SEO = {};
for (const page of INTENT_PAGES) {
  INTENT_ROUTE_SEO[page.key] = {
    title: page.seoTitle,
    description: page.seoDescription,
    canonicalPath: page.path,
    keywords: page.seoKeywords,
    structuredData: toFaqSchema(page.faqs),
    bodyContent: {
      heading: page.heroTitle,
      paragraphs: [page.heroSummary],
      valuePoints: page.valuePoints,
      proofPoints: page.proofPoints,
      faqs: page.faqs,
    },
  };
}

const INTENT_HUB_ROUTE_SEO = {
  workflows: {
    title: 'Workflow Library for PDF Automation | DullyPDF',
    description:
      'Explore DullyPDF workflow pages for converting PDFs to fillable templates, mapping fields to schemas, and auto-filling from structured data.',
    canonicalPath: '/workflows',
    keywords: [
      'pdf workflow library',
      'pdf to fillable form workflow',
      'pdf mapping and autofill workflows',
    ],
    bodyContent: {
      heading: 'Workflow Library for PDF Automation',
      paragraphs: [
        'Browse workflow-first landing pages for converting PDFs to fillable templates, mapping fields to structured schemas, and filling forms from repeat records.',
      ],
      sections: INTENT_PAGES
        .filter((page) => page.category === 'workflow')
        .map((page) => ({ title: page.navLabel, description: page.heroSummary })),
    },
  },
  industries: {
    title: 'Industry PDF Automation Solutions | DullyPDF',
    description:
      'Explore DullyPDF industry pages for healthcare, insurance, legal, HR, finance, and other repeat PDF automation workflows.',
    canonicalPath: '/industries',
    keywords: [
      'industry pdf automation',
      'healthcare insurance legal pdf workflows',
      'pdf form automation by industry',
    ],
    bodyContent: {
      heading: 'Industry Solutions for Repeat PDF Workflows',
      paragraphs: [
        'Browse industry-specific landing pages for healthcare, insurance, legal, HR, finance, logistics, and other document-heavy operations that still rely on recurring PDF packets.',
      ],
      sections: INTENT_PAGES
        .filter((page) => page.category === 'industry')
        .map((page) => ({ title: page.navLabel, description: page.heroSummary })),
    },
  },
};

const FEATURE_PLAN_ROUTE_SEO = {};
for (const page of FEATURE_PLAN_PAGES) {
  FEATURE_PLAN_ROUTE_SEO[page.key] = {
    title: page.seoTitle,
    description: page.seoDescription,
    canonicalPath: page.path,
    keywords: page.seoKeywords,
    structuredData: toFaqSchema(page.faqs),
    bodyContent: {
      heading: page.heroTitle,
      paragraphs: [page.heroSummary],
      valuePoints: page.valuePoints,
      sections: page.detailSections.map((section) => ({
        title: section.title,
        description: section.items.join(' '),
      })),
      faqs: page.faqs,
    },
  };
}

// ---------------------------------------------------------------------------
// All routes consolidated
// ---------------------------------------------------------------------------

/** @type {Array<{path: string, seo: object, kind: string, pageKey?: string}>} */
export const ALL_ROUTES = [
  { path: '/', seo: HOME_ROUTE_SEO, kind: 'home' },
  { path: '/privacy', seo: LEGAL_ROUTE_SEO.privacy, kind: 'legal', pageKey: 'privacy' },
  { path: '/terms', seo: LEGAL_ROUTE_SEO.terms, kind: 'legal', pageKey: 'terms' },
  { path: '/workflows', seo: INTENT_HUB_ROUTE_SEO.workflows, kind: 'intent-hub', pageKey: 'workflows' },
  { path: '/industries', seo: INTENT_HUB_ROUTE_SEO.industries, kind: 'intent-hub', pageKey: 'industries' },
  ...FEATURE_PLAN_PAGES.map((page) => ({
    path: page.path,
    seo: FEATURE_PLAN_ROUTE_SEO[page.key],
    kind: 'feature-plan',
    pageKey: page.key,
  })),
  ...USAGE_DOCS_PAGES.map((page) => ({
    path: page.path,
    seo: USAGE_DOCS_ROUTE_SEO[page.key],
    kind: 'usage-docs',
    pageKey: page.key,
  })),
  ...INTENT_PAGES.map((page) => ({
    path: page.path,
    seo: INTENT_ROUTE_SEO[page.key],
    kind: 'intent',
    pageKey: page.key,
    category: page.category,
  })),
];

// Convenience export: just the paths
export const INDEXABLE_PUBLIC_ROUTE_PATHS = ALL_ROUTES.map((r) => r.path);

// ---------------------------------------------------------------------------
// Footer link structure (used by static HTML generator for every page)
// ---------------------------------------------------------------------------

export const FOOTER_LINKS = {
  product: [
    { label: 'Try DullyPDF', href: '/' },
    { label: 'Getting Started', href: '/usage-docs/getting-started' },
    { label: 'Usage Docs', href: '/usage-docs' },
  ],
  workflows: INTENT_PAGES.filter((p) => p.category === 'workflow').map((p) => ({ label: p.navLabel, href: p.path })),
  industries: INTENT_PAGES.filter((p) => p.category === 'industry').map((p) => ({ label: p.navLabel, href: p.path })),
  resources: [
    { label: 'Blog', href: '/blog' },
    { label: 'Troubleshooting', href: '/usage-docs/troubleshooting' },
  ],
  legal: [
    { label: 'Privacy Policy', href: '/privacy' },
    { label: 'Terms of Service', href: '/terms' },
  ],
};

// ---------------------------------------------------------------------------
// Blog posts (mirrors frontend/src/config/blogPosts.ts)
// ---------------------------------------------------------------------------

const BLOG_POSTS = [
  {
    slug: 'how-to-convert-pdf-to-fillable-form',
    title: 'How to Convert a PDF to a Fillable Form Without Adobe Acrobat',
    seoTitle: 'Convert PDF to Fillable Form Without Adobe Acrobat | DullyPDF Blog',
    seoDescription: 'Learn how to convert any PDF into a fillable form without Acrobat. DullyPDF uses AI field detection to create reusable templates for free.',
    seoKeywords: ['pdf to fillable form without acrobat', 'convert pdf to fillable form free', 'fillable pdf without adobe'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Adobe Acrobat is expensive and overkill for most fillable form needs. This guide shows how to convert any PDF into a fillable template using AI-powered field detection in your browser.',
    sections: [
      { id: 'why-skip-acrobat', title: 'Why skip Adobe Acrobat?', body: 'Adobe Acrobat Pro costs $23/month and requires installation. Browser-based tools like DullyPDF detect fields automatically and save reusable templates without any desktop software.' },
      { id: 'step-by-step', title: 'Step-by-step: convert a PDF to fillable form', body: 'Upload your PDF to DullyPDF (up to 50MB). The AI detection pipeline identifies text fields, checkboxes, date fields, and signature areas with confidence scores.' },
      { id: 'field-detection', title: 'How AI field detection works', body: 'DullyPDF uses the CommonForms ML model to scan each page and identify input regions with confidence scores.' },
      { id: 'mapping-schema', title: 'Map fields to your database schema', body: 'Upload a CSV, Excel, or JSON schema file and let OpenAI rename and map fields to your column headers.' },
      { id: 'reuse-templates', title: 'Save and reuse templates', body: 'Save your template to your DullyPDF profile for repeat use without re-detection or re-mapping.' },
    ],
  },
  {
    slug: 'auto-fill-pdf-from-spreadsheet',
    title: 'How to Auto-Fill PDF Forms From a Spreadsheet (CSV or Excel)',
    seoTitle: 'Auto-Fill PDF Forms From CSV or Excel Spreadsheet | DullyPDF Blog',
    seoDescription: 'Fill PDF form fields automatically from CSV or Excel spreadsheet rows. Map columns to PDF fields and populate forms in seconds.',
    seoKeywords: ['fill pdf from spreadsheet', 'auto fill pdf from excel', 'fill pdf from csv'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Stop copying and pasting from spreadsheets into PDF forms. Map spreadsheet columns to PDF fields and auto-fill forms from any row.',
    sections: [
      { id: 'the-problem', title: 'The copy-paste problem', body: 'Office teams manually copy data from spreadsheets into PDF forms every day, wasting hours on tedious, error-prone data entry.' },
      { id: 'how-it-works', title: 'How spreadsheet-to-PDF filling works', body: 'DullyPDF connects spreadsheet columns to PDF form fields through schema mapping.' },
      { id: 'search-and-fill', title: 'Search & Fill: find the right record fast', body: 'Search across any column using contains or exact-match mode, then fill all mapped fields with one click.' },
      { id: 'supported-formats', title: 'Supported data formats', body: 'CSV, XLSX, and JSON for row-based filling. TXT for schema-only mapping.' },
      { id: 'tips', title: 'Tips for reliable auto-fill', body: 'Run Rename + Map together. Test with one record before batch processing.' },
    ],
  },
  {
    slug: 'acord-25-certificate-fill-faster',
    title: 'ACORD 25 Certificate of Insurance: How to Fill It Faster',
    seoTitle: 'Fill ACORD 25 Certificate of Insurance Faster | DullyPDF Blog',
    seoDescription: 'Speed up ACORD 25 certificate processing with mapped templates.',
    seoKeywords: ['acord 25 fillable', 'fill acord form automatically', 'acord certificate of insurance automation', 'insurance pdf automation', 'certificate of insurance automation'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Insurance agencies process hundreds of ACORD 25 certificates monthly. Turn the ACORD 25 into a mapped template that fills from your management system data.',
    sections: [
      { id: 'acord-25-overview', title: 'What is the ACORD 25?', body: 'The standard certificate of liability insurance used across the US insurance industry.' },
      { id: 'manual-pain', title: 'Why manual ACORD filling is painful', body: 'ACORD forms have dozens of fields. Manual copy-paste is slow and error-prone.' },
      { id: 'template-workflow', title: 'Create a reusable ACORD 25 template', body: 'Upload, detect, map to your AMS export, and save for repeat use.' },
      { id: 'fill-from-ams', title: 'Fill certificates from your data', body: 'Search for the insured and fill all mapped fields with one click.' },
    ],
  },
  {
    slug: 'insurance-pdf-automation-acord-and-coi-workflows',
    title: 'Insurance PDF Automation: ACORD and Certificate Workflows',
    seoTitle: 'Insurance PDF Automation for ACORD and COI Workflows | DullyPDF Blog',
    seoDescription: 'Learn how insurance teams automate ACORD forms and certificate of insurance PDFs with mapped templates tied to agency data exports.',
    seoKeywords: ['insurance pdf automation', 'insurance form automation', 'certificate of insurance automation', 'acord form automation software', 'auto fill insurance forms'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'If your team handles recurring ACORD packets and COI requests, this workflow shows how to map once and fill insurance PDFs from AMS exports in seconds.',
    sections: [
      { id: 'why-insurance-pdfs-stay-manual', title: 'Why insurance PDF workflows stay manual', body: 'Insurance teams still process many forms as PDFs and repeatedly retype insured, policy, and coverage data.' },
      { id: 'acord-and-carrier-forms', title: 'ACORD plus carrier-specific form variants', body: 'Treat each recurring ACORD or carrier form as a reusable template to avoid repeated setup work.' },
      { id: 'map-from-ams-exports', title: 'Map once from AMS or broker exports', body: 'Map insured, producer, policy, and coverage fields once, then fill from structured data exports.' },
      { id: 'coi-turnaround', title: 'Speed up certificate of insurance turnaround', body: 'Mapped templates help account teams search a policy record, fill quickly, and validate key fields.' },
      { id: 'implementation-checklist', title: 'Implementation checklist for insurance teams', body: 'Start with one high-volume form, validate with real records, then roll out to adjacent forms.' },
    ],
  },
  {
    slug: 'pdf-form-field-detection-how-ai-finds-fields',
    title: 'PDF Form Field Detection: How AI Finds Fields in Any PDF',
    seoTitle: 'PDF Form Field Detection: How AI Finds Fields | DullyPDF Blog',
    seoDescription: 'Learn how AI-powered field detection identifies text fields, checkboxes, and signatures in any PDF.',
    seoKeywords: ['pdf form field detection', 'detect fields in pdf', 'ai pdf field detection'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'How does AI find form fields in a PDF that has no embedded form data? This post explains the detection pipeline and confidence scoring.',
    sections: [
      { id: 'the-challenge', title: 'The field detection challenge', body: 'Most PDFs are not fillable and require image analysis to find form fields.' },
      { id: 'how-detection-works', title: 'How DullyPDF detection works', body: 'The CommonForms ML model analyzes rendered page images to identify input regions.' },
      { id: 'confidence-scores', title: 'Understanding confidence scores', body: 'High (80%+), medium (65-80%), low (below 65%).' },
      { id: 'tips-for-better-results', title: 'Tips for better detection results', body: 'Use clean, high-resolution PDFs for best results.' },
      { id: 'after-detection', title: 'What to do after detection', body: 'Review low-confidence detections first, then proceed to rename and mapping.' },
    ],
  },
  {
    slug: 'map-pdf-fields-to-database-columns',
    title: 'Map PDF Fields to Database Columns: A Step-by-Step Guide',
    seoTitle: 'Map PDF Fields to Database Columns Step-by-Step | DullyPDF Blog',
    seoDescription: 'Learn how to map PDF form fields to database columns for automated filling.',
    seoKeywords: ['pdf to database', 'map pdf fields to database', 'pdf database mapping'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Mapping PDF fields to database columns transforms a fillable form into an automated data-entry tool.',
    sections: [
      { id: 'why-mapping-matters', title: 'Why mapping matters', body: 'Without mapping, each PDF field is just a named rectangle. Mapping links field names to data columns.' },
      { id: 'prepare-your-schema', title: 'Prepare your schema file', body: 'Export database headers as CSV, Excel, or JSON with clean snake_case naming.' },
      { id: 'rename-first', title: 'Rename fields before mapping', body: 'Run OpenAI Rename first for better mapping accuracy.' },
      { id: 'run-mapping', title: 'Run the mapping step', body: 'Upload schema and run Map or Rename + Map combined workflow.' },
      { id: 'test-and-save', title: 'Test and save your mapped template', body: 'Test with Search & Fill, then save for repeat use.' },
    ],
  },
  {
    slug: 'automate-medical-intake-forms',
    title: 'Automate Medical Intake Forms: Reduce Front-Desk Data Entry by 80%',
    seoTitle: 'Automate Medical Intake Forms: Cut Data Entry 80% | DullyPDF Blog',
    seoDescription: 'Reduce front-desk data entry by automating patient intake PDF forms.',
    seoKeywords: ['automate patient intake forms', 'healthcare pdf automation', 'medical intake form automation'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Front-desk staff spend hours retyping patient data into intake PDFs. Create mapped templates that fill automatically from patient records.',
    sections: [
      { id: 'intake-form-problem', title: 'The intake form data entry problem', body: 'Medical offices manually type patient data into stacks of intake PDFs daily.' },
      { id: 'template-approach', title: 'The template-based approach', body: 'Create a mapped template once and reuse it for every patient visit.' },
      { id: 'checkbox-handling', title: 'Handling medical checkboxes', body: 'DullyPDF supports yes_no, presence, enum, and list checkbox rule types.' },
      { id: 'privacy-note', title: 'Privacy considerations', body: 'Patient data stays in your browser during Search & Fill operations.' },
      { id: 'getting-started', title: 'Getting started with healthcare automation', body: 'Start with your most frequently used intake form.' },
    ],
  },
  {
    slug: 'fillable-pdf-field-names-why-they-matter',
    title: 'Fillable PDF Field Names: Why They Matter and How to Fix Them',
    seoTitle: 'PDF Field Names: Why They Matter & How to Fix | DullyPDF Blog',
    seoDescription: 'Understand why consistent PDF field names are critical for auto-fill and how AI rename fixes it.',
    seoKeywords: ['pdf field names', 'rename pdf form fields', 'pdf field naming'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Bad field names are the number-one cause of mapping failures. This post explains why field naming matters and how AI rename fixes it.',
    sections: [
      { id: 'why-names-matter', title: 'Why field names matter', body: 'Meaningful, consistent field names are essential for accurate schema mapping.' },
      { id: 'common-naming-problems', title: 'Common naming problems', body: 'Detection outputs and PDF tools often produce meaningless field names.' },
      { id: 'ai-rename', title: 'How AI rename works', body: 'OpenAI analyzes page images and labels to suggest meaningful field names.' },
      { id: 'rename-best-practices', title: 'Rename best practices', body: 'Run rename before mapping. Review low-confidence renames manually.' },
      { id: 'combined-workflow', title: 'Rename + Map combined workflow', body: 'Use Rename + Map for best results in a single step.' },
    ],
  },
  {
    slug: 'hr-onboarding-stop-retyping-employee-data',
    title: 'HR Onboarding Paperwork: Stop Retyping Employee Data Into PDFs',
    seoTitle: 'Stop Retyping HR Onboarding Data Into PDFs | DullyPDF Blog',
    seoDescription: 'Automate HR onboarding paperwork by mapping employee data to PDF form templates.',
    seoKeywords: ['hr onboarding form automation', 'automate employee paperwork', 'hr pdf automation'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'HR teams retype the same employee data across W-4s, I-9s, benefits enrollments, and policy acknowledgments.',
    sections: [
      { id: 'onboarding-pain', title: 'The onboarding paperwork problem', body: 'Every new hire means a stack of PDF forms with the same data retyped.' },
      { id: 'one-source-many-forms', title: 'One data source, many forms', body: 'Export your HRIS data and create mapped templates for each form type.' },
      { id: 'template-setup', title: 'Setting up onboarding templates', body: 'Upload each form, detect fields, map to HRIS columns, and save.' },
      { id: 'batch-workflow', title: 'Filling forms for each new hire', body: 'Search for the employee and fill each template with their data.' },
      { id: 'tips', title: 'Tips for HR teams', body: 'Start with the most frequently used forms. Test with a few employees first.' },
    ],
  },
  {
    slug: 'dullypdf-vs-adobe-acrobat-pdf-form-automation',
    title: 'DullyPDF vs Adobe Acrobat for PDF Form Automation',
    seoTitle: 'DullyPDF vs Adobe Acrobat for PDF Form Automation | Comparison',
    seoDescription: 'Compare DullyPDF and Adobe Acrobat for PDF form automation.',
    seoKeywords: ['dullypdf vs acrobat', 'acrobat fillable form alternative', 'pdf form automation comparison'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'Adobe Acrobat is the industry standard for PDF editing, but its form automation features are limited compared to DullyPDF\'s AI-driven workflow.',
    sections: [
      { id: 'overview', title: 'Overview: different tools for different needs', body: 'Acrobat is a general PDF editor. DullyPDF is purpose-built for database-mapped template filling.' },
      { id: 'field-detection', title: 'Field detection', body: 'Acrobat detects existing form fields. DullyPDF uses AI to detect fields even in flat PDFs.' },
      { id: 'schema-mapping', title: 'Schema mapping and auto-fill', body: 'Acrobat does not support schema mapping. DullyPDF links fields to data columns for one-click filling.' },
      { id: 'pricing', title: 'Pricing comparison', body: 'Acrobat Pro costs $23/month. DullyPDF offers free detection with paid AI features.' },
      { id: 'when-to-choose', title: 'When to choose each tool', body: 'Choose Acrobat for general PDF editing. Choose DullyPDF for automated form filling from data.' },
    ],
  },
  {
    slug: 'dullypdf-vs-jotform-pdf-data-collection',
    title: 'DullyPDF vs JotForm for PDF Data Collection',
    seoTitle: 'DullyPDF vs JotForm for PDF Data Collection | Comparison',
    seoDescription: 'Compare DullyPDF and JotForm for PDF-based data collection workflows.',
    seoKeywords: ['dullypdf vs jotform', 'jotform alternative for pdf', 'pdf data collection comparison'],
    publishedDate: '2026-03-04',
    author: 'DullyPDF Team',
    summary: 'JotForm builds online forms from scratch. DullyPDF works with existing PDF forms.',
    sections: [
      { id: 'different-approaches', title: 'Two different approaches to forms', body: 'JotForm creates new web forms. DullyPDF automates existing PDF documents.' },
      { id: 'existing-pdf-workflows', title: 'When you must use existing PDFs', body: 'Industries with mandated PDF formats need DullyPDF, not a form builder.' },
      { id: 'data-privacy', title: 'Data privacy differences', body: 'DullyPDF keeps data rows in-browser. JotForm stores submissions on their servers.' },
      { id: 'when-to-choose', title: 'When to choose each tool', body: 'JotForm for new online forms. DullyPDF for automating existing PDF forms.' },
    ],
  },
];

// Add blog routes to ALL_ROUTES
const BLOG_INDEX_ROUTE = {
  path: '/blog',
  seo: {
    title: 'PDF Automation Blog | DullyPDF',
    description: 'Guides, tutorials, and best practices for converting PDFs to fillable forms, mapping fields to databases, and automating form-filling workflows.',
    canonicalPath: '/blog',
    keywords: ['pdf automation blog', 'fillable form guides', 'pdf form tutorials'],
    structuredData: [{
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'DullyPDF Blog',
      url: 'https://dullypdf.com/blog',
      description: 'Guides and tutorials for PDF form automation, field detection, schema mapping, and auto-fill workflows.',
    }],
    bodyContent: {
      heading: 'PDF Automation Guides & Tutorials',
      paragraphs: ['Practical guides for converting PDFs to fillable forms, mapping fields to databases, and automating repetitive form-filling workflows.'],
    },
  },
  kind: 'blog-index',
};

const BLOG_POST_ROUTES = BLOG_POSTS.map((post) => ({
  path: `/blog/${post.slug}`,
  seo: {
    title: post.seoTitle,
    description: post.seoDescription,
    canonicalPath: `/blog/${post.slug}`,
    keywords: post.seoKeywords,
    structuredData: [{
      '@context': 'https://schema.org',
      '@type': 'BlogPosting',
      headline: post.title,
      description: post.seoDescription,
      author: { '@type': 'Organization', name: post.author },
      datePublished: post.publishedDate,
      url: `https://dullypdf.com/blog/${post.slug}`,
      publisher: { '@type': 'Organization', name: 'DullyPDF', logo: { '@type': 'ImageObject', url: 'https://dullypdf.com/DullyPDFLogoImproved.png' } },
    }],
    bodyContent: {
      heading: post.title,
      paragraphs: [post.summary],
      sections: post.sections.map((s) => ({ title: s.title, description: s.body })),
    },
  },
  kind: 'blog-post',
  slug: post.slug,
}));

// Append blog routes
ALL_ROUTES.push(BLOG_INDEX_ROUTE);
ALL_ROUTES.push(...BLOG_POST_ROUTES);

// Export raw data for blog/sitemap integration
export { INTENT_PAGES, USAGE_DOCS_PAGES, BLOG_POSTS };
