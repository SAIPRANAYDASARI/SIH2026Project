import { useState } from "react";
import { Link } from "react-router-dom";

import { AuroraBackground } from "@/components/background/AuroraBackground";
import { Card, CardContent } from "@/components/ui/card";
import { CertificationWizard } from "@/components/tools/CertificationWizard";
import { GapChecker } from "@/components/tools/GapChecker";
import { LicenceVerifier } from "@/components/tools/LicenceVerifier";
import { SchemeBrowser } from "@/components/tools/SchemeBrowser";
import { cn } from "@/lib/utils";

type Tool = "wizard" | "verify" | "gap-check" | "schemes";

const TOOLS: { value: Tool; label: string }[] = [
  { value: "wizard", label: "Certification wizard" },
  { value: "verify", label: "Verify a licence" },
  { value: "gap-check", label: "Gap check" },
  { value: "schemes", label: "Browse schemes" },
];

/** Surfaces the rules-engine-backed tools (F4/F8 from the brief) that
 * otherwise only exist as API endpoints — the certification wizard,
 * licence verification, and gap analysis all run on deterministic YAML
 * rules / a demo licence table, no LLM involved, so they're instant next
 * to the chat's LLM latency. */
export function ToolsPage(): JSX.Element {
  const [tool, setTool] = useState<Tool>("wizard");

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden">
      <AuroraBackground />

      <header className="relative z-10 flex flex-wrap items-center justify-between gap-3 border-b border-border/40 bg-surface/30 px-4 py-3 backdrop-blur-xl">
        <div>
          <h1 className="bg-gradient-to-r from-primary to-glow bg-clip-text text-lg font-semibold tracking-tight text-transparent">
            Certification Tools
          </h1>
          <p className="text-xs text-muted-foreground">
            Rules-engine tools — instant, no LLM involved
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/" className="text-primary hover:underline">
            ← Chat
          </Link>
          <Link to="/dashboard" className="text-primary hover:underline">
            Officer dashboard
          </Link>
        </div>
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 p-4">
        <div
          role="tablist"
          aria-label="Tool"
          className="inline-flex w-fit flex-wrap gap-0.5 rounded-full border border-border/60 bg-surface/60 p-0.5 backdrop-blur-md"
        >
          {TOOLS.map((t) => (
            <button
              key={t.value}
              type="button"
              role="tab"
              aria-selected={tool === t.value}
              onClick={() => setTool(t.value)}
              className={cn(
                "rounded-full px-3 py-1.5 text-sm font-medium transition-all duration-200",
                tool === t.value
                  ? "bg-gradient-to-r from-primary to-glow text-primary-foreground shadow-glow"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <Card>
          <CardContent>
            {tool === "wizard" && <CertificationWizard />}
            {tool === "verify" && <LicenceVerifier />}
            {tool === "gap-check" && <GapChecker />}
            {tool === "schemes" && <SchemeBrowser />}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
