import { useState } from "react";
import type { FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { postWizardStep } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { WizardAnswers, WizardResponse } from "@/types/api";

/**
 * A thin UI over the stateless certification wizard (`app.rules.wizard`):
 * every step resubmits the full answers collected so far and gets back
 * either the next question or the final matched-scheme result — this
 * component just accumulates `answers` in React state and mirrors that
 * back to the server on each step, it never decides the flow itself.
 */
export function CertificationWizard(): JSX.Element {
  const [answers, setAnswers] = useState<WizardAnswers>({});
  const [productInput, setProductInput] = useState("");
  const [response, setResponse] = useState<WizardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (nextAnswers: WizardAnswers): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const result = await postWizardStep(nextAnswers);
      setAnswers(nextAnswers);
      setResponse(result);
    } catch {
      setError("Couldn't reach the certification rules engine. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleProductSubmit = (e: FormEvent): void => {
    e.preventDefault();
    if (!productInput.trim()) return;
    void submit({ product_description: productInput });
  };

  const handleOrigin = (manufacturedInIndia: boolean): void => {
    void submit({ ...answers, manufactured_in_india: manufacturedInIndia });
  };

  const reset = (): void => {
    setAnswers({});
    setProductInput("");
    setResponse(null);
    setError(null);
  };

  const showProductForm = !response || (!response.done && response.next_question?.field === "product_description");
  const showOriginQuestion = response && !response.done && response.next_question?.input_type === "boolean";

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Answer a couple of questions to find which BIS certification scheme(s) likely apply to
        your product.
      </p>

      {showProductForm && (
        <form onSubmit={handleProductSubmit} className="flex flex-col gap-2 sm:flex-row">
          <Input
            value={productInput}
            onChange={(e) => setProductInput(e.target.value)}
            placeholder="e.g. LED bulb, gold jewellery, pressure cooker…"
            aria-label="Product description"
            disabled={loading}
          />
          <Button type="submit" disabled={loading || !productInput.trim()}>
            {loading ? "Checking…" : "Find scheme"}
          </Button>
        </form>
      )}

      {showOriginQuestion && response?.next_question && (
        <div className="flex animate-fade-slide-up flex-col gap-3 rounded-xl border border-border/60 bg-surface/60 p-4 backdrop-blur-md">
          <p className="text-sm font-medium">{response.next_question.prompt}</p>
          <div className="flex gap-2">
            <Button type="button" onClick={() => handleOrigin(true)} disabled={loading}>
              Yes
            </Button>
            <Button type="button" variant="outline" onClick={() => handleOrigin(false)} disabled={loading}>
              No
            </Button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {response?.done && (
        <div className="flex animate-fade-slide-up flex-col gap-4">
          {response.results.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No matching scheme found for that description.
            </p>
          )}

          {response.results.map(({ scheme, matched_keywords }) => (
            <div
              key={scheme.code}
              className="flex flex-col gap-3 rounded-xl border border-border/60 bg-surface/60 p-4 backdrop-blur-md shadow-glass"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{scheme.name}</h3>
                {scheme.mandatory && <Badge variant="warning">mandatory (QCO)</Badge>}
                {matched_keywords.map((kw) => (
                  <Badge key={kw} variant="secondary">
                    {kw}
                  </Badge>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">{scheme.description}</p>

              <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Timeline</p>
                  <p>{scheme.timeline_days ? `~${scheme.timeline_days} days` : "Not specified"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Validity</p>
                  <p>{scheme.validity_years ? `${scheme.validity_years} years` : "Not specified"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Fees</p>
                  {scheme.fees.length === 0 ? (
                    <p>Not specified</p>
                  ) : (
                    <ul>
                      {scheme.fees.map((fee) => (
                        <li key={fee.category}>
                          ₹{fee.fee_inr.toLocaleString("en-IN")} — {fee.category} ({fee.unit})
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {scheme.required_documents.length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    Required documents
                  </p>
                  <ul className="flex flex-col gap-1 text-sm">
                    {scheme.required_documents.map((doc) => (
                      <li key={doc.name} className={cn("flex items-start gap-1.5")}>
                        <span className="mt-0.5 text-primary">{doc.required ? "●" : "○"}</span>
                        <span>
                          {doc.name}
                          {!doc.required && " (optional)"}
                          {doc.notes && (
                            <span className="text-muted-foreground"> — {doc.notes}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}

          {response.disclaimer && (
            <p className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-muted-foreground">
              {response.disclaimer}
            </p>
          )}

          <Button type="button" variant="outline" onClick={reset} className="self-start">
            Start over
          </Button>
        </div>
      )}
    </div>
  );
}
