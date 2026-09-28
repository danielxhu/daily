// Detail-page ids pre-rendered by a static export (the GitHub Pages mock demo,
// `output: "export"`), which can only serve paths it generated at build time.
// They mirror the mock fixtures (src/mocks/fixtures.ts, handlers.ts); a normal
// server build still renders any other id on demand.

export const STATIC_ITEM_IDS = ["ti_sec", "ti_pod", "ti_board"];

const STATIC_BOARD_IDS = ["b_finance", "b_politics", "b_economy", "b_tech"];
const STATIC_NOTE_IDS = ["n_user_1", "n_kb_1", "n_kb_2", "n_new", "n_saved_1", "n_distilled_1"];

export const STATIC_NOTE_PARAMS = STATIC_BOARD_IDS.flatMap((boardId) =>
  STATIC_NOTE_IDS.map((noteId) => ({ boardId, noteId })),
);
