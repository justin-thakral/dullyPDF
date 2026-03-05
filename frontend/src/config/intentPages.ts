export type IntentPageKey =
  | 'pdf-to-fillable-form'
  | 'pdf-to-database-template'
  | 'fill-pdf-from-csv'
  | 'fill-information-in-pdf'
  | 'fillable-form-field-name'
  | 'healthcare-pdf-automation'
  | 'acord-form-automation'
  | 'insurance-pdf-automation'
  | 'real-estate-pdf-automation'
  | 'government-form-automation'
  | 'finance-loan-pdf-automation'
  | 'hr-pdf-automation'
  | 'legal-pdf-workflow-automation'
  | 'education-form-automation'
  | 'nonprofit-pdf-form-automation'
  | 'logistics-pdf-automation'
  | 'batch-fill-pdf-forms'
  | 'pdf-checkbox-automation'
  | 'pdf-field-detection-tool'
  | 'construction-pdf-automation'
  | 'accounting-tax-pdf-automation';

export type IntentPageCategory = 'workflow' | 'industry';

export type IntentFaq = {
  question: string;
  answer: string;
};

export type IntentPage = {
  key: IntentPageKey;
  category: IntentPageCategory;
  path: string;
  navLabel: string;
  heroTitle: string;
  heroSummary: string;
  seoTitle: string;
  seoDescription: string;
  seoKeywords: string[];
  valuePoints: string[];
  proofPoints: string[];
  faqs: IntentFaq[];
};

