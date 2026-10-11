import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Ghép class Tailwind, class sau thắng class trước khi trùng thuộc tính (pattern shadcn). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
