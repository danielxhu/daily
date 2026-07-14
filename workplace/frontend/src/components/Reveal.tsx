"use client";

import { useEffect, useRef, type ReactNode } from "react";

// L2 staggered entrance (DESIGN.md Rev 3 §7): children start slightly lowered and
// transparent, then settle in shortly after mount (stagger via --reveal-i). Mount-
// based rather than IntersectionObserver-based on purpose: the dashboard is short,
// and full-page screenshots (review evidence) never scroll, so viewport-triggered
// reveals would leave below-the-fold sections invisible. prefers-reduced-motion
// neutralizes the .reveal rules in CSS, so content is always visible without JS.
export function Reveal({ index = 0, children }: { index?: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // double rAF so the initial (hidden) styles are committed before transitioning
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => el.classList.add("revealed"));
    });
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      ref={ref}
      className="reveal"
      style={{ ["--reveal-i" as string]: Math.min(index, 5) }}
    >
      {children}
    </div>
  );
}
