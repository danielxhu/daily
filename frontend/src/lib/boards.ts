// The three preset topic boards are seeded with Chinese names (backend
// migrations: b_politics 政治 / b_economy 经济 / b_tech 科技). Show them in the
// UI language; a board the user created or renamed keeps its own name.

const PRESET_NAMES: Record<string, string> = {
  b_politics: "政治",
  b_economy: "经济",
  b_tech: "科技",
};

export function boardName(
  board: { id: string; name: string },
  t: (key: string) => string,
): string {
  return PRESET_NAMES[board.id] === board.name
    ? t(`board.preset.${board.id}`)
    : board.name;
}
