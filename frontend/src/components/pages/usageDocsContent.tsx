import type { ReactNode } from 'react';

export type UsageDocsPageKey =
  | 'index'
  | 'getting-started'
  | 'detection'
  | 'rename-mapping'
  | 'editor-workflow'
  | 'search-fill'
  | 'save-download-profile'
  | 'troubleshooting';

export type UsageDocsSection = {
  id: string;
  title: string;
  body: ReactNode;
};

export type UsageDocsPage = {
  key: UsageDocsPageKey;
  slug: string;
  navLabel: string;
  title: string;
  summary: string;
  sections: UsageDocsSection[];
};

export type ResolvedUsageDocsPath =
  | { kind: 'canonical'; pageKey: UsageDocsPageKey }
  | { kind: 'redirect'; targetPath: string }
  | { kind: 'not-found'; requestedPath: string };

const USAGE_DOCS_PAGES: UsageDocsPage[] = [
  {
    key: 'index',
    slug: '',
    navLabel: 'Overview',
    title: 'DullyPDF Usage Docs',
    summary:
      'Implementation-level guide for the full DullyPDF workflow, including concrete limits, matching rules, and checkbox behavior.',
    sections: [
      {
        id: 'pipeline-overview',
        title: 'Pipeline overview',
        body: (
          <>
            <p>
              DullyPDF runs a fixed sequence: PDF upload -&gt; CommonForms detection -&gt; optional OpenAI Rename
              and/or Map -&gt; editor cleanup -&gt; Search &amp; Fill -&gt; download/save.
            </p>
            <p>
              Route-level behavior: `/detect-fields` creates the detection session, `/api/renames/ai` performs rename,
              `/api/schema-mappings/ai` performs mapping, and Search &amp; Fill runs client-side over your local rows.
            </p>
          </>
        ),
      },
      {
        id: 'before-you-start',
        title: 'Before you start',
        body: (
          <ul>
            <li>PDF upload limit is 50MB (`UploadComponent` validation).</li>
            <li>Desktop is required for full editor usage. Mobile is walkthrough-only.</li>
            <li>Search &amp; Fill record rows require CSV, XLSX, or JSON. TXT is schema-only.</li>
            <li>OpenAI actions require sign-in and credits. Pricing is bucketed by page count (default 5 pages per bucket).</li>
            <li>Credits formula: total = baseCost x ceil(pageCount / bucketSize). Base costs: Rename=1, Remap=1, Rename+Map=2.</li>
            <li>Billing runs through Stripe from Profile: Pro Monthly, Pro Yearly, and a Pro-only 500-credit refill pack.</li>
          </ul>
        ),
      },
      {
        id: 'choose-the-right-page',
        title: 'Choose the right docs page',
        body: (
          <ul>
            <li>
              Use <a href="/usage-docs/detection">Detection</a> for confidence tiers, geometry shape, and coordinate behavior.
            </li>
            <li>
              Use <a href="/usage-docs/rename-mapping">Rename + Mapping</a> for OpenAI payload boundaries and checkbox rule precedence.
            </li>
            <li>
              Use <a href="/usage-docs/editor-workflow">Editor Workflow</a> for drag/resize constraints and edit-history behavior.
            </li>
            <li>
              Use <a href="/usage-docs/search-fill">Search &amp; Fill</a> for row caps, query modes, and field resolution heuristics.
            </li>
            <li>
              Use <a href="/usage-docs/troubleshooting">Troubleshooting</a> for exact validation/error messages and fast diagnosis steps.
            </li>
          </ul>
        ),
      },
      {
        id: 'hard-numbers',
        title: 'Hard numbers used by the app',
        body: (
          <ul>
            <li>Confidence tiers: high &gt;= 0.80, medium &gt;= 0.65, low &lt; 0.65.</li>
            <li>Search results are capped at 25 rows per query.</li>
            <li>CSV/XLSX/JSON parsing caps rows at 5000 records per import.</li>
            <li>Schema inference samples up to 200 rows when inferring field types.</li>
            <li>Field edit history depth is 10 snapshots (undo/redo).</li>
            <li>Minimum overlay field geometry is 6 PDF points for width/height.</li>
          </ul>
        ),
      },
    ],
  },
  {
    key: 'getting-started',
    slug: 'getting-started',
    navLabel: 'Getting Started',
    title: 'Getting Started',
    summary:
      'A practical quick-start from upload to filled output, including when to pause and review results.',
    sections: [
      {
        id: 'quick-start-path',
        title: 'Quick-start path',
        body: (
          <ol>
            <li>Upload a PDF (50MB max). Non-PDF or larger files are blocked before upload.</li>
            <li>Wait for detection results, then check low-confidence items first.</li>
            <li>If naming is inconsistent, run Rename or Rename + Map (with schema ready).</li>
            <li>Clean geometry in the editor, then verify field types.</li>
            <li>Load CSV/XLSX/JSON rows and run one controlled Search &amp; Fill test.</li>
          </ol>
        ),
      },
      {
        id: 'best-practice-order',
        title: 'Best-practice order',
        body: (
          <>
            <p>For consistent results, keep this order:</p>
            <ul>
              <li>Detect first.</li>
              <li>Rename before mapping if labels are inconsistent.</li>
              <li>Map after schema upload so field names align to column headers.</li>
              <li>Finalize geometry and field types before large batch filling/exporting.</li>
            </ul>
            <p>
              Practical credit plan: when you need both operations, use Rename + Map to reduce round trips.
              Credit cost remains bucketed by page count either way.
            </p>
          </>
        ),
      },
      {
        id: 'first-run-checklist',
        title: 'First-run checklist',
        body: (
          <ul>
            <li>Confirm each required form area has a field candidate.</li>
            <li>Verify page assignment for fields spanning multiple pages.</li>
            <li>Check checkbox groups/options (`groupKey`, `optionKey`) before filling.</li>
            <li>Run one test record through Search &amp; Fill before saving templates.</li>
            <li>Validate one date field and one checkbox group in the final output PDF.</li>
          </ul>
        ),
      },
      {
        id: 'what-good-looks-like',
        title: 'What good output looks like',
        body: (
          <ul>
            <li>High-confidence fields require little or no geometry correction.</li>
            <li>Mapped field names resemble your schema headers (snake_case style in most cases).</li>
            <li>Yes/no checkbox pairs always end with exactly one selected option after fill.</li>
            <li>
              Search returns expected records quickly with either <code>contains</code> or <code>equals</code> mode.
            </li>
          </ul>
        ),
      },
    ],
  },
  {
    key: 'detection',
    slug: 'detection',
    navLabel: 'Detection',
    title: 'Detection',
    summary:
      'How CommonForms detection works, how confidence levels are used, and what to adjust when candidates look wrong.',
    sections: [
      {
        id: 'what-detection-returns',
        title: 'What detection returns',
        body: (
          <>
            <p>
              Detection returns a field list with key values: <code>name</code>, <code>type</code>, <code>page</code>,
              geometry (<code>rect</code>), and confidence metadata.
            </p>
            <p>
              Geometry is normalized to top-left origin coordinates and rendered as <code>{`{x, y, width, height}`}</code>
              in the editor.
            </p>
            <p>
              Field types supported in the UI are <code>text</code>, <code>date</code>, <code>signature</code>, and <code>checkbox</code>.
            </p>
          </>
        ),
      },
      {
        id: 'confidence-review',
        title: 'Confidence review',
        body: (
          <ul>
            <li>High: confidence &gt;= 0.80</li>
            <li>Medium: confidence &gt;= 0.65 and &lt; 0.80</li>
            <li>Low: confidence &lt; 0.65</li>
            <li>
              Numeric confidence parser accepts either 0..1 values or 0..100 percentages (for example <code>82</code>
              becomes <code>0.82</code>).
            </li>
            <li>Start review from low-confidence candidates because they drive most downstream errors.</li>
          </ul>
        ),
      },
      {
        id: 'common-limitations',
        title: 'Common limitations and fixes',
        body: (
          <ul>
            <li>Low-quality scans can reduce field boundary precision.</li>
            <li>Dense pages may produce close candidates that need manual cleanup.</li>
            <li>Decorative boxes can be mistaken for fields; remove or repurpose them in inspector.</li>
            <li>Encrypted PDFs are rejected and must be unlocked before detection.</li>
          </ul>
        ),
      },
      {
        id: 'geometry-values',
        title: 'Geometry values and editor constraints',
        body: (
          <ul>
            <li>Rectangles are clamped to page bounds during drag/resize.</li>
            <li>Minimum field width/height is 6 points.</li>
            <li>All geometry edits in inspector and overlay are applied in the same coordinate system.</li>
          </ul>
        ),
      },
    ],
  },
  {
    key: 'rename-mapping',
    slug: 'rename-mapping',
    navLabel: 'Rename + Mapping',
    title: 'Rename + Mapping',
    summary:
      'How to choose Rename, Map, or Rename + Map and how OpenAI outputs appear in the editor.',
    sections: [
      {
        id: 'when-to-run-each',
        title: 'When to run each action',
        body: (
          <ul>
            <li>Rename: use when geometry is acceptable but field names are inconsistent.</li>
            <li>Map: use when names are already acceptable and you only need schema alignment.</li>
            <li>Rename + Map: use when you need both in a single flow.</li>
            <li>Base costs per bucket: Rename=1, Remap=1, Rename+Map=2.</li>
            <li>Server pricing formula: total credits = baseCost x ceil(pageCount / bucketSize).</li>
            <li>Current bucket size default is 5 pages, and server page count is used for final billing.</li>
          </ul>
        ),
      },
      {
        id: 'openai-data-boundaries',
        title: 'OpenAI data boundaries',
        body: (
          <>
            <p>
              Rename and mapping can send PDF page imagery, field overlay tags, and schema headers.
              CSV/Excel/JSON row values and in-editor field input values are not sent.
            </p>
            <p>
              The product asks for explicit confirmation before these requests run. Mapping-only requests send
              database headers + PDF field tags. Combined Rename + Map sends PDF + headers + tags.
            </p>
          </>
        ),
      },
      {
        id: 'interpreting-results',
        title: 'Interpreting results',
        body: (
          <ul>
            <li>
              <code>renameConfidence</code> measures name quality; <code>fieldConfidence</code> measures whether it is
              likely a true field; <code>mappingConfidence</code> measures schema alignment confidence.
            </li>
            <li>Review checkbox metadata (`groupKey`, `optionKey`, `optionLabel`) after rename/map runs.</li>
            <li>Treat AI output as recommendations and validate before production usage.</li>
          </ul>
        ),
      },
      {
        id: 'checkbox-rules-and-precedence',
        title: 'Checkbox rules and precedence',
        body: (
          <>
            <p>
              Checkbox rules support four operations: <code>yes_no</code>, <code>presence</code>, <code>enum</code>,
              and <code>list</code>.
            </p>
            <ul>
              <li><code>yes_no</code>: boolean semantics with optional true/false option mapping.</li>
              <li><code>presence</code>: truthy means select positive option; falsey usually leaves group unset unless mapped.</li>
              <li><code>enum</code>: select the first valid option from a categorical value.</li>
              <li><code>list</code>: split multi-value strings on <code>, ; | /</code> for multi-select groups.</li>
            </ul>
            <p>Search &amp; Fill applies checkbox logic in this order:</p>
            <ol>
              <li>Direct field-name boolean match.</li>
              <li>Direct option-key match.</li>
              <li>Direct group-value match (`i_...`, `checkbox_...`, or raw group key).</li>
              <li><code>checkboxRules</code>.</li>
              <li><code>checkboxHints</code> (`directBooleanPossible=true`).</li>
              <li>Built-in alias fallback groups.</li>
            </ol>
          </>
        ),
      },
      {
        id: 'boolean-token-values',
        title: 'Boolean token values used by Search & Fill',
        body: (
          <>
            <p>Truthy tokens include: <code>true</code>, <code>1</code>, <code>yes</code>, <code>y</code>, <code>on</code>, <code>checked</code>, <code>t</code>, <code>x</code>, <code>selected</code>.</p>
            <p>False tokens include: <code>false</code>, <code>0</code>, <code>no</code>, <code>n</code>, <code>off</code>, <code>unchecked</code>, <code>f</code>, <code>unselected</code>.</p>
            <p>Ambiguous tokens return null and do not coerce booleans: <code>y/n</code>, <code>yes/no</code>, <code>true/false</code>, <code>t/f</code>, <code>0/1</code>, <code>1/0</code>.</p>
            <p>
              Presence-false tokens include: <code>n/a</code>, <code>none</code>, <code>unknown</code>, <code>not available</code>,
              <code>null</code>, <code>blank</code>, and related variants.
            </p>
          </>
        ),
      },
      {
        id: 'rename-only-warning',
        title: 'Rename-only warning',
        body: (
          <p>
            Rename without map can standardize names, but complex checkbox groups and non-matching checkbox columns may
            still fail to fill correctly until schema mapping is also applied.
          </p>
        ),
      },
    ],
  },
  {
    key: 'editor-workflow',
    slug: 'editor-workflow',
    navLabel: 'Editor Workflow',
    title: 'Editor Workflow',
    summary:
      'How to use overlay, field list, and inspector together for fast, high-confidence template cleanup.',
    sections: [
      {
        id: 'three-panel-model',
        title: 'Three-panel model',
        body: (
          <ul>
            <li>Overlay is best for spatial review and direct manipulation.</li>
            <li>Field list is best for scanning, filtering, and page jumping.</li>
            <li>Inspector is best for precise metadata and geometry edits.</li>
            <li>
              Display presets are <code>Review</code>, <code>Edit</code>, and <code>Fill</code>, with manual toggles for
              <code>Fields</code>, <code>Names</code>, <code>Info</code>, <code>All</code>, and <code>Clear</code>.
            </li>
            <li>The field list header shows <code>visible / in-scope</code> counts and overall total for state clarity.</li>
          </ul>
        ),
      },
      {
        id: 'editing-actions',
        title: 'Editing actions',
        body: (
          <ul>
            <li>Drag fields to move and use handles to resize.</li>
            <li>Corner handles follow standard freeform resize behavior by default (independent width/height).</li>
            <li>Hold <code>Shift</code> while dragging a corner to preserve aspect ratio for that drag.</li>
            <li>All four corners and all four edges provide resize handles for direct geometry control.</li>
            <li>Use inspector inputs for exact x/y/width/height updates.</li>
            <li>Add text, date, signature, and checkbox fields for missing regions.</li>
            <li>Delete invalid candidates to keep templates clean.</li>
            <li>Geometry is clamped to page bounds and minimum 6-point width/height.</li>
            <li>If a selected field is hidden by active filters, use <code>Reveal selected</code> in the list panel.</li>
          </ul>
        ),
      },
      {
        id: 'quality-loop',
        title: 'Recommended quality loop',
        body: (
          <ol>
            <li>Filter low confidence items first.</li>
            <li>Normalize field naming patterns.</li>
            <li>Validate page assignments and dimensions.</li>
            <li>Run a Search &amp; Fill trial row and inspect final output.</li>
          </ol>
        ),
      },
      {
        id: 'history-and-clear',
        title: 'History and clear behavior',
        body: (
          <ul>
            <li>Undo/redo depth is 10 edits.</li>
            <li><code>Clear</code> removes meaningful field values and resets them to null.</li>
            <li>For booleans, only true values are considered filled for clear-state checks.</li>
            <li>Header OpenAI actions surface prerequisite hints when disabled to reduce trial-and-error clicks.</li>
          </ul>
        ),
      },
      {
        id: 'keyboard-shortcuts',
        title: 'Keyboard shortcuts',
        body: (
          <ul>
            <li><code>Ctrl/Cmd+Z</code>: undo</li>
            <li><code>Ctrl/Cmd+Shift+Z</code> or <code>Ctrl/Cmd+Y</code>: redo</li>
            <li><code>Delete</code>, <code>Backspace</code>, or <code>Ctrl/Cmd+X</code>: delete selected field</li>
            <li><code>Ctrl/Cmd+F</code> or <code>/</code>: focus field search</li>
            <li><code>[</code> and <code>]</code>: previous/next page</li>
            <li><code>Alt+Arrow</code>: nudge selected field by 1 point</li>
            <li><code>Shift+Alt+Arrow</code>: nudge selected field by 10 points</li>
            <li><code>Ctrl/Cmd+0</code>: reset zoom to 100%</li>
            <li><code>Shift</code> (during corner drag): temporary aspect-ratio lock</li>
          </ul>
        ),
      },
    ],
  },
  {
    key: 'search-fill',
    slug: 'search-fill',
    navLabel: 'Search & Fill',
    title: 'Search & Fill',
    summary:
      'Connect local data sources, search a record, and populate mapped fields with predictable behavior.',
    sections: [
      {
        id: 'data-source-support',
        title: 'Data source support',
        body: (
          <ul>
            <li>CSV, XLS, and JSON include headers and rows for record-based filling.</li>
            <li>TXT is schema-only and supports mapping but not row-based fill.</li>
            <li>CSV/XLSX/JSON parsers cap records at 5000 rows per import.</li>
            <li>Duplicate headers are auto-renamed (`name`, `name_2`, `name_3`, ...).</li>
            <li>Header normalization converts spaces/hyphens to underscores and removes punctuation.</li>
            <li>TXT schema format is one field per line: <code>field_name[:type]</code> with types `string|int|date|bool`.</li>
          </ul>
        ),
      },
      {
        id: 'fill-flow',
        title: 'Fill flow',
        body: (
          <ol>
            <li>Choose a column (`Any column` is available) and match mode (`contains` or `equals`).</li>
            <li>Search is case-insensitive and returns at most 25 results per query.</li>
            <li>Click `Fill PDF` on a result row to write values to current fields.</li>
            <li>Date fields normalize accepted values like `YYYY-MM-DD` and `YYYY/MM/DD` to `YYYY-MM-DD`.</li>
          </ol>
        ),
      },
      {
        id: 'search-fill-guardrails',
        title: 'Guardrails',
        body: (
          <ul>
            <li>If mapping is incomplete, fill coverage will be partial.</li>
            <li>Clear and refill when testing mapping revisions.</li>
            <li>Validate at least one full record before saving templates for teams.</li>
            <li>Search &amp; Fill is enabled only for CSV/XLSX/JSON with at least one row and a loaded document.</li>
          </ul>
        ),
      },
      {
        id: 'field-resolution-heuristics',
        title: 'Field resolution heuristics (non-checkbox)',
        body: (
          <ul>
            <li>Exact normalized name match is attempted first.</li>
            <li>Fallback prefixes: `patient_` and `responsible_party_` are checked automatically.</li>
            <li><code>name</code> falls back to `full_name`, or `first_name + last_name`.</li>
            <li><code>age</code> is derived from `dob`/`date_of_birth` and reference `date`/`visit_date` (or current date).</li>
            <li><code>city_state_zip</code> is composed from `city`, `state`, and `zip` when available.</li>
            <li>Numeric suffix fields like `phone_1` fall back to base key `phone`.</li>
            <li>List fields (`allergy_1`, `medication_1`, `diagnosis_1`) can be sourced from comma/pipe/etc. lists.</li>
          </ul>
        ),
      },
      {
        id: 'checkbox-groups-and-aliases',
        title: 'Checkbox groups and aliases',
        body: (
          <>
            <p>Built-in alias fallbacks include groups like:</p>
            <ul>
              <li><code>allergies</code> - aliases `allergy`, `has_allergies`</li>
              <li><code>pregnant</code> - aliases `pregnancy`, `pregnancy_status`, `is_pregnant`</li>
              <li><code>drug_use</code> - aliases `substance_use`, `illicit_drug_use`, `has_drug_use`</li>
              <li><code>alcohol_use</code> - aliases `drinks_alcohol`, `etoh_use`, `has_alcohol_use`</li>
              <li><code>tobacco_use</code> - aliases `smoking`, `smoker`, `smoking_status`, `has_tobacco_use`</li>
            </ul>
          </>
        ),
      },
    ],
  },
  {
    key: 'save-download-profile',
    slug: 'save-download-profile',
    navLabel: 'Save / Download',
    title: 'Save, Download, and Profile',
    summary:
      'Understand when to download immediately versus saving templates to your profile for reuse.',
    sections: [
      {
        id: 'download-vs-save',
        title: 'Download vs save',
        body: (
          <ul>
            <li>Download when you need a one-off generated output immediately.</li>
            <li>Save to profile when the template will be reused or shared within your account context.</li>
            <li>Saved forms persist template metadata including checkbox rules and hints.</li>
          </ul>
        ),
      },
      {
        id: 'saved-form-workflow',
        title: 'Saved form workflow',
        body: (
          <>
            <p>
              Saved forms preserve PDF bytes and field metadata so you can re-open, re-map, and refill
              without re-detecting from scratch.
            </p>
            <p>
              Use overwrite intentionally when replacing an existing template baseline.
            </p>
          </>
        ),
      },
      {
        id: 'limits-and-credits',
        title: 'Limits and credits',
        body: (
          <>
            <p>OpenAI credit usage is page-bucketed:</p>
            <ul>
              <li>Formula: total credits = baseCost x ceil(pageCount / bucketSize).</li>
              <li>Current default bucket size is 5 pages.</li>
              <li>Base costs: Rename=1, Remap=1, Rename+Map=2.</li>
              <li>Base users start with 10 credits. Pro users get a 500 monthly pool plus refill credits.</li>
              <li>Refill credits do not expire and are consumed after monthly credits.</li>
            </ul>
            <p>
              Base profile fallback limits used by the frontend are detect pages=5, fillable pages=50, and saved forms=3.
              Effective limits may differ by server role/config.
            </p>
          </>
        ),
      },
      {
        id: 'stripe-billing-plans',
        title: 'Stripe billing plans',
        body: (
          <>
            <p>Profile billing actions are backed by Stripe Checkout:</p>
            <ul>
              <li>Pro Monthly (`pro_monthly`) and Pro Yearly (`pro_yearly`) are recurring Stripe subscriptions.</li>
              <li>Refill 500 (`refill_500`) is a Pro-only one-time credit pack and uses backend-provided Stripe plan metadata.</li>
              <li>Payments are handled through Stripe Checkout for secure transaction processing.</li>
              <li>Canceling Pro schedules cancellation at period end; Pro access remains active until that date.</li>
            </ul>
            <p>
              If a user downgrades, stored refill credits stay on the account and become usable again after re-upgrading to Pro.
            </p>
          </>
        ),
      },
      {
        id: 'replace-vs-new-save',
        title: 'Replace vs new save',
        body: (
          <ul>
            <li>Use overwrite when you intentionally replace an existing template baseline.</li>
            <li>Create a new saved form when testing alternate mappings or field sets.</li>
            <li>Run one Search &amp; Fill verification before overwriting production templates.</li>
          </ul>
        ),
      },
    ],
  },
  {
    key: 'troubleshooting',
    slug: 'troubleshooting',
    navLabel: 'Troubleshooting',
    title: 'Troubleshooting',
    summary:
      'Systematic checks for detection quality, OpenAI steps, mapping mismatches, and fill output issues.',
    sections: [
      {
        id: 'detection-issues',
        title: 'Detection issues',
        body: (
          <ul>
            <li>Re-upload cleaner PDFs when labels are faint or skewed.</li>
            <li>Use inspector tools to correct false positives and missed areas.</li>
            <li>Confirm document is not password protected.</li>
            <li>If upload fails immediately, confirm file type is PDF and size is under 50MB.</li>
          </ul>
        ),
      },
      {
        id: 'rename-map-issues',
        title: 'Rename and mapping issues',
        body: (
          <ul>
            <li>Check that schema headers are loaded before mapping.</li>
            <li>Retry with Rename + Map when direct mapping misses ambiguous names.</li>
            <li>Review low-confidence rename outputs before filling.</li>
            <li>If blocked, confirm credits and role on Profile. The server enforces bucketed pricing and returns remaining/required credits in errors.</li>
          </ul>
        ),
      },
      {
        id: 'fill-output-issues',
        title: 'Fill output issues',
        body: (
          <ul>
            <li>Ensure identifier key matches the data source column you are searching.</li>
            <li>Confirm checkbox options align with mapping/group metadata.</li>
            <li>If values look stale, clear values and refill after mapping edits.</li>
            <li>For missing checkbox fills, inspect rule operation (`yes_no|presence|enum|list`) and valueMap normalization.</li>
          </ul>
        ),
      },
      {
        id: 'common-validation-errors',
        title: 'Common validation and runtime messages',
        body: (
          <ul>
            <li>`Choose a CSV, Excel, or JSON source first.`</li>
            <li>`No record rows are available to search.`</li>
            <li>`Enter a search value.`</li>
            <li>`Choose a column to search.`</li>
            <li>`OpenAI credits exhausted (remaining=X, required=Y)`</li>
            <li>`Upload a schema file before running mapping.`</li>
            <li>`Template session is not ready yet. Try again in a moment.`</li>
          </ul>
        ),
      },
      {
        id: 'support',
        title: 'Support',
        body: (
          <p>
            For persistent issues, include your route, action sequence, and screenshot evidence when
            contacting support at <a href="mailto:justin@ttcommercial.com">justin@ttcommercial.com</a>.
          </p>
        ),
      },
    ],
  },
];

