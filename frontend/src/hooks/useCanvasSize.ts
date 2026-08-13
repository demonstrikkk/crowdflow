import { useState, useEffect } from 'react';

/**
 * useCanvasSize — observes a container element via ResizeObserver and returns
 * its current pixel dimensions. Used by all Canvas 2D layers to keep their
 * `width` and `height` attributes in sync with the SVGVenueLayer pixel size.
 *
 * Satisfies Req 1 (AC 2, AC 5) and Req 17 (AC 5):
 *   - Canvas 2D layers are sized to match the container's rendered pixel dimensions
 *   - Resize response completes within one ResizeObserver callback cycle
 *
 * @param containerRef - ref to the container element being observed
 * @returns { width, height } in CSS pixels; defaults to 800 × 600 before first measurement
 */
export function useCanvasSize(
  containerRef: React.RefObject<Element | null>
): { width: number; height: number } {
  const [size, setSize] = useState<{ width: number; height: number }>({
    width: 800,
    height: 600,
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setSize({
          width: e.contentRect.width,
          height: e.contentRect.height,
        });
      }
    });

    ro.observe(el);

    return () => {
      ro.disconnect();
    };
  }, [containerRef]);

  return size;
}
