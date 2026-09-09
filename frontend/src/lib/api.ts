import type {
  AnalyticsSummary,
  ChatMessage,
  ChatRequest,
  ConversationSummary,
  GapCheckRequest,
  GapCheckResponse,
  HealthStatus,
  ProblemDetail,
  SchemeRules,
  VerifyRequest,
  VerifyResponse,
  WizardAnswers,
  WizardResponse,
} from "@/types/api";

/** Typed fetch wrapper over the backend's `/api/v1` surface. */
export class ApiError extends Error {
  constructor(public problem: ProblemDetail) {
    super(problem.detail ?? problem.title);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    const problem = (await response.json()) as ProblemDetail;
    throw new ApiError(problem);
  }

  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>("/health");
}

export function getAnalyticsSummary(): Promise<AnalyticsSummary> {
  return request<AnalyticsSummary>("/analytics/summary");
}

export function listConversations(): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>("/conversations");
}

export function listConversationMessages(conversationId: string): Promise<ChatMessage[]> {
  return request<ChatMessage[]>(`/conversations/${conversationId}/messages`);
}

/** PATCH /conversations/{cid}/messages/{mid}/feedback — `rating` is
 * 1 (thumbs up), -1 (thumbs down) or 0 (cleared). Feeds the officer
 * dashboard's feedback metrics. */
export function submitFeedback(
  conversationId: string,
  messageId: string,
  rating: -1 | 0 | 1,
  comment?: string,
): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/conversations/${conversationId}/messages/${messageId}/feedback`,
    { method: "PATCH", body: JSON.stringify({ rating, comment: comment ?? null }) },
  );
}

export function listSchemes(): Promise<SchemeRules[]> {
  return request<SchemeRules[]>("/certification/schemes");
}

export function postWizardStep(answers: WizardAnswers): Promise<WizardResponse> {
  return request<WizardResponse>("/certification/wizard", {
    method: "POST",
    body: JSON.stringify(answers),
  });
}

export function postVerifyLicence(payload: VerifyRequest): Promise<VerifyResponse> {
  return request<VerifyResponse>("/verify", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postGapCheck(payload: GapCheckRequest): Promise<GapCheckResponse> {
  return request<GapCheckResponse>("/analysis/gap-check", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * POST /api/v1/chat streams its response as Server-Sent Events rather than
 * one JSON body, so this returns the raw `Response` for the caller
 * (`useChatStream`) to read via `parseSSEStream` (`lib/sse.ts`) instead of
 * parsing it as JSON like every other endpoint here.
 */
export async function postChat(payload: ChatRequest, signal?: AbortSignal): Promise<Response> {
  const response = await fetch("/api/v1/chat", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => null)) as ProblemDetail | null;
    throw new ApiError(
      problem ?? { type: "about:blank", title: "Request failed", status: response.status },
    );
  }

  return response;
}
