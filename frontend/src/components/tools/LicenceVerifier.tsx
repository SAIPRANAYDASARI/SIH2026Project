import { CheckCircle2, XCircle } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { postVerifyLicence } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { LicenceType, VerifyResponse } from "@/types/api";

const TYPE_OPTIONS: { value: LicenceType | ""; label: string }[] = [
  { value: "", label: "Any type" },
  { value: "cml", label: "CM/L (ISI)" },
  { value: "crs_r", label: "CRS R-number" },
  { value: "huid", label: "HUID (hallmarking)" },
];

const STATUS_VARIANT: Record<string, "default" | "warning" | "destructive"> = {
  active: "default",
  expired: "warning",
  suspended: "destructive",
  cancelled: "destructive",
  not_found: "destructive",
};

/** F4 from the brief: check a CM/L, CRS R-number, or HUID against the
 * (small, illustrative demo) licence dataset — see
 * `app.services.verification_service`. */
export function LicenceVerifier(): JSX.Element {
  const [licenceNumber, setLicenceNumber] = useState("");
  const [licenceType, setLicenceType] = useState<LicenceType | "">("");
  const [response, setResponse] = useState<VerifyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    if (!licenceNumber.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const result = await postVerifyLicence({
        licence_number: licenceNumber.trim(),
        licence_type: licenceType || null,
      });
      setResponse(result);
    } catch {
      setError("Couldn't reach the verification service. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Check whether a CM/L number, CRS R-number, or HUID is genuine against our records.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row">
        <Input
          value={licenceNumber}
          onChange={(e) => setLicenceNumber(e.target.value)}
          placeholder="e.g. CML-DEMO-0001"
          aria-label="Licence number"
          disabled={loading}
        />
        <select
          value={licenceType}
          onChange={(e) => setLicenceType(e.target.value as LicenceType | "")}
          aria-label="Licence type"
          disabled={loading}
          className="h-10 rounded-lg border border-border/60 bg-surface/60 px-3 text-sm backdrop-blur-md focus-visible:border-primary/50 focus-visible:shadow-glow focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        >
          {TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={loading || !licenceNumber.trim()}>
          {loading ? "Checking…" : "Verify"}
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {response && (
        <div
          className={cn(
            "flex animate-fade-slide-up items-start gap-3 rounded-xl border p-4 backdrop-blur-md",
            response.found
              ? "border-success/40 bg-success/10"
              : "border-destructive/40 bg-destructive/10",
          )}
        >
          {response.found ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden="true" />
          ) : (
            <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
          )}
          <div className="flex flex-col gap-2 text-sm">
            <p>{response.message}</p>
            {response.result && (
              <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={STATUS_VARIANT[response.result.status] ?? "secondary"}>
                    {response.result.status}
                  </Badge>
                  <Badge variant="outline">{response.result.licence_type.toUpperCase()}</Badge>
                  {response.result.is_seed_data && <Badge variant="secondary">demo data</Badge>}
                </div>
                {response.result.holder_name && <p>Holder: {response.result.holder_name}</p>}
                {response.result.product_category && (
                  <p>Product: {response.result.product_category}</p>
                )}
                {response.result.is_number && <p>Standard: {response.result.is_number}</p>}
                {response.result.valid_until && (
                  <p className="text-muted-foreground">
                    Valid until {response.result.valid_until}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
