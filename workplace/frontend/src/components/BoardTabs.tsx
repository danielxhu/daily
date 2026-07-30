"use client";

import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

/** The board filter: a segmented control whose pill slides to the active option.
 * The pill is measured from the button's own box so labels of any width fit. */
export function BoardTabs({
  aria,
  options,
  value,
  onChange,
}: {
  aria: string;
  options: { id: string | null; label: string }[];
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState({ x: 0, w: 0 });
  useLayoutEffect(() => {
    const active = ref.current?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (active) setPill({ x: active.offsetLeft - 4, w: active.offsetWidth });
  }, [value, options.length]);
  return (
    <div ref={ref} role="group" aria-label={aria} className="seg">
      <span
        aria-hidden="true"
        className="seg-pill"
        style={{ "--seg-x": `${pill.x}px`, "--seg-w": `${pill.w}px` } as CSSProperties}
      />
      {options.map((o) => (
        <button
          key={o.id ?? "all"}
          type="button"
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
