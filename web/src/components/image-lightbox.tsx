"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Download, X } from "lucide-react";

import { cn } from "@/lib/utils";

type LightboxImage = {
  id: string;
  src: string;
  sizeLabel?: string;
  dimensions?: string;
};

type ImageLightboxProps = {
  images: LightboxImage[];
  currentIndex: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onIndexChange: (index: number) => void;
};

type ImageTransform = {
  scale: number;
  x: number;
  y: number;
};

type TouchGesture =
  | {
      type: "swipe";
      startX: number;
      startY: number;
    }
  | {
      type: "pan";
      startX: number;
      startY: number;
      startTransform: ImageTransform;
    }
  | {
      type: "pinch";
      startDistance: number;
      startCenterX: number;
      startCenterY: number;
      startTransform: ImageTransform;
    };

const minScale = 1;
const maxScale = 4;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function getTouchDistance(touches: TouchList) {
  const first = touches[0];
  const second = touches[1];
  return Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY);
}

function getTouchCenter(touches: TouchList) {
  const first = touches[0];
  const second = touches[1];
  return {
    x: (first.clientX + second.clientX) / 2,
    y: (first.clientY + second.clientY) / 2,
  };
}

function normalizeTransform(transform: ImageTransform) {
  if (transform.scale <= minScale) {
    return { scale: minScale, x: 0, y: 0 };
  }

  const maxX = window.innerWidth * (transform.scale - 1) * 0.5;
  const maxY = window.innerHeight * (transform.scale - 1) * 0.5;
  return {
    scale: transform.scale,
    x: clamp(transform.x, -maxX, maxX),
    y: clamp(transform.y, -maxY, maxY),
  };
}

