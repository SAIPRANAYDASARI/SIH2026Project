/**
 * Shared API type contract — hand-maintained to mirror
 * `backend/app/schemas/*.py` field-for-field (see that module's docstring
 * for why this isn't codegen yet). Update both sides together.
 */

export interface HealthStatus {
  status: string;
  database: "ok" | "unreachable";
  redis: "ok" | "unreachable";
  app_env: "development" | "test" | "production";
  llm_backend: "ollama" | "hosted";
}

export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
}

/** F5: the audience persona toggle. Mirrors `app.models.conversation.Audience`. */
export type Audience = "industry" | "consumer";

/** Answer language toggle. Mirrors `app.api.v1.chat.SUPPORTED_LANGUAGES`. */
export type Language = "en" | "hi";

/** Mirrors `app.schemas.chat.ChatRequest`. POST /api/v1/chat body. */
export interface ChatRequest {
  conversation_id?: string | null;
  message: string;
  audience?: Audience | null;
  target_language?: Language | null;
}

/** Mirrors `app.schemas.chat.CitationSchema`. */
export interface Citation {
  marker: number;
  chunk_id: string;
  is_number: string | null;
  clause_number: string | null;
  document_title: string | null;
  document_source_url: string | null;
}

export type MessageRole = "user" | "assistant" | "system";

/** Mirrors `app.schemas.chat.MessageSchema`. GET /api/v1/conversations/{id}/messages. */
export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  intent: string | null;
  citations: Citation[] | null;
  model_backend: string | null;
  latency_ms: number | null;
  created_at: string;
}

/** Mirrors `app.schemas.chat.ConversationSchema`. GET /api/v1/conversations. */
export interface ConversationSummary {
  id: string;
  audience: Audience;
  title: string | null;
  created_at: string;
}

/**
 * Shapes of the three SSE event payloads streamed by POST /api/v1/chat
 * (see `app.api.v1.chat` module docstring for the event sequence). Not a
 * response body — parse each `event:`/`data:` block from the stream into
 * one of these by its event name.
 */
export interface ChatConversationEvent {
  conversation_id: string;
}

export interface ChatTokenEvent {
  text: string;
}

export interface ChatFinalEvent {
  message_id: string;
  conversation_id: string;
  citations: Citation[];
  invalid_citation_markers: number[];
  guardrail_violations: string[];
  intent: string;
  model_backend: string;
  latency_ms: number;
  forced_refusal: boolean;
  target_language: Language;
}

export interface ChatErrorEvent {
  detail: string;
}

/** Mirrors `app.schemas.analytics.IntentCount`/`AnalyticsSummary`.
 * GET /api/v1/analytics/summary — Step 11 officer dashboard. */
export interface IntentCount {
  intent: string;
  count: number;
}

export interface AnalyticsSummary {
  total_conversations: number;
  total_assistant_messages: number;
  intent_distribution: IntentCount[];
  guardrail_violation_count: number;
  forced_refusal_count: number;
  forced_refusal_rate: number;
  average_latency_ms: number | null;
  feedback_thumbs_up: number;
  feedback_thumbs_down: number;
  feedback_response_rate: number;
}

// --- Certification wizard (app.rules.wizard) — GET /certification/schemes,
// POST /certification/wizard. Stateless: the client resubmits the full
// answers object collected so far on every call. ---

export interface RuleFee {
  category: string;
  fee_inr: number;
  unit: string;
}

export interface RuleDocument {
  name: string;
  required: boolean;
  notes: string | null;
}

/** Mirrors `app.rules.schemas.SchemeRules`. */
export interface SchemeRules {
  code: string;
  name: string;
  description: string;
  product_keywords: string[];
  mandatory: boolean;
  fees: RuleFee[];
  timeline_days: number | null;
  validity_years: number | null;
  required_documents: RuleDocument[];
  source_note: string;
}

/** Mirrors `app.rules.wizard.WizardAnswers`. POST /certification/wizard body. */
export interface WizardAnswers {
  product_description?: string | null;
  manufactured_in_india?: boolean | null;
}

export interface WizardQuestion {
  field: string;
  prompt: string;
  input_type: "text" | "boolean";
}

export interface WizardResultScheme {
  scheme: SchemeRules;
  matched_keywords: string[];
}

/** Mirrors `app.rules.wizard.WizardResponse`. */
export interface WizardResponse {
  done: boolean;
  next_question: WizardQuestion | null;
  results: WizardResultScheme[];
  disclaimer: string | null;
}

// --- Licence verification (app.services.verification_service) —
// POST /verify. ---

export type LicenceType = "cml" | "crs_r" | "huid";
export type LicenceStatus = "active" | "expired" | "suspended" | "cancelled" | "not_found";

/** Mirrors `app.schemas.verification.VerifyRequest`. */
export interface VerifyRequest {
  licence_number: string;
  licence_type?: LicenceType | null;
}

/** Mirrors `app.schemas.verification.VerifyResult`. */
export interface VerifyResult {
  id: string;
  licence_number: string;
  licence_type: LicenceType;
  status: LicenceStatus;
  holder_name: string | null;
  is_number: string | null;
  product_category: string | null;
  valid_from: string | null;
  valid_until: string | null;
  is_seed_data: boolean;
}

/** Mirrors `app.schemas.verification.VerifyResponse`. */
export interface VerifyResponse {
  found: boolean;
  result: VerifyResult | null;
  message: string;
}

// --- Gap analysis (app.services.gap_analysis_service) —
// POST /analysis/gap-check. ---

/** Mirrors `app.schemas.verification.GapCheckRequest`. */
export interface GapCheckRequest {
  product_description: string;
  held_licence_numbers?: string[];
}

/** Mirrors `app.schemas.verification.MissingScheme`. */
export interface MissingScheme {
  code: string;
  name: string;
  mandatory: boolean;
  reason: string;
}

/** Mirrors `app.schemas.verification.GapCheckResponse`. */
export interface GapCheckResponse {
  matched_scheme_codes: string[];
  missing_mandatory: MissingScheme[];
  missing_voluntary: MissingScheme[];
  covered_scheme_codes: string[];
  disclaimer: string;
}
