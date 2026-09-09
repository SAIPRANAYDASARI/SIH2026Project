import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { AuroraBackground } from "@/components/background/AuroraBackground";
import { Card } from "@/components/ui/card";
import { getAnalyticsSummary } from "@/lib/api";

/**
 * The officer dashboard (Step 11, F-officer-view from the brief): read-only
 * aggregate metrics over every conversation — intent distribution,
 * guardrail-violation rate, forced-refusal rate, feedback split. No
 * per-user drill-down (would need real auth/roles — flagged in
 * docs/DECISIONS.md as a scope gap, not implemented in this hackathon
 * build) and no login gate on this route yet for the same reason.
 *
 * The feedback figures here are populated by the thumbs up/down control on
 * each answer (`components/chat/MessageActions`).
 */
export function OfficerDashboard(): JSX.Element {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics-summary"],
    queryFn: getAnalyticsSummary,
    refetchInterval: 30_000,
  });

  return (
    <div className="relative min-h-screen">
      <AuroraBackground />

      <div className="relative z-10 mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="bg-gradient-to-r from-primary to-glow bg-clip-text text-2xl font-semibold tracking-tight text-transparent">
              Officer Dashboard
            </h1>
            <p className="text-xs text-muted-foreground">
              Aggregate quality and usage metrics across all conversations
            </p>
          </div>
          <nav className="flex items-center gap-1 text-xs">
            <Link
              to="/"
              className="rounded-full px-2.5 py-1 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
            >
              &larr; Chat
            </Link>
            <Link
              to="/tools"
              className="rounded-full px-2.5 py-1 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
            >
              Tools
            </Link>
          </nav>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading analytics…</p>}
        {isError && (
          <p className="text-sm text-destructive">
            Could not load analytics — is the backend running?
          </p>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Conversations" value={data.total_conversations} delay={0} />
              <StatCard
                label="Assistant messages"
                value={data.total_assistant_messages}
                delay={60}
              />
              <StatCard
                label="Forced refusal rate"
                value={`${(data.forced_refusal_rate * 100).toFixed(1)}%`}
                delay={120}
              />
              <StatCard
                label="Avg latency"
                value={data.average_latency_ms ? `${Math.round(data.average_latency_ms)} ms` : "—"}
                delay={180}
              />
              <StatCard
                label="Guardrail violations"
                value={data.guardrail_violation_count}
                delay={240}
              />
              <StatCard label="👍 Feedback" value={data.feedback_thumbs_up} delay={300} />
              <StatCard label="👎 Feedback" value={data.feedback_thumbs_down} delay={360} />
              <StatCard
                label="Feedback response rate"
                value={`${(data.feedback_response_rate * 100).toFixed(1)}%`}
                delay={420}
              />
            </div>

            <Card className="animate-fade-slide-up p-4">
              <h2 className="mb-4 text-lg font-medium">Intent distribution</h2>
              {data.intent_distribution.length === 0 ? (
                <p className="text-sm text-muted-foreground">No assistant messages yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={data.intent_distribution}>
                    {/* Colours come from the same CSS custom properties as
                        the rest of the UI (they cascade into SVG), so the
                        chart can't drift out of sync with a theme change. */}
                    <defs>
                      <linearGradient id="barAurora" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(var(--glow))" />
                        <stop offset="100%" stopColor="hsl(var(--primary))" />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.4)" />
                    <XAxis
                      dataKey="intent"
                      tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                      stroke="hsl(var(--border))"
                    />
                    <YAxis
                      allowDecimals={false}
                      tick={{ fill: "hsl(var(--muted-foreground))" }}
                      stroke="hsl(var(--border))"
                    />
                    <Tooltip
                      cursor={{ fill: "hsl(var(--primary) / 0.1)" }}
                      contentStyle={{
                        background: "hsl(var(--surface))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: "0.5rem",
                        color: "hsl(var(--foreground))",
                      }}
                    />
                    <Bar dataKey="count" fill="url(#barAurora)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  delay = 0,
}: {
  label: string;
  value: string | number;
  delay?: number;
}): JSX.Element {
  return (
    <Card
      style={{ animationDelay: `${delay}ms` }}
      className="animate-fade-slide-up p-4 transition-shadow hover:shadow-glow"
    >
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 bg-gradient-to-r from-primary to-glow bg-clip-text text-2xl font-semibold tabular-nums text-transparent">
        {value}
      </p>
    </Card>
  );
}
