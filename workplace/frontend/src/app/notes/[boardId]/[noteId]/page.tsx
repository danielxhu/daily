"use client";

import { useParams } from "next/navigation";

import { NoteDetailView } from "@/components/NoteDetailView";

export default function NotePage() {
  const params = useParams<{ boardId: string; noteId: string }>();
  const boardId = typeof params?.boardId === "string" ? params.boardId : "";
  const noteId = typeof params?.noteId === "string" ? params.noteId : "";
  return (
    <section className="py-2">
      <NoteDetailView boardId={boardId} noteId={noteId} />
    </section>
  );
}
