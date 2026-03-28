import type { ReactNode } from 'react';
import { USAGE_DOCS_PAGES as SHARED_USAGE_DOCS_PAGES } from '../../config/publicRouteSeoData.mjs';
import type { IntentPageKey } from '../../config/intentPages';

export type UsageDocsPageKey =
  | 'index'
  | 'getting-started'
  | 'detection'
  | 'rename-mapping'
  | 'editor-workflow'
  | 'search-fill'
  | 'fill-by-link'
  | 'signature-workflow'
  | 'api-fill'
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
  relatedWorkflowKeys?: IntentPageKey[];
  sections: UsageDocsSection[];
};

export type ResolvedUsageDocsPath =
  | { kind: 'canonical'; pageKey: UsageDocsPageKey }
  | { kind: 'redirect'; targetPath: string }
  | { kind: 'not-found'; requestedPath: string };

type SharedUsageDocsPage = {
  key: UsageDocsPageKey;
  slug: string;
  path: string;
  navLabel: string;
  title: string;
  summary: string;
  relatedWorkflowKeys?: IntentPageKey[];
  sectionTitles: string[];
};

const USAGE_DOCS_PAGE_METADATA = SHARED_USAGE_DOCS_PAGES as SharedUsageDocsPage[];
const USAGE_DOCS_PAGE_METADATA_BY_KEY = new Map<UsageDocsPageKey, SharedUsageDocsPage>(
  USAGE_DOCS_PAGE_METADATA.map((page) => [page.key, page]),
);

const getUsageDocsPageMetadata = (
  pageKey: UsageDocsPageKey,
): Pick<UsageDocsPage, 'key' | 'slug' | 'navLabel' | 'title' | 'summary' | 'relatedWorkflowKeys'> => {
  const page = USAGE_DOCS_PAGE_METADATA_BY_KEY.get(pageKey);
  if (!page) {
    throw new Error(`Unknown usage docs page key: ${pageKey}`);
  }

  return {
    key: page.key,
    slug: page.slug,
    navLabel: page.navLabel,
    title: page.title,
    summary: page.summary,
    relatedWorkflowKeys: page.relatedWorkflowKeys,
  };
};

