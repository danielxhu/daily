import type {
  Board,
  DailyDigest,
  KnowledgeModule,
  KnowledgeNote,
  PipelineRun,
  Subscription,
} from "@/types/contract";

// Deterministic offline fixtures for mock mode + the Playwright E2E suite
// (verification engine removed 2026-07-13 — tracking/knowledge surfaces only).

export function buildMockBoards(): Board[] {
  return [
    { id: "b_finance", name: "Finance", created_at: "2026-07-01T00:00:00+00:00" },
    { id: "b_politics", name: "政治", created_at: "2026-07-03T00:00:00+00:00" },
    { id: "b_economy", name: "经济", created_at: "2026-07-03T00:00:00+00:00" },
    { id: "b_tech", name: "科技", created_at: "2026-07-03T00:00:00+00:00" },
  ];
}

export function buildMockModules(boardId: string): KnowledgeModule[] {
  return [
    {
      id: "m_rates",
      board_id: boardId,
      name: "Rates",
      created_at: "2026-06-09T00:00:00+00:00",
    },
  ];
}

export function buildMockBoardNotes(boardId: string): KnowledgeNote[] {
  return [
    {
      id: "n_user_1",
      board_id: boardId,
      kind: "user_note",
      content: "watch the comment deadline",
      citations: [],
      is_synthesized: false,
      regenerable: false,
      created_at: "2026-07-06T00:00:00+00:00",
    },
  ];
}

export function buildMockSubscriptions(): Subscription[] {
  return [
    {
      id: "sub_fed",
      board_id: "b_finance",
      module_id: null,
      input_url: "https://www.federalreserve.gov/feeds/press_all.xml",
      feed_url: "https://www.federalreserve.gov/feeds/press_all.xml",
      mode: "direct",
      interval_minutes: 60,
      last_polled: "2026-06-09T08:00:00+00:00",
      last_seen_item_key_for_display: "fed-1",
      consecutive_failures: 0,
      health: "ok",
      last_error: null,
      subscription_failure_kind: null,
    },
    {
      id: "sub_pod",
      board_id: null,
      module_id: null,
      input_url: "https://podcasts.example.com/markets-daily/feed",
      feed_url: "https://podcasts.example.com/markets-daily/feed",
      mode: "homepage_diff",
      interval_minutes: 60,
      last_polled: "2026-06-09T06:00:00+00:00",
      last_seen_item_key_for_display: null,
      consecutive_failures: 2,
      health: "unhealthy",
      last_error: "404 Not Found",
      subscription_failure_kind: "gone",
    },
  ];
}

export function buildMockDigest(boardId?: string): DailyDigest {
  const tracked: DailyDigest["tracked"] = [
    {
      id: "ti_sec",
      board_id: "b_economy",
      module_id: "m_rates",
      url: "https://www.sec.gov/news/press-release/2026-99",
      title: "SEC statement on market-structure rulemaking",
      domain: "sec.gov",
      tier: "T1",
      published: "2026-06-09T07:30:00+00:00",
      first_seen: "2026-06-09T07:45:00+00:00",
      status: "fetched",
      failure_kind: null,
      degraded_reason: null,
      // DEPRECATED legacy single-language line — the UI must NEVER render it;
      // it stays in the fixture as the canary for that rule
      summary: "LEGACY-ONLY: must never render.",
      enrichment: {
        title_zh: "SEC 就市场结构规则制定发表声明",
        title_en: "SEC statement on market-structure rulemaking",
        summary_zh: "来源称其市场结构规则制定进入公众评议期。",
        summary_en: "The source says its market-structure rulemaking enters a comment period.",
        why_zh: "与市场结构监管追踪相关。",
        why_en: "Relevant if you track market-structure regulation.",
        entities: ["SEC"],
        tags: ["policy", "market-structure"],
        limitations_zh: "仅基于正文节选。",
        limitations_en: "Based on an excerpt only.",
      },
      content_available: true,
      similar_count: 0,
    },
    {
      id: "ti_pod",
      board_id: null,
      module_id: null,
      url: "https://podcasts.example.com/markets-daily/ep-214",
      title: "Markets Daily — episode 214",
      domain: "podcasts.example.com",
      tier: "T2",
      published: null,
      first_seen: "2026-06-09T07:50:00+00:00",
      status: "fetched",
      failure_kind: null,
      degraded_reason: "summary generation failed — the background worker retries",
      summary: null,
      enrichment: null,
      content_available: false,
      similar_count: 0,
    },
  ];
  const boardTracked: DailyDigest["tracked"] = boardId
    ? [
        {
          id: "ti_board",
          board_id: boardId,
          module_id: null,
          url: "https://www.sec.gov/news/board-item",
          title: "Board-scoped tracked item",
          domain: "sec.gov",
          tier: "T1",
          published: null,
          first_seen: "2026-06-09T07:40:00+00:00",
          status: "fetched",
          failure_kind: null,
          degraded_reason: null,
          summary: "LEGACY-ONLY: must never render.",
          enrichment: {
            title_zh: "板块相关更新",
            title_en: "Board-scoped tracked item",
            summary_zh: "来源称一条板块相关更新已发布。",
            summary_en: "The source says a board-scoped update landed.",
            why_zh: null,
            why_en: null,
            entities: [],
            tags: ["board"],
            limitations_zh: null,
            limitations_en: null,
          },
          content_available: true,
          similar_count: 0,
        },
      ]
    : [];
  return {
    date: "2026-06-09",
    generated_at: "2026-06-09T08:00:00+00:00",
    tracked: boardId ? boardTracked : tracked,
  };
}

export function buildMockRuns(): PipelineRun[] {
  return [
    {
      id: "run_poll_1",
      inputs: [],
      trigger: "poll",
      started_at: "2026-06-09T08:00:00+00:00",
      finished_at: "2026-06-09T08:00:40+00:00",
      prompt_version: "2026-06-22.v1",
      steps: [
        {
          step: "ingestion",
          status: "ok",
          fallback_used: null,
          counts: { new_items: 2, items_ok: 2 },
          error: null,
        },
        {
          step: "digest",
          status: "ok",
          fallback_used: null,
          counts: { item_summaries: 2 },
          error: null,
        },
      ],
    },
    {
      id: "run_poll_2",
      inputs: [],
      trigger: "poll",
      started_at: "2026-06-09T09:00:00+00:00",
      finished_at: "2026-06-09T09:00:10+00:00",
      prompt_version: "2026-06-22.v1",
      steps: [
        {
          step: "ingestion",
          status: "failed",
          fallback_used: "anti_bot",
          counts: { new_items: 3, items_ok: 0, items_failed: 3 },
          error: "3/3 new items failed ingestion: anti_bot ×3",
        },
      ],
    },
  ];
}
