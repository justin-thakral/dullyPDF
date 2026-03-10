export const DEFAULT_ARROW_KEY_MOVE_STEP = 5;
export const MIN_ARROW_KEY_MOVE_STEP = 1;
export const MAX_ARROW_KEY_MOVE_STEP = 50;

type FieldNudgeDirection = {
  deltaX: number;
  deltaY: number;
};

export type FieldNudgeCommand = FieldNudgeDirection & {
  step: number;
};

type FieldNudgeShortcutInput = {
  key: string;
  altKey: boolean;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  arrowKeyMoveEnabled: boolean;
  arrowKeyMoveStep: number;
};

const FIELD_NUDGE_DIRECTIONS: Record<string, FieldNudgeDirection> = {
  arrowleft: { deltaX: -1, deltaY: 0 },
  arrowright: { deltaX: 1, deltaY: 0 },
  arrowup: { deltaX: 0, deltaY: -1 },
  arrowdown: { deltaX: 0, deltaY: 1 },
};

export function sanitizeArrowKeyMoveStep(
  value: number | string | null | undefined,
  fallback = DEFAULT_ARROW_KEY_MOVE_STEP,
): number {
  const fallbackValue = Number.isFinite(fallback)
    ? Math.min(MAX_ARROW_KEY_MOVE_STEP, Math.max(MIN_ARROW_KEY_MOVE_STEP, Math.round(fallback)))
    : DEFAULT_ARROW_KEY_MOVE_STEP;
  if (value === null || value === undefined) return fallbackValue;
  if (typeof value === 'string' && value.trim().length === 0) return fallbackValue;

  const numericValue =
    typeof value === 'string'
      ? Number(value.trim())
      : value;

  if (!Number.isFinite(numericValue)) return fallbackValue;
  return Math.min(
    MAX_ARROW_KEY_MOVE_STEP,
    Math.max(MIN_ARROW_KEY_MOVE_STEP, Math.round(numericValue)),
  );
}

export function getFieldNudgeCommandFromKey(
  input: FieldNudgeShortcutInput,
): FieldNudgeCommand | null {
  const direction = FIELD_NUDGE_DIRECTIONS[input.key.toLowerCase()];
  if (!direction) return null;
  if (input.ctrlKey || input.metaKey) return null;

  if (input.altKey) {
    return {
      ...direction,
      step: input.shiftKey ? 10 : 1,
    };
  }

  if (!input.arrowKeyMoveEnabled) return null;

  return {
    ...direction,
    step: sanitizeArrowKeyMoveStep(input.arrowKeyMoveStep),
  };
}
