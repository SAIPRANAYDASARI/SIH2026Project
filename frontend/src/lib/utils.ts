import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui's standard class-merging helper: clsx for conditional classes,
 * tailwind-merge to resolve conflicting Tailwind utilities (e.g. a caller
 * overriding `p-4` with `p-2`) predictably. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
