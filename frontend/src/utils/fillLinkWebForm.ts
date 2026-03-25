import type { CheckboxRule, PdfField } from '../types';
import type { FillLinkQuestion, FillLinkQuestionOption, FillLinkWebFormConfig } from '../services/api';

const NON_ALNUM_RE = /[^a-z0-9]+/g;
const CAMEL_CASE_RE = /([a-z0-9])([A-Z])/g;
const TEXT_LIKE_TYPES = new Set(['text', 'textarea', 'date', 'email', 'phone']);
const OPTION_TYPES = new Set(['radio', 'multi_select', 'select']);
const BOOLEAN_TYPES = new Set(['boolean', 'checkbox']);
const SUPPORTED_TYPES = new Set(['text', 'textarea', 'date', 'boolean', 'radio', 'multi_select', 'select', 'email', 'phone']);
const IDENTITY_KEY = 'respondent_identifier';
const IDENTITY_LABEL = 'Respondent Name or ID';

function randomId(): string {
  const cryptoApi =
    typeof globalThis !== 'undefined' && typeof globalThis.crypto !== 'undefined'
      ? globalThis.crypto
      : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID().replace(/-/g, '');
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

export function normalizeFillLinkKey(value: string | null | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  const collapsed = raw.replace(CAMEL_CASE_RE, '$1_$2');
  return collapsed.toLowerCase().replace(NON_ALNUM_RE, '_').replace(/^_+|_+$/g, '');
}

export function humanizeFillLinkLabel(value: string | null | undefined, fallback = 'Field'): string {
  const raw = String(value ?? '').trim();
  if (!raw) return fallback;
  const collapsed = raw
    .replace(CAMEL_CASE_RE, '$1 $2')
    .replace(/[_\-.]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!collapsed) return fallback;
  return collapsed
    .split(' ')
    .map((segment) => {
      const upper = segment.toUpperCase();
      if (['SSN', 'DOB', 'ZIP', 'ID', 'MRN', 'PDF', 'URL'].includes(upper)) {
        return upper;
      }
      return `${segment.slice(0, 1).toUpperCase()}${segment.slice(1)}`;
    })
    .join(' ');
}

export function normalizeFillLinkQuestionType(value: string | null | undefined): FillLinkQuestion['type'] {
  const normalized = normalizeFillLinkKey(value) || 'text';
  if (normalized === 'checkbox') return 'boolean';
  if (SUPPORTED_TYPES.has(normalized)) {
    return normalized as FillLinkQuestion['type'];
  }
  return 'text';
}

function normalizeSourceType(
  question: Partial<FillLinkQuestion>,
): FillLinkQuestion['sourceType'] {
  const normalized = normalizeFillLinkKey(question.sourceType);
  if (normalized) {
    return normalized as FillLinkQuestion['sourceType'];
  }
  if (question.synthetic) return 'synthetic';
  if (normalizeFillLinkKey(question.groupKey)) return 'checkbox_group';
  if (normalizeFillLinkKey(question.key).startsWith('custom')) return 'custom';
  return 'pdf_field';
}

export function fillLinkQuestionSupportsTextLimit(type: FillLinkQuestion['type']): boolean {
  return TEXT_LIKE_TYPES.has(normalizeFillLinkQuestionType(type));
}

export function fillLinkQuestionSupportsOptions(type: FillLinkQuestion['type']): boolean {
  return OPTION_TYPES.has(normalizeFillLinkQuestionType(type));
}

export function fillLinkQuestionIsBoolean(type: FillLinkQuestion['type']): boolean {
  return BOOLEAN_TYPES.has(normalizeFillLinkQuestionType(type));
}

function defaultQuestionId(
  key: string | null | undefined,
  sourceType: FillLinkQuestion['sourceType'],
): string {
  const normalizedKey = normalizeFillLinkKey(key) || 'question';
  const normalizedSource = normalizeFillLinkKey(sourceType) || 'question';
  return `${normalizedSource}:${normalizedKey}`;
}

function normalizeQuestionOptions(options: FillLinkQuestionOption[] | undefined): FillLinkQuestionOption[] {
  const deduped = new Map<string, FillLinkQuestionOption>();
  for (const option of options || []) {
    const key = String(option?.key ?? '').trim() || normalizeFillLinkKey(option?.label) || '';
    const normalizedKey = normalizeFillLinkKey(key);
    if (!normalizedKey || deduped.has(normalizedKey)) continue;
    deduped.set(normalizedKey, {
      key,
      label: String(option?.label ?? '').trim() || humanizeFillLinkLabel(key, 'Option'),
    });
  }
  return Array.from(deduped.values());
}

function normalizePositiveInteger(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return Math.round(numeric);
}

function sortQuestions(questions: FillLinkQuestion[]): FillLinkQuestion[] {
  return questions
    .map((question, index) => ({
      question,
      index,
      order: normalizePositiveInteger(question.order) ?? index,
    }))
    .sort((left, right) => {
      if (left.order !== right.order) return left.order - right.order;
      return left.index - right.index;
    })
    .map(({ question }, index) => ({
      ...question,
      order: index,
    }));
}

export function sortFillLinkQuestions(questions: FillLinkQuestion[]): FillLinkQuestion[] {
  return sortQuestions(questions);
}

export function fillLinkQuestionSupportsRespondentIdentity(question: Partial<FillLinkQuestion>): boolean {
  if (question.requiredForRespondentIdentity) return true;
  const candidates = [
    normalizeFillLinkKey(question.key),
    normalizeFillLinkKey(question.sourceField),
    normalizeFillLinkKey(question.label),
  ];
  return candidates.some((candidate) => {
    if (!candidate) return false;
    return (
      [
        'respondent_identifier',
        'full_name',
        'name',
        'patient_name',
        'respondent_name',
        'first_name',
        'last_name',
        'id',
        'member_id',
        'patient_id',
        'record_id',
        'user_id',
        'employee_id',
        'customer_id',
        'case_id',
        'mrn',
      ].includes(candidate)
      || candidate.endsWith('_id')
    );
  });
}

function questionCandidateKeys(question: Partial<FillLinkQuestion>): string[] {
  return [
    normalizeFillLinkQuestionType(question.type),
    normalizeFillLinkKey(question.key),
    normalizeFillLinkKey(question.sourceField),
    normalizeFillLinkKey(question.label),
  ].filter(Boolean);
}

export function fillLinkQuestionLooksLikeEmail(question: Partial<FillLinkQuestion>): boolean {
  return questionCandidateKeys(question).some((candidate) => (
    candidate === 'email'
    || candidate.endsWith('_email')
    || candidate.includes('email_address')
  ));
}

function fillLinkQuestionLooksLikePhone(question: Partial<FillLinkQuestion>): boolean {
  return questionCandidateKeys(question).some((candidate) => (
    candidate === 'phone'
    || candidate === 'mobile_phone'
    || candidate === 'telephone'
    || candidate.endsWith('_phone')
    || candidate.endsWith('_telephone')
  ));
}

function inferFieldQuestionType(field: Pick<PdfField, 'name' | 'type'>): FillLinkQuestion['type'] {
  const normalizedFieldType = normalizeFillLinkKey(field.type) || 'text';
  if (normalizedFieldType === 'date') {
    return 'date';
  }
  const probe = {
    key: field.name,
    sourceField: field.name,
    label: field.name,
    type: normalizedFieldType,
  };
  if (fillLinkQuestionLooksLikeEmail(probe)) {
    return 'email';
  }
  if (fillLinkQuestionLooksLikePhone(probe)) {
    return 'phone';
  }
  return 'text';
}

export function fillLinkQuestionIsSigningCeremonyManaged(question: Partial<FillLinkQuestion>): boolean {
  return questionCandidateKeys(question).some((candidate) => (
    candidate === 'signature'
    || candidate.endsWith('_signature')
    || candidate.startsWith('signature_')
    || candidate.includes('_signature_')
  ));
}

function createSyntheticIdentityQuestion(order: number): FillLinkQuestion {
  return {
    id: defaultQuestionId(IDENTITY_KEY, 'synthetic'),
    key: IDENTITY_KEY,
    label: IDENTITY_LABEL,
    type: 'text',
    sourceType: 'synthetic',
    required: true,
    requiredForRespondentIdentity: true,
    synthetic: true,
    visible: true,
    order,
  };
}

function normalizeQuestion(
  question: Partial<FillLinkQuestion>,
  fallbackOrder: number,
): FillLinkQuestion {
  const sourceType = normalizeSourceType(question);
  const type = normalizeFillLinkQuestionType(question.type);
  const key = String(question.key ?? question.sourceField ?? '').trim() || IDENTITY_KEY;
  const requiredForRespondentIdentity = fillLinkQuestionSupportsRespondentIdentity(question);
  const normalized: FillLinkQuestion = {
    id: String(question.id ?? '').trim() || defaultQuestionId(key, sourceType),
    key,
    label: String(question.label ?? '').trim() || humanizeFillLinkLabel(key),
    type,
    sourceType,
    requiredForRespondentIdentity,
    required: Boolean(question.required) || (Boolean(question.synthetic) && requiredForRespondentIdentity),
    synthetic: Boolean(question.synthetic),
    visible: question.visible !== false,
    order: normalizePositiveInteger(question.order) ?? fallbackOrder,
    sourceField: String(question.sourceField ?? '').trim() || undefined,
    groupKey: String(question.groupKey ?? '').trim() || undefined,
    placeholder: String(question.placeholder ?? '').trim() || undefined,
    helpText: String(question.helpText ?? '').trim() || undefined,
    maxLength: fillLinkQuestionSupportsTextLimit(type) ? normalizePositiveInteger(question.maxLength) : null,
    options: fillLinkQuestionSupportsOptions(type) ? normalizeQuestionOptions(question.options) : undefined,
  };
  return normalized;
}

function mergeQuestionTypes(left: FillLinkQuestion['type'], right: FillLinkQuestion['type']): FillLinkQuestion['type'] {
  const normalized = new Set([normalizeFillLinkQuestionType(left), normalizeFillLinkQuestionType(right)]);
  if (normalized.has('multi_select')) return 'multi_select';
  if (normalized.has('select')) return 'select';
  if (normalized.has('radio')) return 'radio';
  if (normalized.has('date') && normalized.size === 1) return 'date';
  if (normalized.has('boolean') && normalized.size === 1) return 'boolean';
  return 'text';
}

function mergeQuestions(existing: FillLinkQuestion, incoming: FillLinkQuestion): FillLinkQuestion {
  const mergedType = mergeQuestionTypes(existing.type, incoming.type);
  const mergedOptions = fillLinkQuestionSupportsOptions(mergedType)
    ? normalizeQuestionOptions([...(existing.options || []), ...(incoming.options || [])])
    : undefined;
  return {
    ...existing,
    id: existing.id || incoming.id || defaultQuestionId(existing.key || incoming.key, existing.sourceType || incoming.sourceType),
    label: existing.label || incoming.label || humanizeFillLinkLabel(existing.key || incoming.key),
    type: mergedType,
    requiredForRespondentIdentity: Boolean(existing.requiredForRespondentIdentity || incoming.requiredForRespondentIdentity),
    sourceField: existing.sourceField || incoming.sourceField,
    groupKey: existing.groupKey || incoming.groupKey,
    sourceType: existing.sourceType || incoming.sourceType,
    synthetic: Boolean(existing.synthetic || incoming.synthetic),
    required: Boolean(existing.required || incoming.required),
    visible: existing.visible !== false || incoming.visible !== false,
    order: Math.min(normalizePositiveInteger(existing.order) ?? 0, normalizePositiveInteger(incoming.order) ?? 0),
    options: mergedOptions,
  };
}

function ensureIdentityQuestion(questions: FillLinkQuestion[]): FillLinkQuestion[] {
  const normalized = sortQuestions(
    questions.map((question, index) => {
      const nextQuestion = normalizeQuestion(question, index);
      nextQuestion.requiredForRespondentIdentity = fillLinkQuestionSupportsRespondentIdentity(nextQuestion);
      if (nextQuestion.synthetic && nextQuestion.requiredForRespondentIdentity) {
        nextQuestion.required = true;
      }
      return nextQuestion;
    }),
  );
  const hasIdentity = normalized.some((question) => question.requiredForRespondentIdentity);
  if (hasIdentity) {
    return normalized;
  }
  return sortQuestions([createSyntheticIdentityQuestion(0), ...normalized]);
}

function resolveCheckboxQuestionType(optionCount: number, operation: string | null | undefined): FillLinkQuestion['type'] {
  if (normalizeFillLinkKey(operation) === 'list') {
    return 'multi_select';
  }
  if (optionCount <= 1) {
    return 'boolean';
  }
  return 'radio';
}

export function buildFillLinkQuestionsFromFields(
  fields: PdfField[],
  checkboxRules: CheckboxRule[] = [],
): FillLinkQuestion[] {
  const orderedFields = [...fields].sort((left, right) => {
    if (left.page !== right.page) return left.page - right.page;
    if (left.rect.y !== right.rect.y) return left.rect.y - right.rect.y;
    if (left.rect.x !== right.rect.x) return left.rect.x - right.rect.x;
    return left.name.localeCompare(right.name);
  });
  const checkboxRuleMap = new Map<string, CheckboxRule>();
  for (const rule of checkboxRules || []) {
    const groupKey = normalizeFillLinkKey(rule?.groupKey);
    if (!groupKey || checkboxRuleMap.has(groupKey)) continue;
    checkboxRuleMap.set(groupKey, rule);
  }

  const questions: FillLinkQuestion[] = [];
  const seenTextKeys = new Set<string>();
  const checkboxGroups = new Map<string, FillLinkQuestion>();

  for (const field of orderedFields) {
    const fieldType = normalizeFillLinkKey(field.type) || 'text';
    if (fieldType !== 'checkbox') {
      const sourceField = String(field.name ?? '').trim();
      const normalizedKey = normalizeFillLinkKey(sourceField);
      if (!sourceField || !normalizedKey || seenTextKeys.has(normalizedKey)) continue;
      seenTextKeys.add(normalizedKey);
      questions.push(normalizeQuestion({
        id: defaultQuestionId(sourceField, 'pdf_field'),
        key: sourceField,
        label: humanizeFillLinkLabel(sourceField),
        type: inferFieldQuestionType(field),
        sourceType: 'pdf_field',
        sourceField,
        visible: true,
        required: false,
        order: questions.length,
      }, questions.length));
      continue;
    }

    const rawGroupKey = String(field.groupKey ?? field.name ?? '').trim();
    const normalizedGroupKey = normalizeFillLinkKey(rawGroupKey);
    if (!rawGroupKey || !normalizedGroupKey) continue;
    const rule = checkboxRuleMap.get(normalizedGroupKey);
    const answerKey = String(rule?.databaseField ?? rawGroupKey).trim();
    const existingGroup = checkboxGroups.get(normalizedGroupKey);
    if (!existingGroup) {
      const labelSource = String(field.groupLabel ?? rule?.databaseField ?? rawGroupKey).trim();
      const nextGroup = normalizeQuestion({
        id: defaultQuestionId(answerKey, 'checkbox_group'),
        key: answerKey,
        label: humanizeFillLinkLabel(labelSource, 'Choice'),
        type: 'radio',
        sourceType: 'checkbox_group',
        groupKey: rawGroupKey,
        required: false,
        visible: true,
        order: questions.length,
      }, questions.length);
      nextGroup.options = [];
      (nextGroup as FillLinkQuestion & { operation?: string }).operation = rule?.operation;
      checkboxGroups.set(normalizedGroupKey, nextGroup);
      questions.push(nextGroup);
    }

    const group = checkboxGroups.get(normalizedGroupKey);
    if (!group) continue;
    const optionKey = String(field.optionKey ?? field.name ?? '').trim();
    const optionLabel = String(field.optionLabel ?? optionKey).trim();
    const normalizedOptionKey = normalizeFillLinkKey(optionKey || optionLabel);
    if (!normalizedOptionKey) continue;
    group.options = normalizeQuestionOptions([
      ...(group.options || []),
      {
        key: optionKey || normalizedOptionKey,
        label: humanizeFillLinkLabel(optionLabel, 'Option'),
      },
    ]);
  }

  for (const question of questions) {
    if (question.sourceType === 'checkbox_group') {
      const operation = (question as FillLinkQuestion & { operation?: string }).operation;
      question.type = resolveCheckboxQuestionType(question.options?.length ?? 0, operation);
      if (question.type === 'boolean') {
        delete question.options;
      }
    }
  }

  return ensureIdentityQuestion(questions);
}

export function mergeFillLinkQuestionSets(questionSets: FillLinkQuestion[][]): FillLinkQuestion[] {
  const mergedQuestions = new Map<string, FillLinkQuestion>();
  for (const questionSet of questionSets) {
    for (const question of ensureIdentityQuestion(questionSet || [])) {
      const normalized = normalizeQuestion(question, normalizePositiveInteger(question.order) ?? mergedQuestions.size);
      const lookupKey = normalizeFillLinkKey(normalized.key);
      if (!lookupKey) continue;
      const existing = mergedQuestions.get(lookupKey);
      if (!existing) {
        mergedQuestions.set(lookupKey, normalized);
        continue;
      }
      mergedQuestions.set(lookupKey, mergeQuestions(existing, normalized));
    }
  }
  return ensureIdentityQuestion(Array.from(mergedQuestions.values()));
}

export function buildFillLinkWebFormConfig(
  defaultQuestions: FillLinkQuestion[],
  existingConfig: FillLinkWebFormConfig | null | undefined,
): FillLinkWebFormConfig {
  const normalizedDefaults = ensureIdentityQuestion(defaultQuestions || []);
  const defaultById = new Map<string, FillLinkQuestion>();
  const defaultByKey = new Map<string, FillLinkQuestion>();
  for (const question of normalizedDefaults) {
    defaultById.set(normalizeFillLinkKey(question.id), question);
    defaultByKey.set(normalizeFillLinkKey(question.key), question);
  }

  if (!existingConfig?.questions?.length) {
    return {
      schemaVersion: 2,
      introText: String(existingConfig?.introText ?? '').trim() || null,
      defaultTextMaxLength: normalizePositiveInteger(existingConfig?.defaultTextMaxLength),
      questions: sortQuestions(normalizedDefaults),
    };
  }

  const storedQuestions: FillLinkQuestion[] = [];
  const seenDefaultKeys = new Set<string>();

  for (const rawQuestion of existingConfig.questions) {
    const normalizedQuestion = normalizeQuestion(rawQuestion, storedQuestions.length);
    if (normalizeSourceType(normalizedQuestion) === 'custom') {
      storedQuestions.push(normalizedQuestion);
      continue;
    }

    const matchedDefault = defaultById.get(normalizeFillLinkKey(normalizedQuestion.id))
      || defaultByKey.get(normalizeFillLinkKey(normalizedQuestion.key))
      || defaultByKey.get(normalizeFillLinkKey(normalizedQuestion.sourceField));
    if (!matchedDefault) continue;
    seenDefaultKeys.add(normalizeFillLinkKey(matchedDefault.key));
    storedQuestions.push({
      ...matchedDefault,
      label: normalizedQuestion.label || matchedDefault.label,
      visible: normalizedQuestion.visible !== false,
      required: Boolean(normalizedQuestion.required),
      maxLength: fillLinkQuestionSupportsTextLimit(matchedDefault.type) ? normalizedQuestion.maxLength : null,
      placeholder: normalizedQuestion.placeholder || undefined,
      helpText: normalizedQuestion.helpText || undefined,
      order: normalizePositiveInteger(normalizedQuestion.order) ?? storedQuestions.length,
    });
  }

  for (const defaultQuestion of normalizedDefaults) {
    const normalizedKey = normalizeFillLinkKey(defaultQuestion.key);
    if (seenDefaultKeys.has(normalizedKey)) continue;
    storedQuestions.push(defaultQuestion);
  }

  return {
    schemaVersion: 2,
    introText: String(existingConfig.introText ?? '').trim() || null,
    defaultTextMaxLength: normalizePositiveInteger(existingConfig.defaultTextMaxLength),
    questions: sortQuestions(ensureIdentityQuestion(storedQuestions)),
  };
}

export function buildPublishedFillLinkQuestions(
  webFormConfig: FillLinkWebFormConfig | null | undefined,
  options?: {
    requireAllFields?: boolean;
  },
): FillLinkQuestion[] {
  const defaultTextMaxLength = normalizePositiveInteger(webFormConfig?.defaultTextMaxLength);
  const requireAllFields = Boolean(options?.requireAllFields);
  const visibleQuestions = sortQuestions(
    (webFormConfig?.questions || [])
      .map((question, index) => normalizeQuestion(question, index))
      .filter((question) => question.visible !== false),
  ).map((question, index) => {
    const required = Boolean(
      requireAllFields
      || question.required
      || (question.synthetic && question.requiredForRespondentIdentity),
    );
    const normalizedType = normalizeFillLinkQuestionType(question.type);
    const publishedQuestion: FillLinkQuestion = {
      ...question,
      type: normalizedType,
      label: question.label || humanizeFillLinkLabel(question.key),
      required,
      visible: true,
      order: index,
      maxLength: fillLinkQuestionSupportsTextLimit(normalizedType)
        ? (normalizePositiveInteger(question.maxLength) ?? defaultTextMaxLength)
        : null,
      options: fillLinkQuestionSupportsOptions(normalizedType) ? normalizeQuestionOptions(question.options) : undefined,
      placeholder: String(question.placeholder ?? '').trim() || undefined,
      helpText: String(question.helpText ?? '').trim() || undefined,
    };
    if (fillLinkQuestionIsBoolean(normalizedType)) {
      delete publishedQuestion.options;
      publishedQuestion.maxLength = null;
    }
    return publishedQuestion;
  }).filter((question) => {
    if (fillLinkQuestionSupportsOptions(question.type)) {
      return (question.options?.length ?? 0) > 0;
    }
    return true;
  });

  const hasIdentityQuestion = visibleQuestions.some((question) => question.requiredForRespondentIdentity);
  if (hasIdentityQuestion) {
    return visibleQuestions;
  }

  const syntheticQuestion = createSyntheticIdentityQuestion(0);
  syntheticQuestion.maxLength = defaultTextMaxLength;
  return sortQuestions([syntheticQuestion, ...visibleQuestions]);
}

export function buildFallbackFillLinkWebFormConfigFromPublishedQuestions(
  questions: FillLinkQuestion[] | undefined,
): FillLinkWebFormConfig {
  return {
    schemaVersion: 2,
    introText: null,
    defaultTextMaxLength: null,
    questions: sortQuestions(ensureIdentityQuestion((questions || []).map((question, index) => normalizeQuestion({
      ...question,
      visible: question.visible !== false,
      required: Boolean(question.required),
      order: normalizePositiveInteger(question.order) ?? index,
    }, index)))),
  };
}

export function createCustomFillLinkQuestion(type: FillLinkQuestion['type'] = 'text'): FillLinkQuestion {
  const idSuffix = randomId();
  const normalizedType = normalizeFillLinkQuestionType(type);
  return normalizeQuestion({
    id: `custom:${idSuffix}`,
    key: `custom__${idSuffix}`,
    label: 'New question',
    type: normalizedType,
    sourceType: 'custom',
    required: false,
    visible: true,
    order: 0,
    options: fillLinkQuestionSupportsOptions(normalizedType)
      ? [
        { key: 'option_1', label: 'Option 1' },
        { key: 'option_2', label: 'Option 2' },
      ]
      : undefined,
  }, 0);
}

export function validateFillLinkWebForm(
  webFormConfig: FillLinkWebFormConfig,
  publishedQuestions: FillLinkQuestion[],
): string | null {
  if (!publishedQuestions.length) {
    return 'Add at least one visible web-form question before publishing.';
  }
  for (const question of webFormConfig.questions || []) {
    const normalized = normalizeQuestion(question, 0);
    if (normalized.sourceType !== 'custom') continue;
    if (!normalized.label) {
      return 'Every custom question needs a label.';
    }
    if (fillLinkQuestionSupportsOptions(normalized.type) && (normalized.options?.length ?? 0) === 0 && normalized.visible !== false) {
      return `${normalized.label} needs at least one option before publishing.`;
    }
  }
  return null;
}
