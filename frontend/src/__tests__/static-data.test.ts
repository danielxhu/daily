import { afterEach, describe, expect, it, vi } from "vitest";

import { READ_ONLY_DETAIL, dataFile, staticFetch } from "@/lib/static-data";

afterEach(() => vi.unstubAllGlobals());

describe("dataFile", () => {
  it("matches the backend's app/static_site.data_file", () => {
    // same cases as backend tests/test_static_site.py
    expect(dataFile("/boards")).toBe("boards.json");
    expect(dataFile("/boards/b_tech/notes")).toBe("boards/b_tech/notes.json");
    expect(
      dataFile("/api/digest", new URLSearchParams({ window_days: "7", board_id: "b_tech" })),
    ).toBe("api/digest~board_id-b_tech~window_days-7.json");
  });
});

describe("staticFetch", () => {
  it("answers every write with a read-only 405", async () => {
    const res = await staticFetch("/subscriptions", { method: "POST", body: "{}" });
    expect(res.status).toBe(405);
    expect((await res.json()).detail).toBe(READ_ONLY_DETAIL);
  });

  it("reads the frozen file, falling back to the unfiltered one", async () => {
    const seen: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      seen.push(url);
      return url.endsWith("/data/api/digest.json")
        ? new Response(JSON.stringify({ tracked: [] }))
        : new Response("", { status: 404 });
    });
    const res = await staticFetch("/api/digest?window_days=14");
    expect(await res.json()).toEqual({ tracked: [] });
    expect(seen).toEqual(["/data/api/digest~window_days-14.json", "/data/api/digest.json"]);
  });

  it("searches the exported corpus in the browser", async () => {
    const corpus = {
      saved: [{ title: "Battery note" }, { title: "Rates note" }],
      items: [{ title: "Battery plant opens" }],
    };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(corpus)));
    const res = await staticFetch("/knowledge/search?q=battery");
    expect(await res.json()).toEqual({
      saved: [{ title: "Battery note" }],
      items: [{ title: "Battery plant opens" }],
    });
  });
});
