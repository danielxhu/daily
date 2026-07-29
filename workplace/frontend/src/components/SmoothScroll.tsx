"use client";

import { useEffect } from "react";

/** App-wide smooth scrolling, so moving through Today feels continuous with the
 * welcome page. Skipped entirely under prefers-reduced-motion, and it never
 * takes over scrolling — Lenis wraps the native scroll, keeping anchors,
 * position: sticky, and keyboard/screen-reader behaviour intact. */
export function SmoothScroll() {
  useEffect(() => {
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }
    let destroy: (() => void) | undefined;
    let cancelled = false;
    void (async () => {
      const { default: Lenis } = await import("lenis");
      if (cancelled) return;
      const lenis = new Lenis({ lerp: 0.12, autoRaf: true });
      destroy = () => lenis.destroy();
    })();
    return () => {
      cancelled = true;
      destroy?.();
    };
  }, []);
  return null;
}
