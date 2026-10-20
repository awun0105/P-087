"use client";

import { createContext, useContext, useSyncExternalStore } from "react";

/**
 * T-064: viewer có đang được nhìn thấy không. Trang scene giữ Studio mount khi đổi tab (ẩn bằng CSS) nên đặt `false` khi rời
 * tab Studio; mặc định `true` cho mọi viewer khác.
 */
export const ViewerActiveContext = createContext(true);

function subscribe(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

/** Tab trình duyệt đang hiện (server render coi như hiện). */
function useDocumentVisible(): boolean {
  return useSyncExternalStore(subscribe, () => document.visibilityState !== "hidden", () => true);
}

/** `inTab`: Studio đang là tab hiện; `visible`: thêm điều kiện tab trình duyệt đang hiện. */
export function useViewerActive(): { inTab: boolean; visible: boolean } {
  const inTab = useContext(ViewerActiveContext);
  const documentVisible = useDocumentVisible();
  return { inTab, visible: inTab && documentVisible };
}
