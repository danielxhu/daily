import { describe, expect, it } from "vitest";

import { boardName } from "@/lib/boards";

const t = (key: string) => ({ "board.preset.b_tech": "Tech" })[key] ?? key;

describe("boardName", () => {
  it("names a preset board in the UI language", () => {
    expect(boardName({ id: "b_tech", name: "科技" }, t)).toBe("Tech");
  });

  it("keeps a renamed preset or a user board as the user named it", () => {
    expect(boardName({ id: "b_tech", name: "AI 与芯片" }, t)).toBe("AI 与芯片");
    expect(boardName({ id: "b_mine", name: "Reading list" }, t)).toBe("Reading list");
  });
});
