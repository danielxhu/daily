import { NoteDetailView } from "@/components/NoteDetailView";
import { STATIC_NOTE_PARAMS } from "@/lib/static-params";

export function generateStaticParams() {
  return STATIC_NOTE_PARAMS;
}

export default function NotePage({ params }: { params: { boardId: string; noteId: string } }) {
  return (
    <section className="py-2">
      <NoteDetailView
        boardId={params.boardId}
        noteId={params.noteId}
      />
    </section>
  );
}
