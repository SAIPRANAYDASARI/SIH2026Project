import { cn } from "@/lib/utils";
import type { Language } from "@/types/api";

interface LanguageToggleProps {
  value: Language;
  onChange: (language: Language) => void;
  disabled?: boolean;
}

const OPTIONS: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिंदी" },
];

/** Answer-language toggle: the LLM writes the whole answer natively in the
 * selected language (see `app.answer.prompts`), not translated after the
 * fact — same pattern as `AudienceToggle`. */
export function LanguageToggle({ value, onChange, disabled }: LanguageToggleProps): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label="Answer language"
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