const USAGE_DOCS_PAGES: UsageDocsPage[] = [
  {
    ...getUsageDocsPageMetadata('index'),
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
              Use <a href="/usage-docs/rename-mapping">Rename + Mapping</a> for OpenAI payload boundaries and checkbox/radio rule precedence.
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
              Use <a href="/usage-docs/signature-workflow">Signature Workflow</a> for email-based signing, web-form-to-sign handoff, immutable record freeze, and owner artifact retrieval.
            </li>
            <li>
              Use <a href="/usage-docs/api-fill">API Fill</a> for template-scoped JSON-to-PDF endpoints, key rotation, hosted schema downloads, and server-side fill guardrails.
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
        id: 'public-routes-vs-docs',
        title: 'Public routes versus docs',
        body: (
          <>
            <p>
              The workflow and industry landing pages are meant to explain why a route exists and what kind of problem
              it solves. The usage docs are where the implementation details live. If a search-intent page answers the
              strategic question and you are ready to build, come back here for the exact runtime behavior.
            </p>
            <p>
              That split is deliberate. It keeps commercial pages focused on the document problem and keeps the docs
              focused on operator behavior, guardrails, limits, and validation steps. The safest path is usually:
              choose the right route first, then use the matching docs page to validate one representative workflow.
            </p>
          </>
        ),
      },
      {
        id: 'three-fastest-starting-paths',
        title: 'Three fastest starting paths',
        body: (
          <ul>
            <li>Template setup: start with <a href="/usage-docs/getting-started">Getting Started</a> when you need one recurring PDF to reach its first safe fill quickly.</li>
            <li>Row-based filling: start with <a href="/usage-docs/search-fill">Search &amp; Fill</a> when the record already exists in CSV, XLSX, JSON, or a stored respondent submission.</li>
            <li>Respondent collection: start with <a href="/usage-docs/fill-by-link">Fill By Link</a> when the row does not exist yet and someone must submit it first.</li>
          </ul>
        ),
      },
      {
        id: 'first-validation-loop',
        title: 'First validation loop',
        body: (
          <ol>
            <li>Choose one recurring document, not every possible packet variation.</li>
            <li>Run detection and review low-confidence items first.</li>
            <li>Normalize names and mappings before you worry about volume.</li>
            <li>Fill one representative record and inspect the output PDF carefully.</li>
            <li>Only after that should you publish a Fill By Link, group the template, or expose an API endpoint.</li>
          </ol>
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
    ...getUsageDocsPageMetadata('getting-started'),
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
        id: 'first-30-minutes',
        title: 'First 30 minutes',
        body: (
          <ol>
            <li>Pick one recurring PDF instead of a full packet.</li>
            <li>Run detection and clean the low-confidence items immediately.</li>
            <li>Rename or map only after the field geometry is believable.</li>
            <li>Fill one realistic record, inspect the PDF, clear it, and fill again.</li>
            <li>Only after that should you publish a Fill By Link, save packet groups, or expose API Fill.</li>
          </ol>
        ),
      },
      {
        id: 'common-first-run-mistakes',
        title: 'Most common first-run mistakes',
        body: (
          <ul>
            <li>Uploading several document variations before one canonical template is stable.</li>
            <li>Running mapping before low-confidence geometry and checkbox cleanup are reviewed.</li>
            <li>Judging the workflow from field detection alone instead of from one full fill cycle.</li>
            <li>Publishing links or sharing templates before date, checkbox, and repeated-name fields are tested with a real record.</li>
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
    ...getUsageDocsPageMetadata('detection'),
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
              Field types supported in the UI are <code>text</code>, <code>date</code>, <code>signature</code>, <code>checkbox</code>, and <code>radio</code>.
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
        id: 'pdf-quality-rubric',
        title: 'PDF quality rubric',
        body: (
          <ul>
            <li>Best: native PDFs with high contrast, clear form lines, and predictable spacing.</li>
            <li>Usable with review: scans that are readable but have light skew, compression noise, or inconsistent line weight.</li>
            <li>High-risk: faint scans, dense tables, decorative borders, or layouts where fields are packed tightly together.</li>
            <li>The dirtier the PDF, the more important it is to review low-confidence candidates before rename or mapping.</li>
          </ul>
        ),
      },
      {
        id: 'redraw-vs-resize',
        title: 'When to redraw instead of resize',
        body: (
          <ul>
            <li>Resize when the candidate is fundamentally the right field but the geometry is slightly off.</li>
            <li>Redraw when a decorative box was mistaken for a field or when the detection captures the wrong label/line pair entirely.</li>
            <li>Delete and recreate when the current candidate would require several compensating edits that are harder to audit later.</li>
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
    ...getUsageDocsPageMetadata('rename-mapping'),
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
            <li>
              Review <code>radioGroupSuggestions</code> after mapping runs so single-select groups stay separate from
              true multi-select checkbox groups.
            </li>
            <li>Treat AI output as recommendations and validate before production usage.</li>
          </ul>
        ),
      },
      {
        id: 'concrete-mapping-examples',
        title: 'Concrete mapping examples',
        body: (
          <ul>
            <li>Text field: map <code>insured_name</code> or <code>employee_first_name</code> directly to a stable string column.</li>
            <li>Checkbox enum: map one group to values like <code>single</code>, <code>married</code>, or other categorical tokens via <code>enum</code> rules.</li>
            <li>Radio group: keep one explicit group key and distinct option keys so a single selected value does not drift into multi-select behavior later.</li>
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
            <p>Search &amp; Fill applies checkbox/radio logic in this order:</p>
            <ol>
              <li>Direct field-name boolean match.</li>
              <li>Direct option-key match.</li>
              <li>Direct group-value match (`i_...`, `checkbox_...`, or raw group key).</li>
              <li><code>checkboxRules</code>.</li>
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
        id: 'schema-hygiene-anti-patterns',
        title: 'Schema hygiene anti-patterns',
        body: (
          <ul>
            <li>Headers that change spelling or casing between exports.</li>
            <li>Multiple columns that mean the same thing but are not normalized intentionally.</li>
            <li>Boolean or checkbox values that mix <code>yes/no</code>, <code>1/0</code>, blanks, and custom tokens without a documented rule.</li>
            <li>Mapping directly from vague field names such as <code>Text1</code> or duplicated labels when Rename should have run first.</li>
          </ul>
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
    ...getUsageDocsPageMetadata('editor-workflow'),
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
            <li>
              Use inspector create tools to draw text, date, signature, checkbox, and radio fields directly on-canvas,
              including quick-radio helpers for common single-select groups.
            </li>
            <li>Use inspector inputs for exact x/y/width/height updates.</li>
            <li>Delete invalid candidates to keep templates clean.</li>
            <li>Geometry is clamped to page bounds and type-based minimum sizes.</li>
            <li>If a selected field is hidden by active filters, use <code>Reveal selected</code> in the list panel.</li>
          </ul>
        ),
      },
      {
        id: 'ten-minute-cleanup-order',
        title: 'Ten-minute cleanup order',
        body: (
          <ol>
            <li>Review low-confidence detections and obvious false positives first.</li>
            <li>Fix page assignment, geometry, and field type mistakes before naming cleanup.</li>
            <li>Normalize names and group metadata once the field set is visually stable.</li>
            <li>Run one Search &amp; Fill validation pass before deciding the template is done.</li>
          </ol>
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
            <li><code>T</code> / <code>D</code> / <code>S</code> / <code>C</code> / <code>R</code>: activate Text/Date/Signature/Checkbox/Radio create tools</li>
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
    ...getUsageDocsPageMetadata('search-fill'),
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
        id: 'search-vs-link-vs-api',
        title: 'Search & Fill versus Fill By Link versus API Fill',
        body: (
          <ul>
            <li>Use Search &amp; Fill when an operator is choosing one record inside the workspace.</li>
            <li>Use Fill By Link when the record still needs to be collected from a respondent first.</li>
            <li>Use API Fill when another system already has the record and needs a hosted JSON-to-PDF endpoint.</li>
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
      {
        id: 'why-partial-fills-happen',
        title: 'Why partial fills happen',
        body: (
          <ul>
            <li>Some fields are still unmapped or mapped to unstable source headers.</li>
            <li>Date or checkbox values need normalization rules that the current row does not satisfy.</li>
            <li>The template was updated but the operator is still validating stale output without clearing and refilling.</li>
            <li>Alias fallbacks help, but they do not replace explicit mapping on important production templates.</li>
          </ul>
        ),
      },
    ],
  },
  {
    ...getUsageDocsPageMetadata('fill-by-link'),
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
            <p>
              Template links can also require signature after submit. In that mode the public web form collects the
              respondent data first, then hands the same stored response into the signing ceremony so the signer reviews
              the exact filled record before adopting a signature.
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
            <li>
              If post-submit signing was enabled and the respondent completed it, download the signed PDF and audit
              receipt directly from that response row.
            </li>
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
    ...getUsageDocsPageMetadata('signature-workflow'),
    sections: [
      {
        id: 'two-entry-paths',
        title: 'Two entry paths, one signing engine',
        body: (
          <ul>
            <li><code>Send PDF for Signature by email</code> starts from the current PDF and freezes that exact record before send.</li>
            <li><code>Require signature after submit</code> starts from a template Fill By Web Form Link, stores the respondent answers, materializes the filled PDF, then hands the signer into the same ceremony.</li>
            <li>Both paths converge on the same immutable PDF boundary before the signer sees the document, and both now begin with email verification on the public signing page.</li>
            <li>The owner workflow remains one request per signer, even when the UI saves recipient batches from pasted or uploaded TXT/CSV data.</li>
          </ul>
        ),
      },
      {
        id: 'signer-ceremony',
        title: 'Public signer ceremony',
        body: (
          <ol>
            <li>The signer opens the public <code>/sign/:token</code> route.</li>
            <li>Email verification unlocks the immutable PDF for every emailed signing request.</li>
            <li>Business requests then go through review -&gt; adopt signature -&gt; explicit finish-sign.</li>
            <li>Consumer requests add a separate electronic-record consent step before review can continue.</li>
            <li>Manual fallback can pause the electronic ceremony and switch the request into owner follow-up instead of forcing e-signing.</li>
          </ol>
        ),
      },
      {
        id: 'artifacts-and-owner-visibility',
        title: 'Artifacts and owner visibility',
        body: (
          <ul>
            <li>Completed requests store the immutable source PDF, final signed PDF, audit-manifest envelope, and human-readable audit receipt.</li>
            <li>The owner `Responses` tab in the signing dialog surfaces waiting vs signed requests plus signed-form and audit-receipt downloads.</li>
            <li>Template Fill By Web Form Link responses also surface linked signing status so the owner can download the finished signed copy from the response row later.</li>
            <li>Signed PDFs are flattened before delivery so normal PDF viewers do not keep the underlying form widgets editable.</li>
            <li>Per-document signer-request caps are enforced server-side across both email and Fill By Web Form signing entry paths.</li>
          </ul>
        ),
      },
      {
        id: 'us-esign-scope',
        title: 'U.S. e-sign scope and guardrails',
        body: (
          <>
            <p>
              DullyPDF targets ordinary U.S. business e-sign workflows and is designed around core E-SIGN and UETA
              principles: explicit signer action, logical association with the exact record, retention-ready final
              artifacts, and paper/manual fallback when needed.
            </p>
            <p>
              Excluded or higher-assurance categories still need separate legal review. The product should not be
              marketed as a notary, qualified-signature, or regulated-signature system unless that scope is added
              deliberately later.
            </p>
            <p>
              Consumer-mode support is stronger than it was before the remediation work, but it is still not a blanket
              promise that every U.S. consumer document type or jurisdiction-specific rule is covered automatically.
              Teams still need document-type and policy review before turning on sensitive or excluded use cases.
            </p>
          </>
        ),
      },
    ],
  },
  {
    ...getUsageDocsPageMetadata('api-fill'),
    sections: [
      {
        id: 'what-api-fill-is',
        title: 'What API Fill is',
        body: (
          <ul>
            <li>API Fill publishes one saved-template snapshot as a hosted backend endpoint that accepts JSON and returns a PDF.</li>
            <li>Each endpoint has its own generated key, schema view, rate limits, monthly request limits, and audit activity.</li>
            <li>API Fill is a server-side runtime. It is different from Search &amp; Fill, which keeps selected record data local in the browser.</li>
          </ul>
        ),
      },
      {
        id: 'owner-manager-flow',
        title: 'Owner manager flow',
        body: (
          <ol>
            <li>Open a saved template in the workspace.</li>
            <li>Click <code>API Fill</code> to open the endpoint manager.</li>
            <li>Create the endpoint from the current saved-template snapshot, then copy the fill URL, public schema URL, POST example, and active key.</li>
            <li>Rotate or revoke keys from the same manager when credentials need to change.</li>
          </ol>
        ),
      },
      {
        id: 'payload-behavior',
        title: 'Payload and fill behavior',
        body: (
          <ul>
            <li>The public schema exposes field names, types, transforms, checkbox rules, and radio group expectations for the frozen template snapshot.</li>
            <li>Public requests must send a top-level <code>data</code> object. Misspelled top-level keys like <code>fields</code> or <code>stict</code> are rejected instead of being ignored.</li>
            <li>The manager examples use <code>strict=true</code> so integration smoke tests fail closed when a caller sends unknown keys.</li>
            <li>Blank strings remain valid scalar values, so callers can intentionally clear a text or date-style field instead of leaving the published default in place.</li>
            <li>Radio groups are resolved deterministically as one selected option key, not as a legacy checkbox-hint side channel.</li>
            <li>API Fill does not reuse the generic workspace materialize endpoint. It is its own hosted path with explicit auth, limits, and audit activity.</li>
            <li>The backend is designed not to store raw submitted record values by default unless a separate operational need is added later.</li>
          </ul>
        ),
      },
      {
        id: 'when-to-use-api-fill',
        title: 'When to use API Fill instead of Search and Fill',
        body: (
          <>
            <p>
              Use Search &amp; Fill when an operator is choosing a row interactively inside the workspace. Use API Fill
              when another system already has the record data and needs a hosted JSON-to-PDF endpoint for the same saved
              template.
            </p>
            <p>
              The template still needs the same review discipline either way: stable naming, correct checkbox and radio
              behavior, and one real end-to-end validation before the endpoint is treated as production-ready.
            </p>
          </>
        ),
      },
    ],
  },
  {
    ...getUsageDocsPageMetadata('create-group'),
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
        id: 'packet-design-rules',
        title: 'Packet design rules',
        body: (
          <ul>
            <li>Keep one canonical template per recurring document type instead of several near-duplicates.</li>
            <li>Use a group when the documents truly belong to one packet or respondent journey, not just because they are all PDFs.</li>
            <li>Validate one representative record across the whole packet before publishing a group link or running batch Rename + Map.</li>
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
    ...getUsageDocsPageMetadata('save-download-profile'),
    sections: [
      {
        id: 'download-vs-save',
        title: 'Download vs save',
        body: (
          <ul>
            <li>Download when you need a one-off generated output immediately. The workspace download menu now offers both a flat PDF and an editable PDF with fields preserved.</li>
            <li>Save to profile when the template will be reused or shared within your account context.</li>
            <li>Saved forms persist template metadata including checkbox rules, radio groups, and text transform rules.</li>
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
        id: 'must-save-before-publish',
        title: 'What must be saved before publishing or API use',
        body: (
          <ul>
            <li>Fill By Link requires a saved template or open saved group because the public form belongs to that saved snapshot.</li>
            <li>API Fill publishes one saved-template snapshot, not the unsaved working state in the editor.</li>
            <li>Signature workflows are safest after the template and current record state are both intentionally frozen.</li>
          </ul>
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
              Signing limits are separate from OpenAI credits too: by default free allows 10 signer requests for one
              immutable document version, while Pro allows 1,000.
            </p>
            <p>
              API Fill is a hosted backend runtime, not a browser-local tool. Published API endpoints are scoped to one
              saved template snapshot, use template-specific keys, and are governed by server-side page limits, monthly
              request caps, rate limits, and endpoint audit logs. Search &amp; Fill stays local in the browser; API Fill
              sends the submitted record data to DullyPDF backend services.
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
    ...getUsageDocsPageMetadata('troubleshooting'),
    sections: [
      {
        id: 'troubleshoot-by-stage',
        title: 'Troubleshoot by stage',
        body: (
          <ol>
            <li>Upload: confirm the file is a real PDF, under 50MB, and not encrypted.</li>
            <li>Detect: review low-confidence items and obvious false positives before moving on.</li>
            <li>Rename or map: confirm the schema is loaded, credits are available, and checkbox or radio metadata still make sense.</li>
            <li>Fill: clear the output, refill from one representative record, and inspect the risky fields first.</li>
            <li>Publish: confirm you are working from the intended saved template or group snapshot before sharing a link or API endpoint.</li>
          </ol>
        ),
      },
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
        id: 'capture-before-support',
        title: 'What to capture before support',
        body: (
          <ul>
            <li>The exact route or page you were on when the issue happened.</li>
            <li>The action order that led to the failure: upload, detect, rename, map, fill, publish, or sign.</li>
            <li>One screenshot that shows the state of the template or error message clearly.</li>
            <li>The exact validation or runtime message if one was shown.</li>
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
