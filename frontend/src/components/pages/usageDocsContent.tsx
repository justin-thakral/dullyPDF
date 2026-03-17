import type { ReactNode } from 'react';

export type UsageDocsPageKey =
  | 'index'
  | 'getting-started'
  | 'detection'
  | 'rename-mapping'
  | 'editor-workflow'
  | 'search-fill'
  | 'fill-by-link'
  | 'create-group'
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
              and/or Map -&gt; editor cleanup -&gt; saved template -&gt; Search &amp; Fill or Fill By Link respondent
              selection -&gt; download/save.
            </p>
            <p>
              Route-level behavior: `/detect-fields` creates the detection session, `/api/renames/ai` performs rename,
              `/api/schema-mappings/ai` performs mapping, and Search &amp; Fill runs over your local rows or stored
              Fill By Link respondent records.
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
            <li>Search &amp; Fill record rows can come from CSV, XLSX, JSON, or stored Fill By Link respondents. TXT is schema-only.</li>
            <li>Fill By Link can be published from the active saved form or from an open group. Owners now use a larger builder dialog with global settings, searchable questions, and live preview before publishing.</li>
            <li>OpenAI actions require sign-in and credits. Pricing is bucketed by page count (default 5 pages per bucket).</li>
            <li>Credits formula: total = baseCost x ceil(pageCount / bucketSize). Base costs: Rename=1, Remap=1, Rename+Map=2.</li>
            <li>Billing runs through Stripe from Profile: Pro Monthly, Pro Yearly, and a Pro-only 500-credit refill pack.</li>
            <li>Public plan explainers live at <a href="/free-features">/free-features</a> and <a href="/premium-features">/premium-features</a>.</li>
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
              Use <a href="/usage-docs/search-fill">Search &amp; Fill</a> for row caps, query modes, Fill By Link respondent use, and field resolution heuristics.
            </li>
            <li>
              Use <a href="/usage-docs/fill-by-link">Fill By Link</a> for published link creation, respondent expectations, and response review.
            </li>
            <li>
              Use <a href="/usage-docs/create-group">Create Group</a> for packet workflows, group Search &amp; Fill, and batch Rename + Map behavior.
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
            <li>Confidence tiers: high &gt;= 0.60, medium &gt;= 0.30, low &lt; 0.30.</li>
            <li>Search results are capped at 25 rows per query.</li>
            <li>CSV/XLSX/JSON parsing caps rows at 5000 records per import.</li>
            <li>Schema inference samples up to 200 rows when inferring field types.</li>
            <li>Field edit history depth is 10 snapshots (undo/redo).</li>
            <li>Minimum overlay geometry is type-based: text/date/checkbox = 12 points, signature = 16 points.</li>
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
      'A practical quick-start from upload to filled output, including when to pause, publish a Fill By Link, and review results.',
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
            <li>Save the template, then either publish Fill By Link or load CSV/XLSX/JSON rows for Search &amp; Fill.</li>
            <li>Run one controlled Search &amp; Fill or respondent-selection test before production use.</li>
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
            <li>If using Fill By Link, verify the public form questions read clearly on a phone before sharing.</li>
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
            <li>High: confidence &gt;= 0.60</li>
            <li>Medium: confidence &gt;= 0.30 and &lt; 0.60</li>
            <li>Low: confidence &lt; 0.30</li>
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
            <li>Minimum field geometry is type-based: text/date/checkbox = 12 points, signature = 16 points.</li>
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
            <li>Enable <code>Transform</code> mode to show resize handles while editing fields on the PDF.</li>
            <li><code>Transform</code> and <code>Info</code> are mutually exclusive to prevent drag/input conflicts.</li>
            <li><code>Edit</code> preset is the default when a form opens.</li>
            <li>Moving and resizing are only available while <code>Transform</code> is on.</li>
            <li>Drag fields to move and use handles to resize while <code>Transform</code> is enabled.</li>
            <li>Corner handles follow standard freeform resize behavior by default (independent width/height).</li>
            <li>Hold <code>Shift</code> while dragging a corner to preserve aspect ratio for that drag.</li>
            <li>Standard fields expose four corners plus middle edge handles; small fields (for example tiny checkboxes) use a single bottom-right handle.</li>
            <li>Small fields also include a larger move hit area to reduce missed drag attempts.</li>
            <li>Use inspector create tools to draw text, date, signature, and checkbox fields directly on-canvas.</li>
            <li>Use inspector inputs for exact x/y/width/height updates.</li>
            <li>Delete invalid candidates to keep templates clean.</li>
            <li>Geometry is clamped to page bounds and type-based minimum sizes.</li>
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
            <li><code>T</code> / <code>D</code> / <code>S</code> / <code>C</code>: activate Text/Date/Signature/Checkbox create tools</li>
            <li><code>Esc</code>: clear active create tool</li>
            <li><code>Ctrl/Cmd+F</code> or <code>/</code>: focus field search</li>
            <li><code>[</code> and <code>]</code>: previous/next page</li>
            <li><code>Arrow</code>: move selected field by the configured step when <code>Arrow keys</code> movement is enabled</li>
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
      'Connect local data sources or Fill By Link respondent records, search a record, and populate mapped fields with predictable behavior.',
    sections: [
      {
        id: 'data-source-support',
        title: 'Data source support',
        body: (
          <ul>
            <li>CSV, XLS, and JSON include headers and rows for record-based filling.</li>
            <li>Fill By Link respondent submissions are stored as structured records and can be selected from the workspace.</li>
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
            <li>If you published Fill By Link, open the respondent list for that saved template and select a saved submission.</li>
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
            <li>Search &amp; Fill is enabled only for CSV/XLSX/JSON with at least one row, stored respondent records, and a loaded document.</li>
            <li>Public Fill By Link forms close automatically when their response cap is reached: free closes at 5 responses and premium closes at 10,000 responses.</li>
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
    key: 'fill-by-link',
    slug: 'fill-by-link',
    navLabel: 'Fill By Link',
    title: 'Fill By Link',
    summary:
      'Publish a DullyPDF-hosted form from a saved template or open group, share the generated link, and turn stored respondent answers into PDFs when needed, with optional post-submit downloads for template respondents.',
    sections: [
      {
        id: 'what-gets-published',
        title: 'What gets published',
        body: (
          <ul>
            <li>Fill By Link starts from a saved template or an open group. Unsaved work cannot be published.</li>
            <li>The generated link points to a DullyPDF-hosted HTML form, not the PDF file itself.</li>
            <li>Template links publish one saved form. Group links publish one merged form built from every distinct respondent-facing field in the open group.</li>
            <li>Changing group membership closes the current group link so the next publish reflects the updated schema.</li>
          </ul>
        ),
      },
      {
        id: 'owner-publishing-flow',
        title: 'Owner publishing flow',
        body: (
          <ol>
            <li>Open the saved template or saved group you want to publish.</li>
            <li>Use Fill By Link to generate the public URL, set global defaults such as requiredness and text limits, and tune each visible question before sharing.</li>
            <li>Open the generated URL yourself first to confirm question wording and mobile layout.</li>
            <li>Copy the link and send it to respondents. Their answers are stored in DullyPDF under the owner account.</li>
          </ol>
        ),
      },
      {
        id: 'what-respondents-see',
        title: 'What respondents see',
        body: (
          <>
            <p>
              Respondents fill a mock-form style HTML experience with the fields you chose to publish. They do not
              edit the live PDF directly.
            </p>
            <p>
              This separation keeps the PDF template stable while still letting teams collect answers from phones,
              tablets, and desktops.
            </p>
            <p>
              For template links only, owners can optionally expose a post-submit button that lets respondents
              download a PDF copy of what they just submitted.
            </p>
            <p>
              Template builders can also add custom questions that do not exist on the PDF itself, while group links
              currently stay limited to the merged packet field set.
            </p>
          </>
        ),
      },
      {
        id: 'reviewing-responses',
        title: 'Reviewing responses and generating PDFs',
        body: (
          <ol>
            <li>Open the saved respondent list in the workspace.</li>
            <li>Select one submission and hand it to Search &amp; Fill just like a local CSV/XLSX/JSON row.</li>
            <li>Generate the PDF only when you are ready to materialize that response into the active template or group.</li>
            <li>Download the output immediately or keep working with the stored respondent record later.</li>
          </ol>
        ),
      },
      {
        id: 'limits-and-sharing',
        title: 'Limits and sharing guidance',
        body: (
          <ul>
            <li>Free accounts get 1 active Fill By Link and up to 5 accepted responses.</li>
            <li>Premium accounts can publish a shareable link for every saved template and accept up to 10,000 responses per link.</li>
            <li>Preview the public form before you share it so required fields and labels match what respondents should submit.</li>
          </ul>
        ),
      },
    ],
  },
  {
    key: 'create-group',
    slug: 'create-group',
    navLabel: 'Create Group',
    title: 'Create Group and Group Workflows',
    summary:
      'Use groups to organize multi-document packets, switch between saved templates quickly, and run full document workflows across the group.',
    sections: [
      {
        id: 'what-a-group-is',
        title: 'What a group is',
        body: (
          <ul>
            <li>A group is a named collection of saved templates that belong to one packet or workflow.</li>
            <li>Opening a group loads the alphabetically first template first, then lets you switch between member templates from the header.</li>
            <li>Groups are best for packets that share respondents, schema expectations, or repeat end-to-end processing steps.</li>
          </ul>
        ),
      },
      {
        id: 'create-and-open-groups',
        title: 'Create and open groups',
        body: (
          <ol>
            <li>Create a group from the upload screen or while organizing saved templates.</li>
            <li>Add the templates that belong together in one workflow.</li>
            <li>Open the group to work inside a packet context instead of reopening templates one at a time.</li>
            <li>Use the header selector to move between member templates while keeping the group context active.</li>
          </ol>
        ),
      },
      {
        id: 'group-search-fill',
        title: 'Search and fill full groups',
        body: (
          <ul>
            <li>When a group is open, Search &amp; Fill can apply one selected record across the packet instead of just one template.</li>
            <li>This is the fastest way to populate full document sets that share a respondent or client record.</li>
            <li>Group workflows keep the current template snapshots aligned so you can switch documents without losing the packet context.</li>
          </ul>
        ),
      },
      {
        id: 'group-rename-map',
        title: 'Rename and remap entire groups',
        body: (
          <ul>
            <li>`Rename + Map Group` runs batch Rename + Map across every saved template in the open group.</li>
            <li>Use this when a full packet needs standardized field names and schema alignment together.</li>
            <li>The run overwrites each saved template on success, so test the packet once before using it in production.</li>
          </ul>
        ),
      },
      {
        id: 'group-fill-by-link',
        title: 'Group Fill By Link and packet publishing',
        body: (
          <ul>
            <li>Open a group to publish one merged Fill By Link that asks for every distinct respondent-facing field across the packet.</li>
            <li>Owners can still review stored responses in the workspace and generate the final PDFs only when needed.</li>
            <li>If group membership changes, republish the group link so the public form matches the new packet schema.</li>
          </ul>
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
      'Understand when to download immediately versus saving templates to your profile for reuse, Fill By Link publishing, and respondent management.',
    sections: [
      {
        id: 'download-vs-save',
        title: 'Download vs save',
        body: (
          <ul>
            <li>Download when you need a one-off generated output immediately.</li>
            <li>Save to profile when the template will be reused or shared within your account context.</li>
            <li>Saved forms persist template metadata including checkbox rules and hints.</li>
            <li>Fill By Link starts from a saved form or an open group because the public respondent link is tied to the owner account and saved template set.</li>
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
              Saved forms are also the publication point for Fill By Link. You can publish one link for the active
              template or, when a group is open, publish one merged link that asks for every distinct field across that
              group. Respondent records stay attached to the owner account and the published template/group snapshot.
            </p>
          </>
        ),
      },
      {
        id: 'fill-by-link-owner-flow',
        title: 'Fill By Link owner flow',
        body: (
          <ol>
            <li>Open a saved template to publish a template link, or open a group to publish one merged group link.</li>
            <li>Open your own generated public link to preview the respondent form before you send it out.</li>
            <li>Share the public DullyPDF-hosted HTML form with respondents.</li>
            <li>DullyPDF always requires each respondent to provide a name or ID before a submission is accepted.</li>
            <li>Review stored respondent submissions in the workspace.</li>
            <li>Select one respondent and run the existing Search &amp; Fill materialization flow against the active template or group targets.</li>
            <li>Download the final PDF only when it is needed.</li>
          </ol>
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
            <p>
              Fill By Link tier limits are separate from credits: free includes 1 active published link with 5 accepted
              responses, while premium supports a shareable link on every saved template with up to 10,000 accepted
              responses per link.
            </p>
            <p>
              For the marketing-facing summary of those tiers, use the public <a href="/free-features">Free Features</a> and{' '}
              <a href="/premium-features">Premium Features</a> pages.
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
              <li>
                If an account downgrades to free while holding more saved forms than the free tier allows, DullyPDF keeps
                the default oldest set, opens a 30-day grace period, and shows a retention dialog on each site visit so
                the owner can swap which saved forms stay, delete the queued set immediately, or reactivate Pro.
              </li>
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
            <li>If a template already has active Fill By Link traffic, publish replacement versions intentionally so response ownership remains clear.</li>
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
            contacting support at <a href="mailto:justin@dullypdf.com">justin@dullypdf.com</a>.
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
