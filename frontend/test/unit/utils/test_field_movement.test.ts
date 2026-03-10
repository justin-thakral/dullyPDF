import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ARROW_KEY_MOVE_STEP,
  MAX_ARROW_KEY_MOVE_STEP,
  MIN_ARROW_KEY_MOVE_STEP,
  getFieldNudgeCommandFromKey,
  sanitizeArrowKeyMoveStep,
} from '../../../src/utils/fieldMovement';

describe('fieldMovement', () => {
  it('sanitizes arrow key move step values', () => {
    expect(sanitizeArrowKeyMoveStep(undefined)).toBe(DEFAULT_ARROW_KEY_MOVE_STEP);
    expect(sanitizeArrowKeyMoveStep('')).toBe(DEFAULT_ARROW_KEY_MOVE_STEP);
    expect(sanitizeArrowKeyMoveStep(-8)).toBe(MIN_ARROW_KEY_MOVE_STEP);
    expect(sanitizeArrowKeyMoveStep('6.6')).toBe(7);
    expect(sanitizeArrowKeyMoveStep(999)).toBe(MAX_ARROW_KEY_MOVE_STEP);
  });

  it('returns plain arrow movement when keyboard move is enabled', () => {
    expect(
      getFieldNudgeCommandFromKey({
        key: 'ArrowLeft',
        altKey: false,
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        arrowKeyMoveEnabled: true,
        arrowKeyMoveStep: 5,
      }),
    ).toEqual({
      deltaX: -1,
      deltaY: 0,
      step: 5,
    });
  });

  it('preserves existing Alt+Arrow shortcuts', () => {
    expect(
      getFieldNudgeCommandFromKey({
        key: 'ArrowUp',
        altKey: true,
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        arrowKeyMoveEnabled: true,
        arrowKeyMoveStep: 9,
      }),
    ).toEqual({
      deltaX: 0,
      deltaY: -1,
      step: 1,
    });

    expect(
      getFieldNudgeCommandFromKey({
        key: 'ArrowDown',
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        arrowKeyMoveEnabled: true,
        arrowKeyMoveStep: 9,
      }),
    ).toEqual({
      deltaX: 0,
      deltaY: 1,
      step: 10,
    });
  });

  it('ignores unsupported keys and ctrl/cmd shortcuts', () => {
    expect(
      getFieldNudgeCommandFromKey({
        key: 'Enter',
        altKey: false,
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        arrowKeyMoveEnabled: true,
        arrowKeyMoveStep: 5,
      }),
    ).toBeNull();

    expect(
      getFieldNudgeCommandFromKey({
        key: 'ArrowRight',
        altKey: false,
        shiftKey: false,
        ctrlKey: true,
        metaKey: false,
        arrowKeyMoveEnabled: true,
        arrowKeyMoveStep: 5,
      }),
    ).toBeNull();
  });
});
