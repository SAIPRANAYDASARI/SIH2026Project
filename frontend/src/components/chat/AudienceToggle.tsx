import { cn } from "@/lib/utils";
import type { Audience } from "@/types/api";

interface AudienceToggleProps {
  value: Audience;
  onChange: (audience: Audience) => void;
  disabled?: boolean;
}

const OPTIONS: { value: Audience; label: string }[] = [
  { value: "consumer", label: "Consumer" },
  { value: "industry", label: "Industry" },
];

/** F5 from the brief: switches the answer engine's persona/prompt (see
 * `app.answer.prompts`) between a plain-language consumer voice and a
 * more technical industry/manufacturer voice. */
export function AudienceToggle({ value, onChange, disabled }: AudienceToggleProps): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label="Audience"
      className="inline-flex rounded-full border border-border/60 bg-surface/60 p-0.5 backdrop-blur-md"
    >
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-full px-3 py-1 text-sm font-medium transition-all duration-200 disabled:opacity-50",
            value === option.value
              ? "bg-gradient-to-r from-primary to-glow text-primary-foreground shadow-glow"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
