import { useState } from "react";
import type { FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { postGapCheck } from "@/lib/api";
import type { GapCheckResponse } from "@/types/api";

/** F4's gap-analysis half: given a product description and the licences
 * the user already holds, shows which mandatory BIS schemes they're still
 * missing — see `app.services.gap_analysis_service`. */
export function GapChecker(): JSX.Element {
  const [description, setDescription] = useState("");
  const [licenceNumbers, setLicenceNumbers] = useState("");
  const [response, setResponse] = useState<GapCheckResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    if (!description.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const result = await postGapCheck({
        product_description: description.trim(),
        held_licence_numbers: licenceNumbers
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setResponse(result);
    } catch {
      setError("Couldn't reach the gap-analysis service. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Describe your product and the licences you already hold — see which mandatory BIS
        certifications you're still missing.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. LED bulb manufactured in India for retail sale"
          rows={3}
          aria-label="Product description"
          disabled={loading}
        />
        <Input
          value={licenceNumbers}
          onChange={(e) => setLicenceNumbers(e.target.value)}
          placeholder="Licence numbers you already hold, comma-separated (optional)"
          aria-label="Held licence numbers"
          disabled={loading}
        />
        <Button type="submit" disabled={loading || !description.trim()} className="self-start">
          {loading ? "Checking…" : "Check gaps"}
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {response && (
        <div className="flex animate-fade-slide-up flex-col gap-4">
          {response.matched_scheme_codes.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No certification scheme matched this description.
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Matched schemes:</span>
              {response.matched_scheme_codes.map((code) => (
                <Badge key={code} variant="outline">
                  {code}
                </Badge>
              ))}
            </div>
          )}

          {response.missing_mandatory.length > 0 && (
            <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-4">
              <p className="mb-2 text-sm font-semibold text-destructive">Missing — mandatory</p>
              <ul className="flex flex-col gap-2 text-sm">
                {response.missing_mandatory.map((m) => (
                  <li key={m.code}>
                    <span className="font-medium">{m.name}</span>
                    <span className="text-muted-foreground"> — {m.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {response.missing_voluntary.length > 0 && (
            <div className="rounded-xl border border-warning/40 bg-warning/10 p-4">
              <p className="mb-2 text-sm font-semibold text-warning">Missing — voluntary</p>
              <ul className="flex flex-col gap-2 text-sm">
                {response.missing_voluntary.map((m) => (
                  <li key={m.code}>
                    <span className="font-medium">{m.name}</span>
                    <span className="text-muted-foreground"> — {m.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {response.covered_scheme_codes.length > 0 && (
            <div className="rounded-xl border border-success/40 bg-success/10 p-4">
              <p className="mb-2 text-sm font-semibold text-success">Already covered</p>
              <div className="flex flex-wrap gap-2">
                {response.covered_scheme_codes.map((code) => (
                  <Badge key={code} variant="secondary">
                    {code}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <p className="rounded-lg border border-border/50 bg-surface/50 p-3 text-xs text-muted-foreground">
            {response.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}
