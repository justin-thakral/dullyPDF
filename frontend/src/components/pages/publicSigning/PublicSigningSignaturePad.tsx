import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from 'react';

const CANVAS_WIDTH = 640;
const CANVAS_HEIGHT = 220;

type PublicSigningSignaturePadProps = {
  value: string | null;
  disabled?: boolean;
  onChange: (value: string | null) => void;
};

type CanvasPoint = {
  x: number;
  y: number;
};

function getCanvasContext(canvas: HTMLCanvasElement | null): CanvasRenderingContext2D | null {
  if (!canvas) {
    return null;
  }
  const context = canvas.getContext('2d');
  if (!context) {
    return null;
  }
  context.lineCap = 'round';
  context.lineJoin = 'round';
  context.lineWidth = 3;
  context.strokeStyle = '#0f172a';
  context.fillStyle = '#0f172a';
  return context;
}

function resetCanvas(canvas: HTMLCanvasElement | null): void {
  const context = getCanvasContext(canvas);
  if (!canvas || !context) {
    return;
  }
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, canvas.width, canvas.height);
}

function pointForEvent(canvas: HTMLCanvasElement, event: PointerEvent | ReactPointerEvent<HTMLCanvasElement>): CanvasPoint {
  const rect = canvas.getBoundingClientRect();
  const xScale = canvas.width / Math.max(rect.width, 1);
  const yScale = canvas.height / Math.max(rect.height, 1);
  return {
    x: (event.clientX - rect.left) * xScale,
    y: (event.clientY - rect.top) * yScale,
  };
}

export function PublicSigningSignaturePad({
  value,
  disabled = false,
  onChange,
}: PublicSigningSignaturePadProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<CanvasPoint | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    resetCanvas(canvas);
    if (!canvas || !value) {
      return;
    }
    const image = new Image();
    image.onload = () => {
      const context = getCanvasContext(canvas);
      if (!context) {
        return;
      }
      resetCanvas(canvas);
      const padding = 12;
      const availableWidth = canvas.width - padding * 2;
      const availableHeight = canvas.height - padding * 2;
      const widthScale = availableWidth / Math.max(image.width, 1);
      const heightScale = availableHeight / Math.max(image.height, 1);
      const scale = Math.min(widthScale, heightScale);
      const drawWidth = image.width * scale;
      const drawHeight = image.height * scale;
      const left = padding + Math.max((availableWidth - drawWidth) / 2, 0);
      const top = padding + Math.max((availableHeight - drawHeight) / 2, 0);
      context.drawImage(image, left, top, drawWidth, drawHeight);
    };
    image.src = value;
  }, [value]);

  function commitCanvasValue() {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    onChange(canvas.toDataURL('image/png'));
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (disabled || !canvasRef.current) {
      return;
    }
    const canvas = canvasRef.current;
    const context = getCanvasContext(canvas);
    if (!context) {
      return;
    }
    drawingRef.current = true;
    lastPointRef.current = pointForEvent(canvas, event);
    canvas.setPointerCapture(event.pointerId);
    context.beginPath();
    context.arc(lastPointRef.current.x, lastPointRef.current.y, 1.4, 0, Math.PI * 2);
    context.fill();
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current || disabled || !canvasRef.current) {
      return;
    }
    const canvas = canvasRef.current;
    const context = getCanvasContext(canvas);
    const previousPoint = lastPointRef.current;
    if (!context || !previousPoint) {
      return;
    }
    const nextPoint = pointForEvent(canvas, event);
    context.beginPath();
    context.moveTo(previousPoint.x, previousPoint.y);
    context.lineTo(nextPoint.x, nextPoint.y);
    context.stroke();
    lastPointRef.current = nextPoint;
  }

  function finishStroke(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current || !canvasRef.current) {
      return;
    }
    drawingRef.current = false;
    lastPointRef.current = null;
    if (canvasRef.current.hasPointerCapture(event.pointerId)) {
      canvasRef.current.releasePointerCapture(event.pointerId);
    }
    commitCanvasValue();
  }

  function handleClear() {
    resetCanvas(canvasRef.current);
    onChange(null);
  }

  return (
    <div className="public-signing-page__signature-pad-shell">
      <canvas
        ref={canvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        className="public-signing-page__signature-pad"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishStroke}
        onPointerLeave={finishStroke}
        onPointerCancel={finishStroke}
        aria-label="Draw signature"
      />
      <div className="public-signing-page__button-group public-signing-page__button-group--secondary">
        <button
          className="ui-button ui-button--ghost"
          type="button"
          disabled={disabled}
          onClick={handleClear}
        >
          Clear drawing
        </button>
      </div>
    </div>
  );
}
