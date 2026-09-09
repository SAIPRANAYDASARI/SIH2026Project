import { forwardRef } from "react";
import type { TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex w-full resize-none rounded-lg border border-border/60 bg-surface/60 px-3 py-2 text-sm " +
        "backdrop-blur-md transition-shadow duration-200 placeholder:text-muted-foreground " +
        "focus-visible:border-primary/50 focus-visible:shadow-glow focus-visible:outline-none " +
        "disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
