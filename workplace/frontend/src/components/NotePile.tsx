"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useLocale, useT } from "@/lib/i18n";
import type { KnowledgeNote } from "@/types/contract";

/** Cursor-distance peek, from the macOS dock: the cards above the pointer slide up
 * and the ones below slide down, so a pointer resting between two of them parts
 * exactly those two. */
const PEEK_PX = 11;
const PEEK_RANGE = 170;

// the pile's geometry, owned here so the reserved height and the card sizes can
// never drift apart: the visible strip, an open card, the overlap, and the gap
// under an open card
const STRIP = 72;
const OPEN = 304;
const LAP = 16;
const GAP = 10;

function peekOffset(centerY: number, cursorY: number | null): number {
  if (cursorY === null) return 0;
  const d = centerY - cursorY;
  return Math.sign(d) * PEEK_PX * (1 - Math.min(1, Math.abs(d) / PEEK_RANGE));
}

/** A note's title and body in the active UI language, falling back to whatever
 * language it was written in. */
export function noteText(note: KnowledgeNote, locale: string): { title: string; body: string } {
  const title = (locale === "en" ? note.title_en : note.title_zh) ?? note.title ?? "";
  const body = (locale === "en" ? note.content_en : note.content_zh) ?? note.content;
  // an older note has no title: its opening line stands in for one
  return { title: title || body.split("\n")[0].slice(0, 60), body };
}

/** The saved notes as a pile of cards: only the top edge of each shows, the front
 * one is open, and hovering any card opens it in place. Cards can be picked, which
 * is what bounds an ask to them. */
export function NotePile({
  notes: newestFirst,
  picked,
  onPick,
  onRename,
}: {
  notes: KnowledgeNote[];
  picked: Set<string>;
  onPick: (id: string) => void;
  onRename: (note: KnowledgeNote, title: string) => Promise<void>;
}) {
  const { locale } = useLocale();
  const t = useT();
  // later cards sit in front, so the pile is built oldest-first: the newest note
  // ends up at the front, fully open, with older ones receding behind it
  const notes = [...newestFirst].reverse();
  const hostRef = useRef<HTMLDivElement>(null);
  const raf = useRef(0);
  // the front of the pile is open at rest, so the page always has something to read
  const restOpen = notes.length - 1;
  const [open, setOpen] = useState(restOpen);
  const [cursorY, setCursorY] = useState<number | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  useEffect(() => setOpen(notes.length - 1), [notes.length]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    host.querySelectorAll<HTMLElement>(".pcard").forEach((card, i) => {
      const box = card.getBoundingClientRect();
      const y = open === i || editing ? 0 : peekOffset(box.top + box.height / 2, cursorY);
      card.style.setProperty("--peek", `${y.toFixed(2)}px`);
    });
  }, [cursorY, open, editing, notes.length]);

  const onMove = (event: React.PointerEvent) => {
    const y = event.clientY;
    if (raf.current) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = 0;
      setCursorY(y);
    });
  };

  const startRename = (note: KnowledgeNote) => {
    setEditing(note.id);
    setDraftTitle(noteText(note, locale).title);
  };

  const commitRename = async (note: KnowledgeNote) => {
    const title = draftTitle.trim();
    setEditing(null);
    if (title && title !== noteText(note, locale).title) await onRename(note, title);
  };

  return (
    <div
      ref={hostRef}
      className="pile"
      style={
        {
          "--pile-n": notes.length,
          "--strip": `${STRIP}px`,
          "--open": `${OPEN}px`,
          "--lap": `${LAP}px`,
          "--gap": `${GAP}px`,
        } as CSSProperties
      }
      onPointerMove={onMove}
      onPointerLeave={() => {
        setCursorY(null);
        setOpen(restOpen);
      }}
    >
      {notes.map((note, i) => {
        const { title, body } = noteText(note, locale);
        const isOpen = open === i;
        return (
          <article
            key={note.id}
            className="pcard"
            data-open={isOpen ? "1" : "0"}
            tabIndex={0}
            onMouseEnter={() => setOpen(i)}
            onFocus={() => setOpen(i)}
          >
            <header className="spine">
              <input
                type="checkbox"
                checked={picked.has(note.id)}
                onChange={() => onPick(note.id)}
                onClick={(e) => e.stopPropagation()}
                aria-label={t("knowledge.notes.pick", { title })}
                className="shrink-0 accent-accent"
              />
              {editing === note.id ? (
                <input
                  autoFocus
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onBlur={() => void commitRename(note)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(note);
                    if (e.key === "Escape") setEditing(null);
                  }}
                  aria-label={t("knowledge.notes.rename.aria")}
                  className="input h-8 flex-1 py-1 text-[15px]"
                />
              ) : (
                <h3 className="serif min-w-0 flex-1 truncate text-[18px] tracking-[-0.013em]">
                  {title}
                </h3>
              )}
              {isOpen && editing !== note.id && (
                <button
                  type="button"
                  onClick={() => startRename(note)}
                  className="shrink-0 rounded border border-dashed border-line-strong px-1.5 text-[11px] text-faint transition-colors hover:border-accent hover:text-accent"
                >
                  {t("knowledge.notes.rename")}
                </button>
              )}
              <span className="mono shrink-0 text-[10.5px] text-faint">
                {note.created_at.slice(5, 10)}
              </span>
            </header>
            <div className="nbody">
              <hr />
              <div className="ntext">
                {body.split("\n").map((para, k) => para.trim() && <p key={k}>{para}</p>)}
              </div>
              <p className="nfrom">{t("knowledge.notes.honesty")}</p>
            </div>
          </article>
        );
      })}
    </div>
  );
}
