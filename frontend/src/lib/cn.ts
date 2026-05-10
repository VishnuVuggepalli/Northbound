import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Combine class lists. `clsx` handles falsy values; `twMerge` resolves
 * Tailwind conflicts so the last passed utility wins.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
