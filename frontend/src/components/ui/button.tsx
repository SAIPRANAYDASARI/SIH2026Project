import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * Hand-built rather than scaffolded via the shadcn CLI: `shadcn init`'s
 * first step calls out to ui.shadcn.com for its registry/telemetry, which
 * this sandbox's network egress blocks (confirmed while building this
 * step — same class of restriction as bis.gov.in in Step 2). This
 * component follows shadcn/ui's own Button API and variant conventions
 * (CVA-based variants, `asChild`-free, same class names) without the
 * Radix `Slot` dependency, so swapping in the real generated component
 * later is a drop-in replacement, not a rewrite. See docs/DECISIONS.md.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium " +
    "transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 " +
    "focus-visible:ring-primary disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-gradient-to-br from-primary to-glow text-primary-foreground shadow-glow " +
          "hover:-translate-y-0.5 hover:shadow-glow-lg active:translate-y-0",
        outline:
          "border border-border/60 bg-surface/50 backdrop-blur-md hover:-translate-y-0.5 " +
          "hover:border-primary/50 hover:bg-surface/80",
        ghost: "bg-transparent hover:bg-muted/60",
        destructive: "bg-destructive text-primary-foreground hover:opacity-90",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
);
Button.displayName = "Button";