export function ImageLightbox({
  images,
  currentIndex,
  open,
  onOpenChange,
  onIndexChange,
}: ImageLightboxProps) {
  const gestureRef = useRef<TouchGesture | null>(null);
  const lastTapRef = useRef(0);
  const pendingTransformRef = useRef<ImageTransform | null>(null);
  const rafRef = useRef<number | null>(null);
  const [transform, setTransform] = useState<ImageTransform>({ scale: 1, x: 0, y: 0 });
  const [isGesturing, setIsGesturing] = useState(false);
  const current = images[currentIndex];
  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex < images.length - 1;

  const cancelScheduledTransform = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    pendingTransformRef.current = null;
  }, []);

  const scheduleTransform = useCallback((next: ImageTransform) => {
    pendingTransformRef.current = next;
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const pending = pendingTransformRef.current;
      pendingTransformRef.current = null;
      if (pending) {
        setTransform(pending);
      }
    });
  }, []);

  const flushScheduledTransform = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    const pending = pendingTransformRef.current;
    pendingTransformRef.current = null;
    if (pending) {
      setTransform(pending);
    }
  }, []);

  const resetTransform = useCallback(() => {
    cancelScheduledTransform();
    setTransform({ scale: 1, x: 0, y: 0 });
    setIsGesturing(false);
    gestureRef.current = null;
  }, [cancelScheduledTransform]);

  const goPrev = useCallback(() => {
    if (hasPrev) onIndexChange(currentIndex - 1);
  }, [hasPrev, currentIndex, onIndexChange]);

  const goNext = useCallback(() => {
    if (hasNext) onIndexChange(currentIndex + 1);
  }, [hasNext, currentIndex, onIndexChange]);

  useEffect(() => {
    resetTransform();
  }, [current?.id, open, resetTransform]);

  useEffect(() => {
    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goNext();
      } else if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, goPrev, goNext, onOpenChange]);

  const handleDownload = useCallback(() => {
    if (!current) return;
    const link = document.createElement("a");
    link.href = current.src;
    link.download = `image-${current.id}.png`;
    link.click();
  }, [current]);

  const toggleZoom = useCallback(() => {
    setTransform((currentTransform) =>
      currentTransform.scale > minScale ? { scale: 1, x: 0, y: 0 } : { scale: 2.5, x: 0, y: 0 },
    );
  }, []);

  const handleTouchStart = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      if (event.touches.length === 2) {
        event.preventDefault();
        const startDistance = getTouchDistance(event.touches);
        if (startDistance < 1) {
          gestureRef.current = null;
          return;
        }
        const center = getTouchCenter(event.touches);
        cancelScheduledTransform();
        setIsGesturing(true);
        gestureRef.current = {
          type: "pinch",
          startDistance,
          startCenterX: center.x,
          startCenterY: center.y,
          startTransform: transform,
        };
        return;
      }

      if (event.touches.length !== 1) {
        gestureRef.current = null;
        return;
      }

      const touch = event.touches[0];
      if (transform.scale > minScale) {
        cancelScheduledTransform();
        setIsGesturing(true);
        gestureRef.current = {
          type: "pan",
          startX: touch.clientX,
          startY: touch.clientY,
          startTransform: transform,
        };
      } else {
        gestureRef.current = {
          type: "swipe",
          startX: touch.clientX,
          startY: touch.clientY,
        };
      }
    },
    [transform, cancelScheduledTransform],
  );

  const handleTouchMove = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      const gesture = gestureRef.current;
      if (!gesture) return;

      if (gesture.type === "pinch" && event.touches.length === 2) {
        event.preventDefault();
        const targetScale = clamp(
          (getTouchDistance(event.touches) / gesture.startDistance) * gesture.startTransform.scale,
          minScale,
          maxScale,
        );
        const effectiveRatio = targetScale / gesture.startTransform.scale;
        const center = getTouchCenter(event.touches);
        const viewportCenterX = window.innerWidth / 2;
        const viewportCenterY = window.innerHeight / 2;
        const nextX =
          center.x -
          viewportCenterX -
          (gesture.startCenterX - viewportCenterX - gesture.startTransform.x) * effectiveRatio;
        const nextY =
          center.y -
          viewportCenterY -
          (gesture.startCenterY - viewportCenterY - gesture.startTransform.y) * effectiveRatio;
        scheduleTransform(
          normalizeTransform({ scale: targetScale, x: nextX, y: nextY }),
        );
        return;
      }

      if (gesture.type === "pan" && event.touches.length === 1) {
        event.preventDefault();
        const touch = event.touches[0];
        scheduleTransform(
          normalizeTransform({
            scale: gesture.startTransform.scale,
            x: gesture.startTransform.x + touch.clientX - gesture.startX,
            y: gesture.startTransform.y + touch.clientY - gesture.startY,
          }),
        );
        return;
      }

      if (event.touches.length !== 1) {
        gestureRef.current = null;
      }
    },
    [scheduleTransform],
  );

  const handleTouchEnd = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      flushScheduledTransform();
      setIsGesturing(false);

      const gesture = gestureRef.current;
      gestureRef.current = null;
      if (!gesture) return;

      if (gesture.type !== "swipe" || event.changedTouches.length !== 1) {
        return;
      }

      const touch = event.changedTouches[0];
      const deltaX = touch.clientX - gesture.startX;
      const deltaY = touch.clientY - gesture.startY;
      const now = Date.now();

      if (Math.abs(deltaX) < 10 && Math.abs(deltaY) < 10 && now - lastTapRef.current < 280) {
        event.preventDefault();
        lastTapRef.current = 0;
        toggleZoom();
        return;
      }
      lastTapRef.current = now;

      if (Math.abs(deltaX) < 48 || Math.abs(deltaX) < Math.abs(deltaY) * 1.4) {
        return;
      }

      if (deltaX > 0) {
        goPrev();
      } else {
        goNext();
      }
    },
    [goPrev, goNext, toggleZoom, flushScheduledTransform],
  );

  const handleTouchCancel = useCallback(() => {
    cancelScheduledTransform();
    setIsGesturing(false);
    gestureRef.current = null;
  }, [cancelScheduledTransform]);

  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!current || !open || !mounted) return null;

  return createPortal(
    <div 
      className="flex items-center justify-center outline-none bg-black/90 backdrop-blur-md"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 99999,
        margin: 0,
        padding: 0
      }}
    >
      <div className="absolute top-4 right-4 z-[999999] flex items-center gap-2">
        {current.sizeLabel || current.dimensions ? (
          <span className="rounded-full bg-black/50 px-3 py-1.5 text-xs font-medium text-white/90">
            {[current.sizeLabel, current.dimensions].filter(Boolean).join(" · ")}
          </span>
        ) : null}
        {images.length > 1 && (
          <span className="rounded-full bg-black/50 px-3 py-1.5 text-xs font-medium text-white/90">
            {currentIndex + 1} / {images.length}
          </span>
        )}
        <button
          type="button"
          onClick={handleDownload}
          className="inline-flex size-9 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70"
          aria-label="Tải ảnh"
        >
          <Download className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="inline-flex size-9 items-center justify-center rounded-full bg-black/50 text-white/90 transition hover:bg-black/70"
        >
          <X className="size-4" />
          <span className="sr-only">Đóng</span>
        </button>
      </div>

      {hasPrev && transform.scale <= minScale && (
        <button
          type="button"
          onClick={goPrev}
          className="absolute left-4 z-[110] inline-flex size-10 items-center justify-center rounded-full bg-black/40 text-white/90 transition hover:bg-black/60"
          aria-label="Ảnh trước"
        >
          <ChevronLeft className="size-5" />
        </button>
      )}

      <div
        className="flex h-full w-full touch-none items-center justify-center overflow-hidden"
        onClick={() => onOpenChange(false)}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchCancel}
      >
        <img
          src={current.src}
          alt=""
          className={cn(
            "max-h-[98vh] max-w-[98vw] rounded-lg object-contain will-change-transform",
            isGesturing ? "" : "transition-transform duration-150 ease-out",
            transform.scale > minScale ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in",
          )}
          style={{
            transform: `translate3d(${transform.x}px, ${transform.y}px, 0) scale(${transform.scale})`,
          }}
          onClick={(e) => {
            e.stopPropagation();
          }}
          onDoubleClick={(e) => {
            e.stopPropagation();
            toggleZoom();
          }}
          draggable={false}
        />
      </div>

      {hasNext && transform.scale <= minScale && (
        <button
          type="button"
          onClick={goNext}
          className="absolute right-4 z-[110] inline-flex size-10 items-center justify-center rounded-full bg-black/40 text-white/90 transition hover:bg-black/60"
          aria-label="Ảnh tiếp theo"
        >
          <ChevronRight className="size-5" />
        </button>
      )}
    </div>,
    document.body
  );
}
