export const STUDIO_LOGIN_URL =
  process.env.NEXT_PUBLIC_STUDIO_LOGIN_URL ||
  (process.env.NEXT_PUBLIC_STUDIO_URL
    ? `${process.env.NEXT_PUBLIC_STUDIO_URL}/login?next=%2Foverview`
    : "/login?next=%2Foverview");

export const STUDIO_URL = process.env.NEXT_PUBLIC_STUDIO_URL || "";
