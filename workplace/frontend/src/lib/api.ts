import type {
  Board,
  DailyDigest,
  DiscussMessage,
  ItemDiscussReply,
  KnowledgeModule,
  KnowledgeNote,
  KnowledgeAnswer,
  KnowledgeSearchResult,
  PipelineRun,
  SourceFailureKind,
  SourcePackEntry,
  Subscription,
  SubscriptionFailureKind,
  TrackedItemCard,
  TrackedItemDetail,
} from "@/types/contract";

/** Thrown on a non-2xx /verify response; carries the HTTP status + server detail. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const DEFAULT_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Mock builds only: wait for the MSW worker before any request, so a mount-time
 * fetch can't race the worker and hit a nonexistent backend. No-op elsewhere
 * (NEXT_PUBLIC_API_MOCK is inlined at build time). */
async function waitForMock(): Promise<void> {
  if (process.env.NEXT_PUBLIC_API_MOCK !== "1" || typeof window === "undefined") return;
  await (await import("@/lib/msw-gate")).mswReady();
}

/** The HTTP URL the backend serves a vision frame's still at (M8.7 / FR-8):
 * `<base>/frames/<name>`. A `FrameAnnotation.image_path` (M8.2) is a local file path;
 * the UI fetches it by basename so a frame-derived stance can show the actual image.
 * An already-absolute URL is returned unchanged; an empty path yields "". */

interface VerifyOptions {
  signal?: AbortSignal;
  baseUrl?: string;
  fetchFn?: typeof fetch; // injectable so tests never hit the network
}


interface QueryOptions {
  signal?: AbortSignal;
  baseUrl?: string;
  fetchFn?: typeof fetch; // injectable so tests never hit the network
}

async function getJson<T>(path: string, opts: QueryOptions): Promise<T> {
  const fetchFn = opts.fetchFn ?? fetch;
  await waitForMock();
  const res = await fetchFn(`${opts.baseUrl ?? DEFAULT_BASE_URL}${path}`, {
    signal: opts.signal,
  });
  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}