const INTENT_PAGES: IntentPage[] = [
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
      'Convert PDF files into fillable form templates, validate field geometry, and reuse saved forms for repeat workflows in DullyPDF.',
    seoKeywords: [
      'pdf to fillable form',
      'convert pdf to fillable template',
      'fillable form template workflow',
    ],
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
      {
        question: 'Can DullyPDF convert non-fillable PDFs into fillable forms?',
        answer:
          'Yes. DullyPDF detects likely field regions, then lets you refine and save them as a fillable template.',
      },
      {
        question: 'Do I need to edit the PDF file directly?',
        answer:
          'No. You edit overlay field metadata and geometry in the app, without changing the source PDF layout.',
      },
      {
        question: 'Can I reuse a converted fillable template later?',
        answer:
          'Yes. Saved forms preserve PDF bytes and field metadata so you can reopen and refill without rerunning full setup.',
      },
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
    seoKeywords: [
      'pdf to database template',
      'map pdf fields to database columns',
      'pdf schema mapping workflow',
    ],
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
      {
        question: 'How is a PDF database template different from a normal fillable PDF?',
        answer:
          'A database template is explicitly mapped to data headers so rows can be filled predictably instead of manually.',
      },
      {
        question: 'Can I map checkboxes to database values?',
        answer:
          'Yes. DullyPDF supports checkbox grouping metadata and rule-based mapping for boolean, enum, and list-style values.',
      },
      {
        question: 'Can I update mappings later?',
        answer:
          'Yes. Saved templates can be reopened, remapped, and retested as your schema evolves.',
      },
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
    seoKeywords: [
      'fill pdf from csv',
      'fill pdf from excel',
      'fill pdf from json',
    ],
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
      {
        question: 'Can I fill a PDF directly from CSV rows?',
        answer:
          'Yes. After mapping, select a row in Search & Fill and DullyPDF writes matching values into PDF fields.',
      },
      {
        question: 'Does DullyPDF support Excel files too?',
        answer:
          'Yes. XLSX is supported alongside CSV and JSON for row-based Search & Fill workflows.',
      },
      {
        question: 'What if some fields do not fill correctly?',
        answer:
          'Review mappings and checkbox rules, then run a clear-and-refill verification pass before production output.',
      },
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
    seoKeywords: [
      'fill information in pdf',
      'fill data in pdf forms',
      'automated pdf form filling',
    ],
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
      {
        question: 'Can I fill patient or client information into a PDF quickly?',
        answer:
          'Yes. DullyPDF is designed for repeated intake and form workflows where data comes from structured records.',
      },
      {
        question: 'Do I have to re-map fields every time?',
        answer:
          'No. Once saved, templates retain mapping metadata so you can run repeat fills with less setup.',
      },
      {
        question: 'Does this work for checkbox-heavy forms?',
        answer:
          'Yes. Checkbox metadata and rule precedence are part of the mapping and fill workflow.',
      },
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
    seoKeywords: [
      'fillable form field name',
      'pdf field naming standardization',
      'pdf field rename mapping',
    ],
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
      {
        question: 'Why does fillable form field naming matter?',
        answer:
          'Consistent field names improve mapping accuracy and reduce missing values during automated fill runs.',
      },
      {
        question: 'Can I rename fields without changing PDF appearance?',
        answer:
          'Yes. Naming changes happen in template metadata and do not alter the visual PDF source layout.',
      },
      {
        question: 'Can I combine field rename with database mapping?',
        answer:
          'Yes. DullyPDF supports rename-only, map-only, and combined rename-plus-map workflows.',
      },
    ],
  },
  {
    key: 'healthcare-pdf-automation',
    category: 'industry',
    path: '/healthcare-pdf-automation',
    navLabel: 'Healthcare PDF Automation',
    heroTitle: 'Automate Medical Intake and Healthcare PDF Form Workflows',
    heroSummary:
      'Convert medical intake, registration, history, consent, and HIPAA release PDFs into reusable templates that map directly to structured data columns.',
    seoTitle: 'Healthcare PDF Form Automation for Medical Intake | DullyPDF',
    seoDescription:
      'Automate medical intake forms, map patient intake PDFs to database-ready templates, and fill healthcare PDFs from structured records.',
    seoKeywords: [
      'automate medical intake forms',
      'patient intake pdf to database',
      'healthcare pdf form automation',
      'patient registration form automation',
      'hipaa release form automation',
    ],
    valuePoints: [
      'Build reusable templates for intake, registration, history, and consent packets.',
      'Normalize field names so front-desk teams can map once and reuse consistently.',
      'Support checkbox-heavy workflows for symptoms, disclosures, and releases.',
    ],
    proofPoints: [
      'CSV/XLSX/JSON rows are searchable in-browser for controlled patient record lookup.',
      'Detection plus editor cleanup helps handle scanned and native healthcare PDFs.',
      'Templates can be saved and reused for recurring appointment workflows.',
    ],
    faqs: [
      {
        question: 'Can DullyPDF automate patient intake PDFs and registration forms?',
        answer:
          'Yes. You can detect fields, refine them in the editor, map to schema headers, and then fill forms from structured intake data.',
      },
      {
        question: 'Does DullyPDF work for HIPAA release and consent forms?',
        answer:
          'Yes. Checkbox and text field mapping supports release and consent-style healthcare forms.',
      },
      {
        question: 'Can healthcare teams reuse the same mapped template daily?',
        answer:
          'Yes. Saved templates retain PDF bytes, field metadata, and mapping context for repeat usage.',
      },
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
    seoKeywords: [
      'acord form automation',
      'auto fill acord 25 pdf',
      'certificate of insurance automation',
      'acord certificate automation',
      'insurance pdf automation',
      'acord 24 automation',
      'acord 27 automation',
      'acord 28 automation',
      'acord 126 automation',
      'acord 140 automation',
    ],
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
      {
        question: 'Can DullyPDF auto-fill ACORD 25 and similar insurance forms?',
        answer:
          'Yes. DullyPDF supports mapped template workflows for common ACORD-style PDF forms.',
      },
      {
        question: 'Can insurance teams map ACORD fields to internal database columns?',
        answer:
          'Yes. Schema mapping aligns PDF fields with your preferred naming and column structure.',
      },
      {
        question: 'Does this support ACORD renewals and recurring certificate requests?',
        answer:
          'Yes. Teams can map once and fill repeatedly instead of retyping policy and certificate data every cycle.',
      },
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
    seoKeywords: [
      'insurance pdf automation',
      'insurance form automation',
      'certificate of insurance automation',
      'insurance certificate pdf automation',
      'auto fill insurance forms',
      'acord form automation',
    ],
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
      {
        question: 'Can DullyPDF automate insurance PDFs beyond ACORD 25?',
        answer:
          'Yes. Teams use it for ACORD 24/27/28/126/140 and carrier-specific insurance PDFs that require repeat filling.',
      },
      {
        question: 'Can insurance teams map form fields to agency management exports?',
        answer:
          'Yes. Map once to your export schema, then run repeat fills from structured records in Search & Fill.',
      },
      {
        question: 'Is this useful for certificate of insurance turnaround speed?',
        answer:
          'Yes. Reusable mapped templates reduce manual retyping and help teams produce certificates faster with fewer entry errors.',
      },
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
    seoKeywords: [
      'automate rental application pdf',
      'mortgage pdf to database',
      'real estate form automation',
      'lease agreement pdf automation',
      'property inspection form automation',
    ],
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
      {
        question: 'Can DullyPDF automate rental application PDF workflows?',
        answer:
          'Yes. Rental application and lease-style forms can be mapped and filled from structured tenant data.',
      },
      {
        question: 'Does it work for mortgage-related PDF forms?',
        answer:
          'Yes. Mortgage and lending packets can be converted into reusable mapped templates.',
      },
      {
        question: 'Can real estate teams reuse templates across properties?',
        answer:
          'Yes. Saved templates can be reloaded and reused for recurring packet types.',
      },
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
    seoKeywords: [
      'government form automation',
      'pdf permit automation',
      'tax form database mapping',
      'public sector pdf automation',
      'license renewal form automation',
    ],
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
      {
        question: 'Can DullyPDF automate permit and license PDF forms?',
        answer:
          'Yes. Permit and license forms can be converted, mapped, and reused as structured templates.',
      },
      {
        question: 'Does this help with tax and compliance form workflows?',
        answer:
          'Yes. Standardized mapping and row-based fill reduce repetitive manual entry for recurring forms.',
      },
      {
        question: 'Can agencies keep one canonical template per form type?',
        answer:
          'Yes. Saved template workflows support a canonical setup per recurring government form.',
      },
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
    seoKeywords: [
      'loan pdf automation',
      'loan application pdf automation',
      'fill pdf financial form from database',
      'financial disclosure pdf automation',
      'kyc aml pdf automation',
    ],
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
      {
        question: 'Can DullyPDF automate loan application PDFs?',
        answer:
          'Yes. Loan application templates can be mapped to structured data and reused for repetitive fill tasks.',
      },
      {
        question: 'Does DullyPDF support financial disclosure form filling?',
        answer:
          'Yes. Disclosure and related finance forms can be filled from mapped record fields.',
      },
      {
        question: 'Can lenders use this for KYC and AML paperwork workflows?',
        answer:
          'Yes. Mapped template workflows can support recurring compliance document preparation.',
      },
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
    seoKeywords: [
      'automate hr onboarding forms',
      'pdf employee form automation',
      'onboarding packet pdf automation',
      'benefits enrollment form automation',
      'w4 1099 pdf automation',
    ],
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
      {
        question: 'Can DullyPDF automate onboarding PDF packets?',
        answer:
          'Yes. HR teams can map onboarding templates once and fill forms from structured employee records.',
      },
      {
        question: 'Does it support employee tax and benefits forms?',
        answer:
          'Yes. HR-focused PDF templates can include tax and benefits form workflows.',
      },
      {
        question: 'Can HR teams reuse templates for every new hire?',
        answer:
          'Yes. Saved templates support repeat onboarding runs with minimal setup.',
      },
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
    seoKeywords: [
      'legal pdf workflow automation',
      'court document automation',
      'contract pdf to database',
      'legal intake form automation',
      'affidavit template automation',
    ],
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
      {
        question: 'Can DullyPDF automate legal contract and filing PDFs?',
        answer:
          'Yes. Legal teams can map recurring templates and fill them from structured client and case records.',
      },
      {
        question: 'Does this work for affidavit and declaration form templates?',
        answer:
          'Yes. Affidavit and declaration-style PDFs can be standardized and reused as mapped templates.',
      },
      {
        question: 'Can law firms maintain consistent field naming across templates?',
        answer:
          'Yes. Rename plus mapping workflows are designed to normalize inconsistent field labels.',
      },
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
    seoKeywords: [
      'automate student application pdfs',
      'university form pdf automation',
      'education pdf automation',
      'enrollment form automation',
      'transcript request form automation',
    ],
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
      {
        question: 'Can DullyPDF automate admissions and enrollment PDFs?',
        answer:
          'Yes. Admissions teams can map and reuse student form templates for repeat cycles.',
      },
      {
        question: 'Does this support transcript request and consent forms?',
        answer:
          'Yes. Education teams can automate repetitive transcript and consent form workflows.',
      },
      {
        question: 'Can schools use one template across semesters?',
        answer:
          'Yes. Saved templates can be reused and adjusted as forms evolve.',
      },
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
    seoKeywords: [
      'nonprofit pdf form automation',
      'grant pdf automation',
      'volunteer registration pdf automation',
      'human services form automation',
      'nonprofit intake pdf automation',
    ],
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
      {
        question: 'Can DullyPDF automate grant and volunteer PDF workflows?',
        answer:
          'Yes. Nonprofit teams can map recurring forms and populate them from structured records.',
      },
      {
        question: 'Is this useful for human services intake packets?',
        answer:
          'Yes. Intake-style packet templates can be standardized and reused across programs.',
      },
      {
        question: 'Can smaller teams benefit from template reuse?',
        answer:
          'Yes. Template reuse reduces repetitive manual entry and improves consistency.',
      },
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
    seoKeywords: [
      'transport pdf automation',
      'logistics form to database',
      'bill of lading automation',
      'delivery receipt pdf automation',
      'safety inspection form automation',
    ],
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
      {
        question: 'Can DullyPDF automate bill of lading and delivery receipt PDFs?',
        answer:
          'Yes. Logistics teams can map those recurring forms and fill them from structured records.',
      },
      {
        question: 'Does this support transportation safety inspection forms?',
        answer:
          'Yes. Inspection forms can be standardized and reused as mapped templates.',
      },
      {
        question: 'Can operations teams maintain one template per document type?',
        answer:
          'Yes. Saved template workflows support canonical forms for recurring logistics tasks.',
      },
    ],
  },
  {
    key: 'batch-fill-pdf-forms',
    category: 'workflow',
    path: '/batch-fill-pdf-forms',
    navLabel: 'Batch Fill PDF Forms',
    heroTitle: 'Batch Fill PDF Forms From Multiple Records',
    heroSummary:
      'Fill the same PDF template with multiple records from your CSV, Excel, or JSON data. Map once, then fill form after form in seconds.',
    seoTitle: 'Batch Fill PDF Forms From CSV, Excel, and JSON | DullyPDF',
    seoDescription:
      'Batch fill PDF forms by mapping a template once and populating it from multiple records in CSV, Excel, or JSON data sources.',
    seoKeywords: [
      'batch fill pdf forms',
      'bulk pdf filling',
      'fill multiple pdfs from spreadsheet',
      'batch pdf form automation',
    ],
    valuePoints: [
      'Map a PDF template once and fill it from any number of records.',
      'Search and select rows individually for controlled batch output.',
      'Clear and refill between records to verify mapping quality.',
    ],
    proofPoints: [
      'Search & Fill supports fast row switching for sequential form filling.',
      'Templates persist mapping context between fill sessions.',
      'Filled output can be downloaded immediately for each record.',
    ],
    faqs: [
      {
        question: 'Can I fill the same PDF form with different records?',
        answer:
          'Yes. After mapping, use Search & Fill to select any row and populate the template, then clear and fill with the next record.',
      },
      {
        question: 'Does DullyPDF support bulk PDF generation?',
        answer:
          'DullyPDF fills one record at a time through Search & Fill for controlled output. Map once, then fill repeatedly from your data rows.',
      },
      {
        question: 'What data sources work for batch filling?',
        answer:
          'CSV, XLSX, and JSON files with row data. Each row represents one form to fill.',
      },
    ],
  },
  {
    key: 'pdf-checkbox-automation',
    category: 'workflow',
    path: '/pdf-checkbox-automation',
    navLabel: 'PDF Checkbox Automation',
    heroTitle: 'Automate PDF Checkbox Fields With Rule-Based Logic',
    heroSummary:
      'DullyPDF handles complex checkbox scenarios including yes/no pairs, enum selections, multi-select lists, and presence-based toggles with configurable rule logic.',
    seoTitle: 'PDF Checkbox Automation With Rule-Based Fill Logic | DullyPDF',
    seoDescription:
      'Automate PDF checkbox filling with yes/no, enum, presence, and list rules. Map checkbox groups to data columns for reliable automated form output.',
    seoKeywords: [
      'pdf checkbox automation',
      'auto fill checkboxes pdf',
      'pdf checkbox rules',
      'checkbox form automation',
    ],
    valuePoints: [
      'Support four checkbox rule types: yes_no, presence, enum, and list.',
      'Map checkbox groups and option keys to structured data columns.',
      'Handle multi-select checkbox fields with list-based splitting.',
    ],
    proofPoints: [
      'Checkbox rule precedence follows a defined six-step resolution order.',
      'Built-in alias fallback groups handle common medical and HR patterns.',
      'Boolean token normalization covers yes/no, true/false, 1/0, and variants.',
    ],
    faqs: [
      {
        question: 'Can DullyPDF auto-fill checkboxes in PDF forms?',
        answer:
          'Yes. DullyPDF supports rule-based checkbox automation with yes/no, presence, enum, and list modes.',
      },
      {
        question: 'How does checkbox group mapping work?',
        answer:
          'Each checkbox has a groupKey and optionKey. Map the group to a data column, and DullyPDF selects the correct option based on the cell value and rule type.',
      },
      {
        question: 'Does this work for forms with dozens of checkboxes?',
        answer:
          'Yes. Checkbox-heavy forms like medical intake and benefits enrollment are common use cases for rule-based automation.',
      },
    ],
  },
  {
    key: 'pdf-field-detection-tool',
    category: 'workflow',
    path: '/pdf-field-detection-tool',
    navLabel: 'PDF Field Detection Tool',
    heroTitle: 'Detect Form Fields in Any PDF With AI',
    heroSummary:
      'Upload any PDF and let AI detect text fields, checkboxes, date fields, and signature areas automatically. Review confidence scores and refine in the visual editor.',
    seoTitle: 'AI PDF Field Detection Tool for Form Automation | DullyPDF',
    seoDescription:
      'Detect form fields in any PDF with AI-powered field detection. Identify text, checkbox, date, and signature fields with confidence scoring.',
    seoKeywords: [
      'pdf field detection',
      'detect form fields in pdf',
      'pdf field detection tool',
      'ai form field detection',
    ],
    valuePoints: [
      'Detect text, date, checkbox, and signature fields automatically.',
      'Review confidence scores to prioritize fields needing manual review.',
      'Refine detection results with visual editor tools.',
    ],
    proofPoints: [
      'Supports PDF uploads up to 50MB with multi-page detection.',
      'Confidence tiers: high (80%+), medium (65-80%), low (below 65%).',
      'Field geometry uses normalized top-left origin coordinates.',
    ],
    faqs: [
      {
        question: 'Can DullyPDF detect fields in scanned PDFs?',
        answer:
          'Yes. The AI model analyzes rendered page images and works with both native and scanned PDFs.',
      },
      {
        question: 'How accurate is field detection?',
        answer:
          'Detection quality depends on PDF clarity. High-confidence detections (80%+) are typically accurate. Low-confidence items should be reviewed.',
      },
      {
        question: 'Can I add fields the AI missed?',
        answer:
          'Yes. The editor lets you add text, date, checkbox, and signature fields manually for regions the detector did not identify.',
      },
    ],
  },
  {
    key: 'construction-pdf-automation',
    category: 'industry',
    path: '/construction-pdf-automation',
    navLabel: 'Construction PDF Automation',
    heroTitle: 'Construction Permit and Safety Form PDF Automation',
    heroSummary:
      'Automate construction permits, safety inspection forms, change orders, and daily logs by mapping PDF fields to project and subcontractor data.',
    seoTitle: 'Construction PDF Form Automation for Permits and Safety | DullyPDF',
    seoDescription:
      'Automate construction permit PDFs, safety inspection forms, and change orders with mapped templates and structured project data.',
    seoKeywords: [
      'construction pdf automation',
      'permit form automation',
      'safety inspection form pdf',
      'construction change order automation',
      'daily log pdf automation',
    ],
    valuePoints: [
      'Standardize permit, inspection, and change order form templates.',
      'Map project and subcontractor data fields to form inputs.',
      'Reuse templates across job sites and recurring submission cycles.',
    ],
    proofPoints: [
      'Search & Fill supports fast row selection from project records.',
      'Editor tools handle variable legacy form layouts from different agencies.',
      'Template reuse reduces repetitive data entry for field office teams.',
    ],
    faqs: [
      {
        question: 'Can DullyPDF automate construction permit PDF forms?',
        answer:
          'Yes. Upload permit forms, detect fields, map to your project data, and fill them from structured records.',
      },
      {
        question: 'Does this work for safety inspection and daily log forms?',
        answer:
          'Yes. Safety inspection and daily log PDFs can be standardized as mapped templates.',
      },
      {
        question: 'Can GCs reuse templates across multiple job sites?',
        answer:
          'Yes. Saved templates can be reused for recurring form types across projects.',
      },
    ],
  },
  {
    key: 'accounting-tax-pdf-automation',
    category: 'industry',
    path: '/accounting-tax-pdf-automation',
    navLabel: 'Accounting & Tax PDF Automation',
    heroTitle: 'Accounting and Tax Form PDF Automation Workflows',
    heroSummary:
      'Automate W-9s, 1099s, engagement letters, and other accounting-related PDFs by mapping form fields to client records and tax preparation data.',
    seoTitle: 'Accounting and Tax PDF Form Automation | DullyPDF',
    seoDescription:
      'Automate accounting and tax PDF forms, fill W-9 and 1099 templates from client data, and streamline CPA firm document workflows.',
    seoKeywords: [
      'accounting pdf automation',
      'tax form pdf automation',
      'w9 form automation',
      '1099 pdf automation',
      'cpa firm pdf automation',
    ],
    valuePoints: [
      'Map client and entity data to recurring tax and engagement forms.',
      'Reduce rekeying for W-9 collection, 1099 preparation, and engagement letters.',
      'Support repeat workflows across clients and tax seasons.',
    ],
    proofPoints: [
      'Template reuse supports high-volume tax season processing.',
      'Search & Fill handles quick client record lookup from data exports.',
      'Rename and mapping improve consistency for inconsistent legacy form labels.',
    ],
    faqs: [
      {
        question: 'Can DullyPDF automate W-9 and 1099 PDF forms?',
        answer:
          'Yes. Tax document templates can be mapped to client data and filled from structured records.',
      },
      {
        question: 'Does this work for CPA firm engagement letters?',
        answer:
          'Yes. Engagement letter templates can be standardized and reused across clients.',
      },
      {
        question: 'Can accounting teams handle tax season volume with templates?',
        answer:
          'Yes. Saved templates support repeat filling from client data exports for high-volume processing.',
      },
    ],
  },
];

const PAGE_BY_KEY = new Map<IntentPageKey, IntentPage>(INTENT_PAGES.map((page) => [page.key, page]));
const PAGE_BY_PATH = new Map<string, IntentPage>(INTENT_PAGES.map((page) => [page.path, page]));

export const getIntentPages = (): IntentPage[] => INTENT_PAGES;

export const getIntentPage = (key: IntentPageKey): IntentPage => {
  const page = PAGE_BY_KEY.get(key);
  if (!page) throw new Error(`Unknown intent page key: ${key}`);
  return page;
};

export const resolveIntentPath = (pathname: string): IntentPageKey | null => {
  const normalizedPath = pathname.replace(/\/+$/, '') || '/';
  const page = PAGE_BY_PATH.get(normalizedPath);
  return page?.key ?? null;
};
