// Static-data mode (NEXT_PUBLIC_STATIC_DATA=1): the GitHub Pages build, where
// there is no backend. A scheduled job runs the real pipeline and freezes every
// read endpoint to a JSON file (backend `app/static_site.py`); this module is
// the `fetch` the API client uses instead of the network. Reads map to those
// files, knowledge search runs over an exported corpus in the browser, and
// every write answers 405 — the page is a read-only snapshot.

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const STATIC_DATA = process.env.NEXT_PUBLIC_STATIC_DATA === "1";

export const READ_ONLY_DETAIL =
  "This is a read-only snapshot on GitHub Pages — run daily locally to add sources, notes, or questions.";

/** The frozen file for a GET `path?query`. Mirrors `data_file` in the backend's
 * `app/static_site.py` — change both together. */
export function dataFile(path: string, params?: URLSearchParams): string {
  let name = path.replace(/^\/+|\/+$/g, "");
  const entries = params ? [...params.entries()].sort(([a], [b]) => a.localeCompare(b)) : [];
  if (entries.length) name += "~" + entries.map(([k, v]) => `${k}-${v}`).join("~");
  return `${name}.json`;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function readData(path: string, params?: URLSearchParams): Promise<Response> {
  const res = await fetch(`${BASE_PATH}/data/${dataFile(path, params)}`);
  if (res.ok || !params || [...params.keys()].length === 0) return res;
  // a query combination the export didn't freeze: fall back to the unfiltered file
  return fetch(`${BASE_PATH}/data/${dataFile(path)}`);
}

async function search(q: string): Promise<Response> {
  const res = await fetch(`${BASE_PATH}/data/knowledge/search-corpus.json`);
  if (!res.ok) return res;
  const corpus = (await res.json()) as { saved: unknown[]; items: unknown[] };
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hit = (x: unknown) => {
    const text = JSON.stringify(x).toLowerCase();
    return terms.length > 0 && terms.every((t) => text.includes(t));
  };
  return json({ saved: corpus.saved.filter(hit), items: corpus.items.filter(hit) });
}

export const staticFetch: typeof fetch = async (input, init) => {
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET") return json({ detail: READ_ONLY_DETAIL }, 405);
  const url = new URL(String(input), "http://static.invalid");
  if (url.pathname === "/knowledge/search") return search(url.searchParams.get("q") ?? "");
  return readData(url.pathname, url.searchParams);
};