async function postJson<T>(path: string, body: unknown, opts: QueryOptions): Promise<T> {
  const fetchFn = opts.fetchFn ?? fetch;
  await waitForMock();
  const res = await fetchFn(`${opts.baseUrl ?? DEFAULT_BASE_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: opts.signal,
  });
  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const errBody = await res.json();
      if (typeof errBody?.detail === "string") detail = errBody.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// --- boards + knowledge layer (FR-15) ---

export async function queryBoards(opts: QueryOptions = {}): Promise<Board[]> {
  return getJson<Board[]>("/boards", opts);
}

export async function createBoard(name: string, opts: QueryOptions = {}): Promise<Board> {
  return postJson<Board>("/boards", { name }, opts);
}

/** Delete a topic board (M14.2): removes the board's grouping and its notes —
 * the shared fact layer is never affected (facts are tagged, not owned). */
export async function deleteBoard(boardId: string, opts: QueryOptions = {}): Promise<void> {
  return deleteRequest(`/boards/${boardId}`, opts);
}


/** The item detail payload (M16.4): card + "Source says" excerpt preview +
 * fetch-method provenance + related hints. Read-only, zero LLM. */
export async function getTrackedItem(
  itemId: string,
  opts: QueryOptions = {},
): Promise<TrackedItemDetail> {
  return getJson<TrackedItemDetail>(`/tracked-items/${itemId}`, opts);
}

/** Manual fetch-&-summarize (M16.4): how a legacy item gets its bilingual
 * summary and discussion grounding. NOT a deep check — no claims, no scoring. */
export async function refreshTrackedItem(
  itemId: string,
  opts: QueryOptions = {},
): Promise<TrackedItemDetail> {
  return postJson<TrackedItemDetail>(`/tracked-items/${itemId}/refresh`, {}, opts);
}

/** Discuss ONE tracked item (M16.5, NFR-7 exception (4)): the backend grounds
 * replies ONLY in the item's stored excerpt + AI summary and answers 证据不足
 * beyond them — source-attributed tone, never a truth call. READ-ONLY. */
export async function discussTrackedItem(
  itemId: string,
  messages: DiscussMessage[],
  opts: QueryOptions = {},
): Promise<ItemDiscussReply> {
  return postJson<ItemDiscussReply>(`/tracked-items/${itemId}/discuss`, { messages }, opts);
}

// --- knowledge modules (M15.1/M15.3): board → module → source → item ---

export async function queryModules(
  boardId: string,
  opts: QueryOptions = {},
): Promise<KnowledgeModule[]> {
  return getJson<KnowledgeModule[]>(`/boards/${boardId}/modules`, opts);
}

export async function createModule(
  boardId: string,
  name: string,
  opts: QueryOptions = {},
): Promise<KnowledgeModule> {
  return postJson<KnowledgeModule>(`/boards/${boardId}/modules`, { name }, opts);
}

/** Delete a module: only the grouping goes — its sources, items, facts, and
 * notes all stay (they fall back to ungrouped). */
export async function deleteModule(moduleId: string, opts: QueryOptions = {}): Promise<void> {
  return deleteRequest(`/modules/${moduleId}`, opts);
}

/** Assign a source to a module in its board (null un-groups). Items inherit the
 * module at discovery, so future items land in the right place. */
export async function assignSubscriptionModule(
  subscriptionId: string,
  moduleId: string | null,
  opts: QueryOptions = {},
): Promise<Subscription> {
  const fetchFn = opts.fetchFn ?? fetch;
  await waitForMock();
  const res = await fetchFn(
    `${opts.baseUrl ?? DEFAULT_BASE_URL}/subscriptions/${subscriptionId}/module`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ module_id: moduleId }),
      signal: opts.signal,
    },
  );
  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const errBody = await res.json();
      if (typeof errBody?.detail === "string") detail = errBody.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as Subscription;
}


export async function queryBoardNotes(
  boardId: string,
  opts: QueryOptions = {},
): Promise<KnowledgeNote[]> {
  return getJson<KnowledgeNote[]>(`/boards/${boardId}/notes`, opts);
}

interface NoteInput {
  // saved_check (M13.2): the user-curated text of a /verify result — no citations
  // (the underlying result is not in the fact layer)
  kind: "pinned_fact" | "user_note" | "saved_check";
  content: string;
  citations?: string[];
}

export async function createNote(
  boardId: string,
  note: NoteInput,
  opts: QueryOptions = {},
): Promise<KnowledgeNote> {
  return postJson<KnowledgeNote>(`/boards/${boardId}/notes`, note, opts);
}

/** Regenerate the board's AI-distilled summary (FR-15 / M6.4-5). */

/** The built-in editable default source-pack template (FR-3 / M6.7) — seed
 * sources to trim/edit on cold start. Static; never topic-wide web discovery. */
export async function querySourcePack(opts: QueryOptions = {}): Promise<SourcePackEntry[]> {
  return getJson<SourcePackEntry[]>("/source-pack", opts);
}

/** Day-1 auto-fill (M14.1): adopt the whole STATIC starter pack as subscriptions,
 * once ever per database — the backend flag (not the subscription count) gates it,
 * so a deliberately emptied source list is never refilled. `seeded` false = the
 * no-op (keep the empty state; the user chose it). */
export interface AdoptResult {
  seeded: boolean;
  subscriptions: Subscription[];
}

export async function adoptSourcePack(opts: QueryOptions = {}): Promise<AdoptResult> {
  return postJson<AdoptResult>("/source-pack/adopt", {}, opts);
}

async function deleteRequest(path: string, opts: QueryOptions): Promise<void> {
  const fetchFn = opts.fetchFn ?? fetch;
  await waitForMock();
  const res = await fetchFn(`${opts.baseUrl ?? DEFAULT_BASE_URL}${path}`, {
    method: "DELETE",
    signal: opts.signal,
  });
  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON / empty (204) error body — keep the generic message
    }
    throw new ApiError(res.status, detail);
  }
}

// --- tracking subscriptions (FR-3) ---

export async function querySubscriptions(
  opts: QueryOptions & { boardId?: string } = {},
): Promise<Subscription[]> {
  const params = new URLSearchParams();
  if (opts.boardId != null) params.set("board_id", opts.boardId);
  const query = params.toString();
  return getJson<Subscription[]>(`/subscriptions${query ? `?${query}` : ""}`, opts);
}

interface SubscriptionInput {
  input_url: string;
  mode: Subscription["mode"];
  board_id?: string | null;
  feed_url?: string | null;
  interval_minutes?: number;
}

export async function createSubscription(
  sub: SubscriptionInput,
  opts: QueryOptions = {},
): Promise<Subscription> {
  return postJson<Subscription>("/subscriptions", sub, opts);
}

export async function deleteSubscription(id: string, opts: QueryOptions = {}): Promise<void> {
  return deleteRequest(`/subscriptions/${id}`, opts);
}

/** One new item that failed ingestion during a poll (M13.1) — the tracked-path
 * analogue of /verify's typed per-source failure. Mirrors backend PollItemFailure. */
export interface PollItemFailure {
  url: string | null;
  kind: SourceFailureKind;
  next_action?: string | null;
}

/** One subscription's outcome within a manual poll. Mirrors backend
 * app/tracking/runtime.py PollSubReport — a runtime API response, not a §7 contract
 * type (so it isn't in the auto-generated contract.ts, like the request bodies). */
export interface PollSubReport {
  subscription_id: string;
  input_url: string;
  ok: boolean;
  new_items: number;
  // M13.1: per-item outcomes — a feed can poll fine while every article fails
  items_ok?: number;
  items_failed?: number;
  item_failures?: PollItemFailure[];
  // M13.4: older items skipped for good on a FIRST check (capped to the latest few)
  backlog_skipped?: number;
  // M14.5: audio/video items a FIRST check deferred (transcription skipped, item
  // re-queued for the next check) — delayed processing, not failures
  items_deferred?: number;
  failure_kind?: SubscriptionFailureKind | null;
  next_action?: string | null;
  error?: string | null;
}

/** The manual poll's useful counts + per-subscription errors. */
export interface PollReport {
  run_id: string;
  polled: number;
  new_items: number;
  system_anomaly: boolean;
  subscriptions: PollSubReport[];
}

/** Poll every subscription now (FR-3 / §6.2): each new item runs through the same
 * ingestion + extraction pipeline and into the rolling window, so corroborated
 * tracked facts graduate to memory + the digest. The in-process scheduler runs this
 * same poll on each source's interval while the machine is on; this is the manual
 * trigger (always available). One bad source never blocks the others (§6.6). */
export async function pollNow(opts: QueryOptions = {}): Promise<PollReport> {
  return postJson<PollReport>("/tracking/poll", {}, opts);
}

// --- daily digest (FR-13) ---

/** The source tracking digest over the recent view window (FR-13 / M14.6: default 30
 * days server-side, user-adjustable): verification-annotated, ordered items
 * (verdict-changed pinned, then reverse-chron). Optionally board-filtered. */
export async function queryDigest(
  opts: QueryOptions & { boardId?: string; windowDays?: number } = {},
): Promise<DailyDigest> {
  const params = new URLSearchParams();
  if (opts.boardId != null) params.set("board_id", opts.boardId);
  if (opts.windowDays != null) params.set("window_days", String(opts.windowDays));
  const query = params.toString();
  return getJson<DailyDigest>(`/api/digest${query ? `?${query}` : ""}`, opts);
}

// --- evidence-bounded discussion (M12.3) ---

/** Discuss ONE digest item within its verified evidence (M12.3 / NFR-7 4th bounded
 * exception). The backend grounds replies ONLY in the item's claims / sources /
 * score and answers 证据不足 beyond them; a discussion never writes the fact layer. */

/** Discuss a NOT-YET-SAVED /verify result within its evidence (M13.2): the evidence
 * rides inline (the result isn't in the fact layer), and the current save-note
 * `draft` goes along so the chat can propose an evidence-bounded revision. */

/** The Knowledge ask-surface search (M13.2): verified facts (semantic) AND the
 * user's saved_check notes (keyword), in separate labeled lists. */
export async function searchKnowledge(
  q: string,
  opts: QueryOptions = {},
): Promise<KnowledgeSearchResult> {
  const params = new URLSearchParams({ q });
  return getJson<KnowledgeSearchResult>(`/knowledge/search?${params.toString()}`, opts);
}

/** M16.2: the on-demand AI answer — ONE synthesis grounded only in the user's
 * saved notes matching the question. An explicit user action; search itself
 * never triggers it (that synchronous call was why search felt slow). */
export async function answerKnowledge(
  q: string,
  opts: QueryOptions = {},
): Promise<KnowledgeAnswer> {
  return postJson<KnowledgeAnswer>("/knowledge/answer", { q }, opts);
}

// --- run trace (§4/§7) ---

/** Recent verify/poll/digest runs (newest first), each with its ordered steps —
 * the debug trace so a half-failed run is inspectable. Read-only. */
export async function queryRuns(
  opts: QueryOptions & { limit?: number } = {},
): Promise<PipelineRun[]> {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const query = params.toString();
  return getJson<PipelineRun[]>(`/api/runs${query ? `?${query}` : ""}`, opts);
}
