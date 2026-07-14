// AUTO-GENERATED from backend/app/schemas/models.py (SSOT §7). DO NOT EDIT.
// Regenerate: `cd backend && python -m app.schemas.codegen`.

export type SourceType = "webpage" | "podcast" | "youtube" | "text" | "pdf";
export type Origin = "user" | "fetched";
export type CitationType = "primary" | "cited" | "republished";
export type Tier = "T1" | "T1.5" | "T2";
export type ExtractionMethod = "static_html" | "structured_html" | "rendered_html" | "pdf_text" | "caption" | "whisper" | "pasted_text" | "frame_ocr";
export type SourceFailureKind = "fetch_blocked" | "paywall" | "login_required" | "anti_bot" | "no_captions" | "transcribe_failed" | "js_render_failed" | "parse_empty" | "unsupported_file" | "timeout" | "transcription_deferred";
export type SubscriptionFailureKind = "gone" | "rate_limited" | "parse_or_render_unfit" | "network" | "system_anomaly" | "items_unfetchable";

export interface Source {
  id: string;
  type: SourceType;
  origin?: Origin;
  url: string | null;
  domain: string | null;
  raw_text: string;
  fetched_at: string;
  reputation_prior?: number;
  citation_type?: CitationType;
  tier?: Tier;
}

export interface Subscription {
  id: string;
  board_id?: string | null;
  module_id?: string | null;
  input_url: string;
  feed_url: string | null;
  mode: "direct" | "autodiscover" | "platform" | "homepage_diff";
  interval_minutes?: number;
  last_polled: string | null;
  last_seen_item_key_for_display: string | null;
  consecutive_failures?: number;
  health?: "ok" | "unhealthy";
  last_error?: string | null;
  subscription_failure_kind?: SubscriptionFailureKind | null;
}

export interface SeenItem {
  subscription_id: string;
  item_key: string;
  first_seen: string;
}

export interface SourcePackEntry {
  label: string;
  url: string;
  mode: "direct" | "autodiscover" | "platform" | "homepage_diff";
  category: "central_bank" | "regulator" | "company_ir" | "rss" | "youtube";
  board_id?: string | null;
}

export interface Segment {
  text: string;
  start_ts: number | null;
  end_ts: number | null;
  words?: Record<string, unknown>[];
}

export interface FrameAnnotation {
  source_id: string;
  timestamp: number;
  anchor_text: string;
  vision_description: string;
  image_path: string;
}

export interface NormalizedSource {
  source_id: string;
  type: SourceType;
  origin?: Origin;
  url: string | null;
  domain: string | null;
  raw_text: string;
  extraction_method?: ExtractionMethod | null;
  segments: Segment[];
  frame_annotations: FrameAnnotation[];
  citation_type?: CitationType;
  tier?: Tier;
}

export interface SourceRequest {
  kind: "url" | "text";
  url?: string | null;
  text?: string | null;
  source_label?: string | null;
  declared_domain?: string | null;
  declared_type?: SourceType | null;
}

export interface SourceFailure {
  requested_url: string | null;
  type: SourceType | null;
  kind: SourceFailureKind;
  next_action?: string | null;
  reason: string;
}

export interface IngestionResult {
  requested: SourceRequest;
  status: "ok" | "failed";
  source: NormalizedSource | null;
  failure: SourceFailure | null;
}

export interface Board {
  id: string;
  name: string;
  created_at: string;
}

export interface KnowledgeModule {
  id: string;
  board_id: string;
  name: string;
  created_at: string;
}

export interface KnowledgeNote {
  id: string;
  board_id: string;
  kind: "pinned_fact" | "user_note" | "ai_distilled" | "saved_check";
  content: string;
  citations?: string[];
  is_synthesized?: boolean;
  regenerable?: boolean;
  created_at: string;
}

export interface TrackedItemDetail {
  item: TrackedItemCard;
  excerpt_preview: string | null;
  fetch_method: string | null;
  related?: TrackedItemCard[];
}

export interface ItemEnrichment {
  summary_zh: string;
  summary_en: string;
  title_zh?: string | null;
  title_en?: string | null;
  why_zh?: string | null;
  why_en?: string | null;
  entities?: string[];
  tags?: string[];
  limitations_zh?: string | null;
  limitations_en?: string | null;
}

export interface TrackedItemCard {
  id: string;
  board_id: string | null;
  module_id?: string | null;
  url: string | null;
  title: string | null;
  domain: string | null;
  tier: Tier | null;
  published: string | null;
  first_seen: string;
  status: "new" | "fetched" | "failed" | "deferred";
  failure_kind?: SourceFailureKind | null;
  degraded_reason?: string | null;
  summary?: string | null;
  enrichment?: ItemEnrichment | null;
  content_available?: boolean;
  similar_count?: number;
}

export interface DailyDigest {
  date: string;
  generated_at: string;
  tracked?: TrackedItemCard[];
}

export interface DiscussMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ItemDiscussRequest {
  messages: DiscussMessage[];
}

export interface ItemDiscussReply {
  reply: string;
}

export interface KnowledgeAnswer {
  answer: string | null;
  based_on: number;
}

export interface KnowledgeAnswerRequest {
  q: string;
}

export interface KnowledgeSearchResult {
  saved: KnowledgeNote[];
  items?: TrackedItemCard[];
}

export interface StepTrace {
  step: "ingestion" | "vision" | "extraction" | "alignment" | "retrieval" | "verification" | "scoring" | "memory" | "digest";
  status: "ok" | "skipped" | "failed";
  fallback_used?: string | null;
  counts?: Record<string, unknown>;
  error?: string | null;
  duration_ms?: number | null;
}

export interface PipelineRun {
  id: string;
  trigger: "verify" | "poll" | "digest";
  inputs: SourceRequest[];
  steps: StepTrace[];
  prompt_version?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export interface UsageEvent {
  type: "digest_open" | "evidence_click" | "verdict_save" | "verdict_share" | "helped_judge";
  ref?: string | null;
  user?: string | null;
  created_at: string;
}

export interface TraceSummary {
  run_id: string;
  steps: StepTrace[];
}