const PAGE_BY_KEY = new Map<UsageDocsPageKey, UsageDocsPage>(
  USAGE_DOCS_PAGES.map((page) => [page.key, page]),
);
const PAGE_BY_SLUG = new Map<string, UsageDocsPage>(
  USAGE_DOCS_PAGES.filter((page) => page.slug).map((page) => [page.slug, page]),
);

export const USAGE_DOCS_DEFAULT_PAGE_KEY: UsageDocsPageKey = 'index';

export const getUsageDocsPage = (pageKey: UsageDocsPageKey): UsageDocsPage =>
  PAGE_BY_KEY.get(pageKey) ?? PAGE_BY_KEY.get(USAGE_DOCS_DEFAULT_PAGE_KEY)!;

export const getUsageDocsPages = (): UsageDocsPage[] => USAGE_DOCS_PAGES;

export const usageDocsHref = (pageKey: UsageDocsPageKey): string => {
  const page = getUsageDocsPage(pageKey);
  return page.slug ? `/usage-docs/${page.slug}` : '/usage-docs';
};

export const resolveUsageDocsPath = (pathname: string): ResolvedUsageDocsPath | null => {
  const normalizedPath = pathname.replace(/\/+$/, '') || '/';

  if (normalizedPath === '/usage-docs') {
    return { kind: 'canonical', pageKey: USAGE_DOCS_DEFAULT_PAGE_KEY };
  }

  if (normalizedPath.startsWith('/usage-docs/')) {
    const slugParts = normalizedPath.slice('/usage-docs/'.length).split('/').filter(Boolean);
    if (slugParts.length !== 1) {
      return { kind: 'not-found', requestedPath: normalizedPath };
    }
    const slug = slugParts[0];
    const page = PAGE_BY_SLUG.get(slug);
    if (page) {
      return { kind: 'canonical', pageKey: page.key };
    }
    return { kind: 'not-found', requestedPath: normalizedPath };
  }

  if (normalizedPath === '/docs') {
    return { kind: 'redirect', targetPath: '/usage-docs' };
  }

  if (normalizedPath.startsWith('/docs/')) {
    const suffix = normalizedPath.slice('/docs'.length);
    return { kind: 'redirect', targetPath: `/usage-docs${suffix}` };
  }

  return null;
};
