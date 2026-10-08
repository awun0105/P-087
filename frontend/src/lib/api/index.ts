export * from "./studio";
import { STUDIO_ENTRY } from "@/lib/routes";

export const STUDIO_LOGIN_URL = process.env.NEXT_PUBLIC_STUDIO_LOGIN_URL || STUDIO_ENTRY || "/login";
export const STUDIO_URL = process.env.NEXT_PUBLIC_STUDIO_URL || "";
