// Detail-page ids pre-rendered by a static export (the GitHub Pages build,
// `output: "export"`), which can only serve paths it generated at build time.
// A static-data build takes them from the exported snapshot
// (public/data/_static-params.json, written by the backend's app/static_site.py);
// otherwise they mirror the mock fixtures (src/mocks/fixtures.ts, handlers.ts).
// A normal server build still renders any other id on demand.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

type NoteParams = { boardId: string; noteId: string };

const MOCK_ITEM_IDS = ["ti_sec", "ti_pod", "ti_board"];
const MOCK_BOARD_IDS = ["b_finance", "b_politics", "b_economy", "b_tech"];
const MOCK_NOTE_IDS = ["n_user_1", "n_kb_1", "n_kb_2", "n_new", "n_saved_1", "n_distilled_1"];
const MOCK_NOTE_PARAMS = MOCK_BOARD_IDS.flatMap((boardId) =>
  MOCK_NOTE_IDS.map((noteId) => ({ boardId, noteId })),
);

function exported(): { items: string[]; notes: NoteParams[] } | null {
  if (process.env.NEXT_PUBLIC_STATIC_DATA !== "1") return null;
  const file = join(process.cwd(), "public", "data", "_static-params.json");
  if (!existsSync(file)) return null;
  return JSON.parse(readFileSync(file, "utf-8")) as { items: string[]; notes: NoteParams[] };
}

const snapshot = exported();

// an export needs at least one path per dynamic route; "_" renders the page's
// own not-found state
export const STATIC_ITEM_IDS = snapshot
  ? snapshot.items.length
    ? snapshot.items
    : ["_"]
  : MOCK_ITEM_IDS;

export const STATIC_NOTE_PARAMS: NoteParams[] = snapshot
  ? snapshot.notes.length
    ? snapshot.notes
    : [{ boardId: "_", noteId: "_" }]
  : MOCK_NOTE_PARAMS;
