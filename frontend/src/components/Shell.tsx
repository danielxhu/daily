import type { ReactNode } from "react";

/** Responsive page container — centered, max-width, mobile-first padding. Sits
 * above the reading sheet, which AppFrame paints at the same width. `wide` is for
 * the card surfaces, where the timeline rail needs a margin of its own. */
export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div
      className={`relative z-10 mx-auto px-4 py-6 sm:px-6 ${wide ? "max-w-[64rem]" : "max-w-3xl"}`}
    >
      {children}
    </div>
  );
}
