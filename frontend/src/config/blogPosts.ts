import type { IntentPageKey } from './intentPages';
import type { UsageDocsPageKey } from '../components/pages/usageDocsContent';

export type BlogPostSection = {
  id: string;
  title: string;
  body: string;
};

export type BlogPost = {
  slug: string;
  title: string;
  seoTitle: string;
  seoDescription: string;
  seoKeywords: string[];
  publishedDate: string;
  updatedDate: string;
  author: string;
  summary: string;
  sections: BlogPostSection[];
  relatedIntentPages: IntentPageKey[];
  relatedDocs: UsageDocsPageKey[];
};

const BLOG_POSTS: BlogPost[] = [
  {
    slug: 'how-to-convert-pdf-to-fillable-form',
    title: 'How to Convert a PDF to a Fillable Form Without Adobe Acrobat',
    seoTitle: 'Convert PDF to Fillable Form Without Adobe Acrobat | DullyPDF Blog',
    seoDescription:
      'Learn how to convert any PDF into a fillable form without Acrobat. DullyPDF uses AI field detection to create reusable templates for free.',
    seoKeywords: ['pdf to fillable form without acrobat', 'convert pdf to fillable form free', 'fillable pdf without adobe'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Adobe Acrobat is expensive and overkill for most fillable form needs. This guide shows how to convert any PDF into a fillable template using AI-powered field detection in your browser.',
    sections: [
      {
        id: 'why-skip-acrobat',
        title: 'Why skip Adobe Acrobat?',
        body: 'Adobe Acrobat Pro costs $23/month and requires installation. For teams that just need to convert a PDF into a fillable form and map it to their data, that is overkill. Browser-based tools like DullyPDF detect fields automatically, let you refine them visually, and save reusable templates without any desktop software.',
      },
      {
        id: 'step-by-step',
        title: 'Step-by-step: convert a PDF to fillable form',
        body: 'Upload your PDF to DullyPDF (up to 50MB). The AI detection pipeline analyzes every page and identifies text fields, checkboxes, date fields, and signature areas with confidence scores. Review the detected fields in the visual editor, resize or rename any that need adjustment, then save the template. The entire process takes minutes, not hours.',
      },
      {
        id: 'field-detection',
        title: 'How AI field detection works',
        body: 'DullyPDF uses the CommonForms ML model to scan each page image and identify regions likely to be form inputs. Each detection comes with a confidence score: high (above 80%), medium (65-80%), and low (below 65%). Start by reviewing low-confidence detections first, since those are most likely to need manual correction.',
      },
      {
        id: 'mapping-schema',
        title: 'Map fields to your database schema',
        body: 'Once fields are detected and cleaned up, upload a CSV, Excel, or JSON schema file. DullyPDF can use OpenAI to automatically rename fields and map them to your column headers. This turns your fillable PDF into a database-ready template that can be populated from structured data rows.',
      },
      {
        id: 'reuse-templates',
        title: 'Save and reuse templates',
        body: 'Save your finished template to your DullyPDF profile. Next time you need to fill the same form type, reload the template, connect your data source, and use Search & Fill to populate all mapped fields in seconds. No re-detection or re-mapping required.',
      },
    ],
    relatedIntentPages: ['pdf-to-fillable-form'],
    relatedDocs: ['getting-started'],
  },
  {
    slug: 'auto-fill-pdf-from-spreadsheet',
    title: 'How to Auto-Fill PDF Forms From a Spreadsheet (CSV or Excel)',
    seoTitle: 'Auto-Fill PDF Forms From CSV or Excel Spreadsheet | DullyPDF Blog',
    seoDescription:
      'Fill PDF form fields automatically from CSV or Excel spreadsheet rows. Map columns to PDF fields and populate forms in seconds.',
    seoKeywords: ['fill pdf from spreadsheet', 'auto fill pdf from excel', 'fill pdf from csv', 'pdf form from spreadsheet'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Stop copying and pasting from spreadsheets into PDF forms. This guide shows how to map spreadsheet columns to PDF fields and auto-fill forms from any row in your data.',
    sections: [
      {
        id: 'the-problem',
        title: 'The copy-paste problem',
        body: 'Every day, office teams manually copy data from spreadsheets into PDF forms. Patient records into intake forms, employee data into onboarding packets, policy details into insurance certificates. Each form takes 5-15 minutes of tedious, error-prone data entry. Multiply that by dozens of forms per day and the waste is enormous.',
      },
      {
        id: 'how-it-works',
        title: 'How spreadsheet-to-PDF filling works',
        body: 'DullyPDF connects your spreadsheet columns to PDF form fields through schema mapping. Upload your PDF, detect fields, then upload your CSV or Excel file. The mapping step links column headers like "first_name" to the corresponding PDF field. Once mapped, select any row and DullyPDF fills every mapped field instantly.',
      },
      {
        id: 'search-and-fill',
        title: 'Search & Fill: find the right record fast',
        body: 'The Search & Fill panel lets you search across any column using contains or exact-match mode. Results are capped at 25 rows for controlled review. Click "Fill PDF" on any result row to populate all mapped fields. Clear and refill as many times as needed to verify mapping quality before downloading or saving.',
      },
      {
        id: 'supported-formats',
        title: 'Supported data formats',
        body: 'DullyPDF supports CSV, XLSX (Excel), and JSON for row-based filling. TXT files work for schema-only mapping without row data. CSV and Excel files can contain up to 5,000 rows. Duplicate column headers are automatically renamed to prevent conflicts.',
      },
      {
        id: 'tips',
        title: 'Tips for reliable auto-fill',
        body: 'Run Rename + Map together for the best field alignment. Always test with one record before batch processing. Check that checkbox groups and date fields are mapping correctly. Use the inspector panel to verify individual field values after filling.',
      },
    ],
    relatedIntentPages: ['fill-pdf-from-csv'],
    relatedDocs: ['search-fill'],
  },
  {
    slug: 'acord-25-certificate-fill-faster',
    title: 'ACORD 25 Certificate of Insurance: How to Fill It Faster',
    seoTitle: 'Fill ACORD 25 Certificate of Insurance Faster | DullyPDF Blog',
    seoDescription:
      'Speed up ACORD 25 certificate of insurance processing with mapped templates. Detect fields, map to your data, and fill in seconds.',
    seoKeywords: [
      'acord 25 fillable',
      'fill acord form automatically',
      'acord certificate of insurance automation',
      'acord 25 template',
      'insurance pdf automation',
      'certificate of insurance automation',
    ],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Insurance agencies process hundreds of ACORD 25 certificates monthly. This guide shows how to turn the ACORD 25 into a mapped template that fills from your management system data.',
    sections: [
      {
        id: 'acord-25-overview',
        title: 'What is the ACORD 25?',
        body: 'The ACORD 25 is the standard certificate of liability insurance used across the US insurance industry. It includes fields for named insured, producer, insurers, coverage types, policy numbers, limits, and certificate holder details. Most agencies fill this form dozens of times per week from their agency management system.',
      },
      {
        id: 'manual-pain',
        title: 'Why manual ACORD filling is painful',
        body: 'ACORD forms have dozens of fields across multiple coverage sections. Manually copying policy numbers, effective dates, limits, and named insureds from your AMS into the PDF is slow and error-prone. One transposed digit in a policy number or wrong effective date can cause E&O exposure.',
      },
      {
        id: 'template-workflow',
        title: 'Create a reusable ACORD 25 template',
        body: 'Upload the ACORD 25 PDF to DullyPDF. Run field detection to identify all input regions. Use the editor to verify and clean up field boundaries. Then upload a CSV or Excel export from your agency management system and map the ACORD fields to your column headers. Save the template for repeat use.',
      },
      {
        id: 'fill-from-ams',
        title: 'Fill certificates from your data',
        body: 'Once the ACORD 25 template is mapped, export your policy data as CSV or Excel. Load it into DullyPDF, search for the insured, and fill all mapped fields with one click. Download the completed certificate immediately or save it to your profile for record-keeping.',
      },
    ],
    relatedIntentPages: ['acord-form-automation'],
    relatedDocs: ['getting-started', 'search-fill'],
  },
  {
    slug: 'insurance-pdf-automation-acord-and-coi-workflows',
    title: 'Insurance PDF Automation: ACORD and Certificate Workflows',
    seoTitle: 'Insurance PDF Automation for ACORD and COI Workflows | DullyPDF Blog',
    seoDescription:
      'Learn how insurance teams automate ACORD forms and certificate of insurance PDFs with mapped templates tied to agency data exports.',
    seoKeywords: [
      'insurance pdf automation',
      'insurance form automation',
      'certificate of insurance automation',
      'acord form automation software',
      'auto fill insurance forms',
    ],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'If your team handles recurring ACORD packets and COI requests, this workflow shows how to map once and fill insurance PDFs from AMS exports in seconds.',
    sections: [
      {
        id: 'why-insurance-pdfs-stay-manual',
        title: 'Why insurance PDF workflows stay manual',
        body: 'Insurance operations teams still process many carrier and ACORD forms as PDFs, not APIs. Producers and account managers repeatedly retype the same insured, policy, and coverage values for renewals, certificates, and endorsements. The bottleneck is not data availability. The bottleneck is mapping that data reliably into fixed PDF layouts.',
      },
      {
        id: 'acord-and-carrier-forms',
        title: 'ACORD plus carrier-specific form variants',
        body: 'ACORD 25 is common, but most agencies also touch ACORD 24, 27, 28, 126, and carrier-specific supplements. A practical setup treats each recurring form as a reusable template: detect fields, clean geometry, normalize names, and save. This prevents repeated setup work each time a carrier changes spacing or a field label.',
      },
      {
        id: 'map-from-ams-exports',
        title: 'Map once from AMS or broker exports',
        body: 'Export policy data from your agency management system as CSV or Excel. Map insured name, producer details, policy numbers, limits, effective dates, and holder data once. After mapping, Search & Fill can locate an insured record and populate the entire form in one pass, reducing rekeying mistakes.',
      },
      {
        id: 'coi-turnaround',
        title: 'Speed up certificate of insurance turnaround',
        body: 'Certificate requests often arrive with tight deadlines. With a mapped template, account teams can search a policy record, fill the certificate, validate key fields, and deliver quickly. The workflow is especially useful for high-volume COI operations where consistency and speed matter more than custom one-off editing.',
      },
      {
        id: 'implementation-checklist',
        title: 'Implementation checklist for insurance teams',
        body: 'Start with your highest-volume ACORD or COI form. Build one template, validate with five real records, and lock naming conventions for policy and coverage fields. Then duplicate the pattern across your next forms. This phased rollout builds trust and minimizes disruption to current servicing workflows.',
      },
    ],
    relatedIntentPages: ['insurance-pdf-automation', 'acord-form-automation'],
    relatedDocs: ['getting-started', 'rename-mapping', 'search-fill'],
  },
  {
    slug: 'pdf-form-field-detection-how-ai-finds-fields',
    title: 'PDF Form Field Detection: How AI Finds Fields in Any PDF',
    seoTitle: 'PDF Form Field Detection: How AI Finds Fields | DullyPDF Blog',
    seoDescription:
      'Learn how AI-powered field detection identifies text fields, checkboxes, and signatures in any PDF. Understand confidence scores and optimization tips.',
    seoKeywords: ['pdf form field detection', 'detect fields in pdf', 'ai pdf field detection', 'pdf field recognition'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'How does AI find form fields in a PDF that has no embedded form data? This post explains the detection pipeline, confidence scoring, and how to get the best results.',
    sections: [
      {
        id: 'the-challenge',
        title: 'The field detection challenge',
        body: 'Most PDFs in the wild are not fillable. They are flat documents with lines, boxes, and labels that humans recognize as form fields, but that contain no embedded form metadata. Turning these visual cues into actual fillable fields requires analyzing the page image and understanding document layout.',
      },
      {
        id: 'how-detection-works',
        title: 'How DullyPDF detection works',
        body: 'DullyPDF uses the CommonForms ML model to analyze rendered page images. The model identifies rectangular regions likely to be input areas and classifies them as text, date, checkbox, or signature fields. Each detection includes geometry coordinates (position and size) and a confidence score.',
      },
      {
        id: 'confidence-scores',
        title: 'Understanding confidence scores',
        body: 'Confidence scores tell you how certain the model is about each detection. High confidence (80% and above) means the model is very sure this is a real field. Medium confidence (65-80%) suggests a probable field that may need review. Low confidence (below 65%) flags uncertain detections that should be checked first.',
      },
      {
        id: 'tips-for-better-results',
        title: 'Tips for better detection results',
        body: 'Use clean, high-resolution PDFs when possible. Scanned documents with low quality or skewed pages produce less precise field boundaries. Dense forms with fields very close together may need manual cleanup. Decorative borders or boxes can sometimes be mistaken for input fields and should be deleted in the editor.',
      },
      {
        id: 'after-detection',
        title: 'What to do after detection',
        body: 'Review low-confidence detections first. Use the visual editor to resize, reposition, or delete incorrect fields. Add any fields the model missed. Once the field set is clean, proceed to rename and mapping to prepare the template for data-driven filling.',
      },
    ],
    relatedIntentPages: ['pdf-to-fillable-form'],
    relatedDocs: ['detection'],
  },
  {
    slug: 'map-pdf-fields-to-database-columns',
    title: 'Map PDF Fields to Database Columns: A Step-by-Step Guide',
    seoTitle: 'Map PDF Fields to Database Columns Step-by-Step | DullyPDF Blog',
    seoDescription:
      'Learn how to map PDF form fields to database or spreadsheet columns for automated filling. Step-by-step guide with best practices.',
    seoKeywords: ['pdf to database', 'map pdf fields to database', 'pdf database mapping', 'pdf schema mapping guide'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Mapping PDF fields to database columns is the key step that turns a fillable form into an automated data-entry tool. This guide walks through the complete process.',
    sections: [
      {
        id: 'why-mapping-matters',
        title: 'Why mapping matters',
        body: 'Without mapping, each PDF field is just a named rectangle on a page. Mapping links field names to your data column headers so that when you select a record, every field knows which value to display. This is what transforms a fillable PDF from a digital form into an automated data pipeline.',
      },
      {
        id: 'prepare-your-schema',
        title: 'Prepare your schema file',
        body: 'Export your database table headers as a CSV, Excel, or JSON file. The headers should be clean and consistent: snake_case works best (e.g., first_name, policy_number, effective_date). DullyPDF will normalize headers by converting spaces and hyphens to underscores automatically.',
      },
      {
        id: 'rename-first',
        title: 'Rename fields before mapping',
        body: 'If your PDF field names are inconsistent (like "Field1", "untitled_2", or "Text Box 3"), run OpenAI Rename first. The AI analyzes the PDF page image and nearby labels to suggest meaningful names. This dramatically improves mapping accuracy because the mapping step can then match field names to column headers more reliably.',
      },
      {
        id: 'run-mapping',
        title: 'Run the mapping step',
        body: 'Upload your schema file and run Map (or Rename + Map for a combined workflow). DullyPDF sends the field names and schema headers to OpenAI, which suggests alignments. Review the mapping confidence scores and adjust any misaligned fields in the editor. Pay special attention to checkbox groups, which may need explicit group and option key configuration.',
      },
      {
        id: 'test-and-save',
        title: 'Test and save your mapped template',
        body: 'Load your actual data file and run a test fill with Search & Fill. Check that all fields populate correctly. Pay attention to date formatting, checkbox selections, and composite fields. Once satisfied, save the template to your profile for repeat use across future fill cycles.',
      },
    ],
    relatedIntentPages: ['pdf-to-database-template'],
    relatedDocs: ['rename-mapping'],
  },
  {
    slug: 'automate-medical-intake-forms',
    title: 'Automate Medical Intake Forms: Reduce Front-Desk Data Entry by 80%',
    seoTitle: 'Automate Medical Intake Forms: Cut Data Entry 80% | DullyPDF Blog',
    seoDescription:
      'Reduce front-desk data entry by automating patient intake PDF forms. Map intake fields to your EHR data and fill in seconds.',
    seoKeywords: ['automate patient intake forms', 'healthcare pdf automation', 'medical intake form automation', 'patient registration automation'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Front-desk staff spend hours retyping patient data into intake PDFs. This guide shows how to create mapped templates that fill automatically from your patient records.',
    sections: [
      {
        id: 'intake-form-problem',
        title: 'The intake form data entry problem',
        body: 'Medical offices use stacks of intake PDFs: patient registration, medical history, consent forms, HIPAA releases, and insurance verification. Front-desk staff manually type patient demographics, insurance details, and medical history into each form. With 20-40 patients per day, this consumes hours of staff time and introduces transcription errors.',
      },
      {
        id: 'template-approach',
        title: 'The template-based approach',
        body: 'Instead of filling forms manually, create a mapped template once and reuse it. Upload your intake PDF to DullyPDF, detect all fields, clean up the layout, and map fields to your patient data columns. Save the template. Now for every patient visit, just search their record and fill all forms in seconds.',
      },
      {
        id: 'checkbox-handling',
        title: 'Handling medical checkboxes',
        body: 'Medical intake forms are checkbox-heavy: symptom lists, allergy disclosures, medication history, and yes/no questions. DullyPDF supports four checkbox rule types: yes_no for boolean fields, presence for truthy/falsey values, enum for categorical selections, and list for multi-select groups. Configure checkbox rules during mapping for accurate automated filling.',
      },
      {
        id: 'privacy-note',
        title: 'Privacy considerations',
        body: 'Patient data stays in your browser during Search & Fill operations. CSV and Excel rows are never uploaded to DullyPDF servers. Only PDF page images and field metadata are sent for detection and optional AI operations. Review the privacy policy for complete data handling details.',
      },
      {
        id: 'getting-started',
        title: 'Getting started with healthcare automation',
        body: 'Start with your most frequently used intake form. Upload it, detect fields, run Rename + Map with a patient data export, and test with a few records. Once the template is working well, expand to your full intake packet. Most practices see the biggest time savings within the first week.',
      },
    ],
    relatedIntentPages: ['healthcare-pdf-automation'],
    relatedDocs: ['getting-started', 'search-fill'],
  },
  {
    slug: 'fillable-pdf-field-names-why-they-matter',
    title: 'Fillable PDF Field Names: Why They Matter and How to Fix Them',
    seoTitle: 'PDF Field Names: Why They Matter & How to Fix | DullyPDF Blog',
    seoDescription:
      'Understand why consistent PDF field names are critical for auto-fill and how to standardize them using AI rename.',
    seoKeywords: ['pdf field names', 'rename pdf form fields', 'pdf field naming', 'fix pdf field names'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Bad field names are the number-one cause of mapping failures. This post explains why field naming matters and how AI rename fixes it.',
    sections: [
      {
        id: 'why-names-matter',
        title: 'Why field names matter',
        body: 'When you map PDF fields to database columns, the mapping relies on field names being meaningful and consistent. A field named "first_name" maps easily to a "first_name" column. But a field named "Text1" or "Unnamed_Field_23" gives the mapping algorithm nothing to work with. The result is missed fields, wrong mappings, and hours of manual correction.',
      },
      {
        id: 'common-naming-problems',
        title: 'Common naming problems',
        body: 'Detection outputs often use labels pulled from nearby text, which may be truncated, duplicated, or irrelevant. PDF authoring tools generate names like "topmostSubform[0].Page1[0].TextField1[0]". Scanned forms may have no meaningful labels at all. Multi-page packets may reuse the same field name across pages. All of these problems degrade downstream mapping quality.',
      },
      {
        id: 'ai-rename',
        title: 'How AI rename works',
        body: 'DullyPDF sends the PDF page image and field overlay tags to OpenAI, which analyzes the visual context to suggest meaningful field names. The AI looks at labels, position, field type, and surrounding text to generate names like "patient_first_name", "policy_effective_date", or "signature_insured". Each rename comes with a confidence score for review.',
      },
      {
        id: 'rename-best-practices',
        title: 'Rename best practices',
        body: 'Run rename before mapping for best results. Review low-confidence renames manually. Check that checkbox groups have consistent group keys and distinct option keys. Verify that date fields are named clearly (e.g., "date_of_birth" not "dob_field_2"). Save the renamed template before mapping so you can revert if needed.',
      },
      {
        id: 'combined-workflow',
        title: 'Rename + Map combined workflow',
        body: 'For the fastest setup, use the Rename + Map combined action. This sends both the rename and mapping requests in a single step, consuming 2 credits per 5 pages. The combined workflow typically produces better mappings than map-only because the mapping algorithm works with clean, meaningful field names.',
      },
    ],
    relatedIntentPages: ['fillable-form-field-name'],
    relatedDocs: ['rename-mapping'],
  },
  {
    slug: 'hr-onboarding-stop-retyping-employee-data',
    title: 'HR Onboarding Paperwork: Stop Retyping Employee Data Into PDFs',
    seoTitle: 'Stop Retyping HR Onboarding Data Into PDFs | DullyPDF Blog',
    seoDescription:
      'Automate HR onboarding paperwork by mapping employee data to PDF form templates. Fill W-4s, I-9s, and benefits forms in seconds.',
    seoKeywords: ['hr onboarding form automation', 'automate employee paperwork', 'hr pdf automation', 'onboarding forms automation'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'HR teams retype the same employee data across W-4s, I-9s, benefits enrollments, and policy acknowledgments. This guide shows how to fill all onboarding forms from one data source.',
    sections: [
      {
        id: 'onboarding-pain',
        title: 'The onboarding paperwork problem',
        body: 'Every new hire means a stack of PDF forms: W-4, I-9, state tax withholding, benefits enrollment, direct deposit, handbook acknowledgment, emergency contact, and more. HR staff retype the same employee name, address, SSN, and date of birth into each form. For companies hiring 10+ people per month, this consumes entire workdays.',
      },
      {
        id: 'one-source-many-forms',
        title: 'One data source, many forms',
        body: 'Export your HRIS or onboarding spreadsheet as CSV or Excel. It contains all the employee data you need: name, address, SSN, date of birth, department, start date, benefits selections. Create a mapped template for each form type in your onboarding packet. Now filling the entire packet for a new hire takes minutes instead of an hour.',
      },
      {
        id: 'template-setup',
        title: 'Setting up onboarding templates',
        body: 'Upload each onboarding form PDF to DullyPDF. Run detection, clean up fields, then map to your HRIS export columns. Pay attention to checkbox fields on benefits forms and yes/no questions on policy acknowledgments. Save each template to your profile. The initial setup takes about 30 minutes per form, but saves hours every month after.',
      },
      {
        id: 'batch-workflow',
        title: 'Filling forms for each new hire',
        body: 'When a new hire starts, load your HRIS export, search for the employee, and fill each onboarding template with their data. Download the completed forms or save them to your profile. The Search & Fill workflow ensures every field is populated consistently across all forms in the packet.',
      },
      {
        id: 'tips',
        title: 'Tips for HR teams',
        body: 'Start with the forms you fill most frequently. Test with a few employees before rolling out to the full team. Keep your HRIS export columns consistent so templates work reliably across hire cohorts. Update templates when form versions change, but keep the mapping structure stable.',
      },
    ],
    relatedIntentPages: ['hr-pdf-automation'],
    relatedDocs: ['getting-started', 'search-fill'],
  },
  {
    slug: 'dullypdf-vs-adobe-acrobat-pdf-form-automation',
    title: 'DullyPDF vs Adobe Acrobat for PDF Form Automation',
    seoTitle: 'DullyPDF vs Adobe Acrobat for PDF Form Automation | Comparison',
    seoDescription:
      'Compare DullyPDF and Adobe Acrobat for PDF form automation. See how AI field detection and schema mapping differ from Acrobat\'s manual form tools.',
    seoKeywords: ['dullypdf vs acrobat', 'acrobat fillable form alternative', 'pdf form automation comparison', 'acrobat alternative'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'Adobe Acrobat is the industry standard for PDF editing, but its form automation features are limited. This comparison shows where DullyPDF\'s AI-driven workflow excels for repeat form-filling use cases.',
    sections: [
      {
        id: 'overview',
        title: 'Overview: different tools for different needs',
        body: 'Adobe Acrobat is a comprehensive PDF editor built for general-purpose document work: annotating, signing, converting, and creating fillable forms manually. DullyPDF is purpose-built for one workflow: converting PDFs into database-mapped templates that can be filled automatically from structured data. If you need a general PDF editor, Acrobat is the right choice. If you need to fill the same form type repeatedly from spreadsheet or database records, DullyPDF is built for that.',
      },
      {
        id: 'field-detection',
        title: 'Field detection',
        body: 'Acrobat\'s "Prepare Form" tool detects existing form fields embedded in PDFs. It works well for PDFs that were authored with form fields. DullyPDF uses AI to detect fields even in flat PDFs that have no embedded form data, using the page image and layout analysis. This is a significant advantage for scanned forms, legacy documents, and PDFs from organizations that don\'t create fillable forms.',
      },
      {
        id: 'schema-mapping',
        title: 'Schema mapping and auto-fill',
        body: 'Acrobat does not support mapping form fields to external data schemas. You can fill forms manually or use JavaScript scripting for limited automation. DullyPDF\'s core feature is schema mapping: link PDF fields to CSV/Excel/JSON column headers, then fill any record with one click. This eliminates manual data entry for repeat workflows.',
      },
      {
        id: 'pricing',
        title: 'Pricing comparison',
        body: 'Adobe Acrobat Pro costs $23/month. DullyPDF offers free detection and editing with paid AI features (rename and mapping) starting at low per-use credit costs. For teams that primarily need form-filling automation, DullyPDF can be significantly more cost-effective than an Acrobat subscription.',
      },
      {
        id: 'when-to-choose',
        title: 'When to choose each tool',
        body: 'Choose Acrobat when you need general PDF editing, document signing, PDF conversion, or annotation. Choose DullyPDF when you need to convert PDFs into mapped templates for repeat data-entry workflows from CSV, Excel, or JSON sources. Many teams use both: Acrobat for one-off PDF work and DullyPDF for automated form filling.',
      },
    ],
    relatedIntentPages: ['pdf-to-fillable-form', 'pdf-field-detection-tool'],
    relatedDocs: ['getting-started', 'detection'],
  },
  {
    slug: 'dullypdf-vs-jotform-pdf-data-collection',
    title: 'DullyPDF vs JotForm for PDF Data Collection',
    seoTitle: 'DullyPDF vs JotForm for PDF Data Collection | Comparison',
    seoDescription:
      'Compare DullyPDF and JotForm for PDF-based data collection. Understand the differences between form-builder and template-mapping approaches.',
    seoKeywords: ['dullypdf vs jotform', 'jotform alternative for pdf', 'pdf data collection comparison', 'pdf form builder alternative'],
    publishedDate: '2026-03-04',
    updatedDate: '2026-03-24',
    author: 'DullyPDF Team',
    summary:
      'JotForm builds online forms from scratch. DullyPDF works with existing PDF forms. This comparison helps you choose the right approach for your data collection workflow.',
    sections: [
      {
        id: 'different-approaches',
        title: 'Two different approaches to forms',
        body: 'JotForm is an online form builder: you create new web-based forms from scratch, collect submissions, and export data. DullyPDF works with existing PDF documents: you upload a PDF that already exists, detect its fields, map them to your data, and fill them from records. The choice depends on whether you need to create new forms or automate existing ones.',
      },
      {
        id: 'existing-pdf-workflows',
        title: 'When you must use existing PDFs',
        body: 'Many industries require specific PDF forms: ACORD certificates in insurance, government permit applications, medical intake packets, legal court filings. These forms can\'t be replaced with online form builders because they have regulatory or industry-mandated formats. DullyPDF automates filling these existing PDF documents. JotForm can\'t help here because the form format is fixed.',
      },
      {
        id: 'data-privacy',
        title: 'Data privacy differences',
        body: 'JotForm submissions are stored on JotForm\'s servers. With DullyPDF, your CSV/Excel/JSON data rows stay in your browser during Search & Fill. Only PDF page images and field metadata are sent for detection and optional AI features. For organizations with strict data handling requirements, DullyPDF\'s browser-local approach can be an advantage.',
      },
      {
        id: 'when-to-choose',
        title: 'When to choose each tool',
        body: 'Choose JotForm when you want to create new online forms, collect submissions from external respondents, and build form workflows from scratch. Choose DullyPDF when you have existing PDF forms that need to be filled from your internal data repeatedly. Some organizations use both: JotForm for external data collection and DullyPDF for internal PDF form automation.',
      },
    ],
    relatedIntentPages: ['fill-pdf-from-csv', 'fill-information-in-pdf'],
    relatedDocs: ['search-fill'],
  },
];

const POST_BY_SLUG = new Map<string, BlogPost>(BLOG_POSTS.map((p) => [p.slug, p]));

export const getBlogPosts = (): BlogPost[] => BLOG_POSTS;

export const getBlogPost = (slug: string): BlogPost | undefined => POST_BY_SLUG.get(slug);

export const getBlogSlugs = (): string[] => BLOG_POSTS.map((p) => p.slug);
