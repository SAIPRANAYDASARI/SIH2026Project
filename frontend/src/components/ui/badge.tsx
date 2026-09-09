import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium backdrop-blur-md " +
    "transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-gradient-to-r from-primary to-glow text-primary-foreground",
        secondary: "border-border/50 bg-surface/60 text-muted-foreground",
        outline: "border-border text-foreground",
        warning: "border-transparent bg-warning/90 text-primary-foreground",
        destructive: "border-transparent bg-destructive/90 text-primary-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps): JSX.Element {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
