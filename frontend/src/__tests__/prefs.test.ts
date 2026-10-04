import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_SHEET_ALPHA, applyStoredSheetAlpha } from "@/lib/prefs";

describe("sheet opacity preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.style.removeProperty("--sheet-a");
  });

  it("falls back to the default when nothing is stored", () => {
    expect(applyStoredSheetAlpha()).toBe(DEFAULT_SHEET_ALPHA);
    expect(document.documentElement.style.getPropertyValue("--sheet-a")).toBe(
      String(DEFAULT_SHEET_ALPHA),
    );
  });

  it("keeps a stored value inside the range where body text stays readable", () => {
    // below 0.55 the field's brightest and darkest extremes push body text under
    // 4.5:1, so a hand-edited or stale value is pulled back to the floor
    window.localStorage.setItem("daily.sheetAlpha", "0.1");
    expect(applyStoredSheetAlpha()).toBe(0.55);

    window.localStorage.setItem("daily.sheetAlpha", "3");
    expect(applyStoredSheetAlpha()).toBe(1);

    window.localStorage.setItem("daily.sheetAlpha", "not-a-number");
    expect(applyStoredSheetAlpha()).toBe(DEFAULT_SHEET_ALPHA);
  });

  it("accepts a valid stored value", () => {
    window.localStorage.setItem("daily.sheetAlpha", "0.84");
    expect(applyStoredSheetAlpha()).toBe(0.84);
    expect(document.documentElement.style.getPropertyValue("--sheet-a")).toBe("0.84");
  });
});
