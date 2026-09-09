import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { listSchemes } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SchemeRules } from "@/types/api";

/** Reference view over the whole rules dataset (`GET /certification/schemes`).
 * The wizard answers "which scheme applies to my product?"; this answers
 * "what schemes exist, and what does each one require?" — useful when you
 * already know the scheme name and just want its fees or checklist. */
export function SchemeBrowser(): JSX.Element {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["schemes"],
    queryFn: listSchemes,
    retry: false,
  });
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const needle = filter.trim().toLowerCase();
  const visible = (data ?? []).filter((scheme) =>
    needle === ""
      ? true
      : [scheme.name, scheme.code, scheme.description, ...scheme.product_keywords]
          .join(" ")
          .toLowerCase()
          .includes(needle),
  );

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Every certification scheme in the rules dataset, with its fees, timeline and document
        checklist. Search by scheme or by product.
      </p>

      <Input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter by scheme or product (e.g. hallmarking, LED, CRS)…"
        aria-label="Filter schemes"
      />

      {isLoading && <p className="text-sm text-muted-foreground">Loading schemes…</p>}
      {isError && (
        <p className="text-sm text-destructive">Couldn&apos;t load the scheme dataset.</p>
      )}
      {data && visible.length === 0 && (
        <p className="text-sm text-muted-foreground">No scheme matches “{filter}”.</p>
      )}

      <ul className="flex flex-col gap-2">
        {visible.map((scheme, index) => (
          <li key={scheme.code}>
            <SchemeRow
              scheme={scheme}
              index={index}
              isOpen={expanded === scheme.code}
              onToggle={() => setExpanded(expanded === scheme.code ? null : scheme.code)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

function SchemeRow({
  scheme,
  index,
  isOpen,
  onToggle,
}: {
  scheme: SchemeRules;
  index: number;
  isOpen: boolean;
  onToggle: () => void;
}): JSX.Element {
  return (
    <div
      style={{ animationDelay: `${index * 50}ms` }}
      className="animate-fade-slide-up gradient-border overflow-hidden rounded-xl bg-surface/50 backdrop-blur-md"
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-primary/5"
      >
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{scheme.name}</span>
            <Badge variant="outline">{scheme.code}</Badge>
            {scheme.mandatory && <Badge variant="warning">mandatory</Badge>}
          </span>
          {!isOpen && (
            <span className="mt-0.5 line-clamp-1 block text-xs text-muted-foreground">
              {scheme.description}
            </span>
          )}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
            isOpen && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>

      {isOpen && (
        <div className="flex animate-fade-slide-up flex-col gap-3 border-t border-border/50 px-4 py-3 text-sm">
          <p className="whitespace-pre-line text-muted-foreground">{scheme.description}</p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Timeline">
              {scheme.timeline_days ? `~${scheme.timeline_days} days` : "Not specified"}
            </Field>
            <Field label="Validity">
              {scheme.validity_years ? `${scheme.validity_years} years` : "Not specified"}
            </Field>
            <Field label="Fees">
              {scheme.fees.length === 0
                ? "Not specified"
                : scheme.fees.map((fee) => (
                    <span key={fee.category} className="block">
                      ₹{fee.fee_inr.toLocaleString("en-IN")} — {fee.category} ({fee.unit})
                    </span>
                  ))}
            </Field>
          </div>

          {scheme.required_documents.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Required documents</p>
              <ul className="flex flex-col gap-1">
                {scheme.required_documents.map((doc) => (
                  <li key={doc.name} className="flex items-start gap-1.5">
                    <span className="mt-0.5 text-primary">{doc.required ? "●" : "○"}</span>
                    <span>
                      {doc.name}
                      {!doc.required && " (optional)"}
                      {doc.notes && <span className="text-muted-foreground"> — {doc.notes}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {scheme.product_keywords.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Matches products like</p>
              <div className="flex flex-wrap gap-1.5">
                {scheme.product_keywords.map((keyword) => (
                  <Badge key={keyword} variant="secondary">
                    {keyword}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <p className="rounded-lg border border-warning/30 bg-warning/10 p-2.5 text-xs text-muted-foreground">
            {scheme.source_note}
          </p>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }): JSX.Element {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div>{children}</div>
    </div>
  );
}
