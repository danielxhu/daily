import {
  buildMockBoardNotes,
  buildMockBoards,
  buildMockDigest,
  buildMockModules,
  buildMockRuns,
  buildMockSubscriptions,
} from "@/mocks/fixtures";
import { http, HttpResponse } from "msw";

import type { KnowledgeModule } from "@/types/contract";

// M15.3: stateful module lists (fresh per page load — the worker restarts)
const mockModules = new Map<string, KnowledgeModule[]>();

export const handlers = [
  http.get("*/source-pack", () => HttpResponse.json([])),
  // M14.1 Day-1 auto-fill: the mock env already has sources, so adopt reports the
  // deliberate no-op (seeded=false) and the UI keeps its normal states
  http.post("*/source-pack/adopt", () =>
    HttpResponse.json({ seeded: false, subscriptions: [] }),
  ),
  // boards + knowledge layer (FR-15)
  http.get("*/boards", () => HttpResponse.json(buildMockBoards())),
  http.post("*/boards", async ({ request }) => {
    const body = (await request.json()) as { name: string };
    return HttpResponse.json({
      id: `b_${body.name.toLowerCase()}`,
      name: body.name,
      created_at: "2026-06-10T00:00:00+00:00",
    });
  }),
  http.get("*/boards/:id/notes", ({ params }) =>
    HttpResponse.json(buildMockBoardNotes(params.id as string)),
  ),
  http.post("*/boards/:id/notes", async ({ params, request }) => {
    const body = (await request.json()) as {
      kind: string;
      content: string;
      citations?: string[];
    };
    return HttpResponse.json({
      id: "n_new",
      board_id: params.id,
      kind: body.kind,
      content: body.content,
      citations: body.citations ?? [],
      is_synthesized: false,
      regenerable: false,
      created_at: "2026-06-10T00:00:00+00:00",
    });
  }),
  // tracking subscriptions (FR-3)
  http.get("*/subscriptions", ({ request }) => {
    const boardId = new URL(request.url).searchParams.get("board_id");
    const subs = buildMockSubscriptions();
    return HttpResponse.json(
      boardId ? subs.filter((s) => s.board_id === boardId) : subs,
    );
  }),
  http.post("*/subscriptions", async ({ request }) => {
    const body = (await request.json()) as {
      input_url: string;
      mode: string;
      board_id?: string | null;
      name?: string | null;
      feed_url?: string | null;
      interval_minutes?: number;
    };
    return HttpResponse.json(
      {
        id: "sub_new",
        board_id: body.board_id ?? null,
        name: body.name ?? null,
        input_url: body.input_url,
        feed_url: body.feed_url ?? null,
        mode: body.mode,
        interval_minutes: body.interval_minutes ?? 60,
        last_polled: null,
        last_seen_item_key_for_display: null,
        consecutive_failures: 0,
        health: "ok",
        last_error: null,
        subscription_failure_kind: null,
      },
      { status: 201 },
    );
  }),
  // rename a source (2026-07-19): echo the renamed subscription back
  http.put("*/subscriptions/:id/name", async ({ params, request }) => {
    const body = (await request.json()) as { name?: string | null };
    const sub = buildMockSubscriptions().find((s) => s.id === params.id);
    if (!sub) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({ ...sub, name: body.name?.trim() || null });
  }),
  http.delete("*/boards/:id", () => new HttpResponse(null, { status: 204 })),
  http.delete(
    "*/subscriptions/:id",
    () => new HttpResponse(null, { status: 204 }),
  ),
  // manual poll (FR-3 / §6.2): new items run into memory; returns useful counts.
  // The Fed sub demonstrates M13.1 (beta P0-1): the feed polls fine but every
  // article page is bot-blocked — typed per-item failures, never a silent "ok".
  http.post("*/tracking/poll", () => {
    const subs = buildMockSubscriptions();
    return HttpResponse.json({
      run_id: "poll_mock",
      polled: subs.length,
      new_items: 3,
      system_anomaly: false,
      subscriptions: subs.map((s) =>
        s.id === "sub_fed"
          ? {
              subscription_id: s.id,
              input_url: s.input_url,
              ok: false,
              new_items: 3,
              items_ok: 1,
              items_failed: 2,
              backlog_skipped: 2, // M13.4: a first check picks up the latest only
              item_failures: [
                {
                  url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260706a.htm",
                  kind: "anti_bot",
                  next_action: "paste the text + a source label/domain",
                },
                {
                  url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260706b.htm",
                  kind: "anti_bot",
                  next_action: "paste the text + a source label/domain",
                },
              ],
              failure_kind: "items_unfetchable",
              next_action:
                "The feed works, but the articles themselves can't be fetched (anti-bot or paywall). Paste the article text on the Check page instead.",
              error: "2/3 new items failed ingestion: anti_bot ×2",
            }
          : {
              subscription_id: s.id,
              input_url: s.input_url,
              ok: s.health !== "unhealthy",
              new_items: 0,
              items_ok: 0,
              items_failed: 0,
              item_failures: [],
              backlog_skipped: 0,
              failure_kind: s.subscription_failure_kind ?? null,
              next_action: null,
              error: s.last_error ?? null,
            },
      ),
    });
  }),
  // M16.5: discuss ONE tracked item — grounded ONLY in its stored excerpt +
  // AI summary; the mock echoes a source-attributed reply, never a verdict.
  // Registered BEFORE the generic */discuss handler, which would swallow it.
  http.post("*/tracked-items/:id/discuss", async ({ params, request }) => {
    const tracked = buildMockDigest().tracked ?? [];
    const item = tracked.find((i) => i.id === params.id);
    if (!item) {
      return HttpResponse.json(
        { detail: `no such tracked item: ${String(params.id)}` },
        { status: 404 },
      );
    }
    if (!item.content_available) {
      return HttpResponse.json(
        {
          detail:
            "this item has no stored source text yet — run fetch-&-summarize (refresh) first",
        },
        { status: 400 },
      );
    }
    const { messages } = (await request.json()) as {
      messages: { content: string }[];
    };
    const question = messages[messages.length - 1]?.content ?? "";
    return HttpResponse.json({
      reply: `来源提到规则进入公开评议期;由此看,「${question}」可以从评议期的节奏与参与方式入手分析。`,
    });
  }),
  // 2026-07-13: the LLM-curated note draft — empty messages = initial draft,
  // otherwise the mock folds the user's latest instruction into a revision
  http.post("*/tracked-items/:id/note-draft", async ({ params, request }) => {
    const tracked = buildMockDigest().tracked ?? [];
    const item = tracked.find((i) => i.id === params.id);
    if (!item) {
      return HttpResponse.json(
        { detail: `no such tracked item: ${String(params.id)}` },
        { status: 404 },
      );
    }
    if (!item.content_available) {
      return HttpResponse.json(
        {
          detail:
            "this item has no stored source text yet — run fetch-&-summarize (refresh) first",
        },
        { status: 400 },
      );
    }
    const { messages } = (await request.json()) as {
      messages: { role: string; content: string }[];
    };
    const instruction = messages[messages.length - 1]?.content;
    return HttpResponse.json({
      draft: instruction
        ? `修订稿(按「${instruction}」):规则进入公开评议期,关注生效时间表。`
        : "要点:市场结构规则进入公开评议期;关注评议截止与生效时间表。",
    });
  }),
  // knowledge modules (M15.3): stateful within one page load so create/delete
  // flows are observable in mock mode and e2e
  http.get("*/boards/:boardId/modules", ({ params }) => {
    const boardId = String(params.boardId);
    if (!mockModules.has(boardId))
      mockModules.set(boardId, buildMockModules(boardId));
    return HttpResponse.json(mockModules.get(boardId));
  }),
  http.post("*/boards/:boardId/modules", async ({ params, request }) => {
    const boardId = String(params.boardId);
    const body = (await request.json()) as { name: string };
    const module = {
      id: `m_${body.name.toLowerCase().replace(/\s+/g, "_")}`,
      board_id: boardId,
      name: body.name,
      created_at: "2026-06-10T00:00:00+00:00",
    };
    if (!mockModules.has(boardId))
      mockModules.set(boardId, buildMockModules(boardId));
    mockModules.get(boardId)!.push(module);
    return HttpResponse.json(module, { status: 201 });
  }),
  http.delete("*/modules/:moduleId", ({ params }) => {
    for (const list of mockModules.values()) {
      const i = list.findIndex((m) => m.id === params.moduleId);
      if (i >= 0) list.splice(i, 1);
    }
    return new HttpResponse(null, { status: 204 });
  }),
  http.put("*/subscriptions/:subId/module", async ({ params, request }) => {
    const body = (await request.json()) as { module_id: string | null };
    const sub = buildMockSubscriptions().find((s) => s.id === params.subId);
    if (!sub) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({ ...sub, module_id: body.module_id });
  }),
  // Knowledge search (M16.2): deterministic keyword hits only — the dormant
  // fields mirror the real backend (facts always [], answer always None)
  http.get("*/knowledge/search", ({ request }) => {
    const q = new URL(request.url).searchParams.get("q") ?? "";
    return HttpResponse.json({
      answer: null,
      facts: [],
      saved: [
        {
          id: "n_saved_1",
          board_id: "b_economy",
          kind: "saved_check",
          content: `Saved check about "${q}": Fed approved the merger (federalreserve.gov).`,
          citations: [],
          is_synthesized: false,
          regenerable: false,
          created_at: "2026-07-06T00:00:00+00:00",
        },
      ],
      // M15.2: tracked items in their own labeled list — never in any answer
      items: (buildMockDigest().tracked ?? []).slice(0, 1),
      // M16.7: distilled board summaries — display-only regenerable AI cache
      distilled: [
        {
          id: "n_distilled_1",
          board_id: "b_economy",
          kind: "ai_distilled",
          content: `Board summary touching "${q}": rate policy and the merger dominated the week.`,
          citations: ["cl_1"],
          is_synthesized: true,
          regenerable: true,
          created_at: "2026-07-07T00:00:00+00:00",
        },
      ],
    });
  }),
  // M16.4: the item detail page — card + Source says + provenance + related
  http.get("*/tracked-items/:id", ({ params }) => {
    const tracked = buildMockDigest().tracked ?? [];
    const item = tracked.find((i) => i.id === params.id);
    if (!item) {
      return HttpResponse.json(
        { detail: `no such tracked item: ${String(params.id)}` },
        { status: 404 },
      );
    }
    return HttpResponse.json({
      item,
      excerpt_preview: item.content_available
        ? "The Securities and Exchange Commission today announced that its market-structure rulemaking enters a public comment period…"
        : null,
    });
  }),
  // M16.4: manual fetch-&-summarize — the mock upgrades the item in place
  http.post("*/tracked-items/:id/refresh", ({ params }) => {
    const tracked = buildMockDigest().tracked ?? [];
    const item = tracked.find((i) => i.id === params.id);
    if (!item) {
      return HttpResponse.json(
        { detail: `no such tracked item: ${String(params.id)}` },
        { status: 404 },
      );
    }
    const upgraded = {
      ...item,
      status: "fetched",
      degraded_reason: null,
      content_available: true,
      enrichment: item.enrichment ?? {
        summary_zh: "来源称本期节目讨论了市场走势。",
        summary_en: "The source says this episode discusses market trends.",
        why_zh: null,
        why_en: null,
        entities: [],
        tags: ["markets"],
        limitations_zh: null,
        limitations_en: null,
      },
    };
    return HttpResponse.json({
      item: upgraded,
      excerpt_preview:
        "Transcript excerpt: markets moved on the latest rate decision…",
    });
  }),
  // M16.2: the on-demand AI answer over the user's saved notes
  http.post("*/knowledge/answer", async ({ request }) => {
    const { q } = (await request.json()) as { q: string };
    return HttpResponse.json({
      answer: `Per your saved note about "${q}": the merger was approved (federalreserve.gov).`,
      based_on: 1,
    });
  }),
  // daily digest (FR-13)
  http.get("*/api/digest", ({ request }) => {
    const boardId = new URL(request.url).searchParams.get("board_id");
    return HttpResponse.json(buildMockDigest(boardId ?? undefined));
  }),
  // run trace (§4/§7)
  http.get("*/api/runs", () => HttpResponse.json(buildMockRuns())),
];
