import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";
import { OfficerDashboard } from "@/pages/OfficerDashboard";

function renderPage(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/dashboard"]}>
        <OfficerDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OfficerDashboard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders aggregate stats once analytics load", async () => {
    vi.spyOn(api, "getAnalyticsSummary").mockResolvedValue({
      total_conversations: 5,
      total_assistant_messages: 12,
      intent_distribution: [{ intent: "standard_lookup", count: 8 }],
      guardrail_violation_count: 1,
      forced_refusal_count: 2,
      forced_refusal_rate: 2 / 12,
      average_latency_ms: 900,
      feedback_thumbs_up: 3,
      feedback_thumbs_down: 1,
      feedback_response_rate: 4 / 12,
    });

    renderPage();

    await waitFor(() => expect(screen.getByText("5")).toBeInTheDocument());
    expect(screen.getByText("900 ms")).toBeInTheDocument();
  });

  it("shows an error message when the analytics request fails", async () => {
    vi.spyOn(api, "getAnalyticsSummary").mockRejectedValue(new Error("boom"));

    renderPage();

    await waitFor(() => expect(screen.getByText(/could not load analytics/i)).toBeInTheDocument());
  });
});
