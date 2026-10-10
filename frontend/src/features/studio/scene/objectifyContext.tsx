"use client";

import { createContext, useContext } from "react";

import { useObjectifyState } from "@/features/studio/scene/useObjectify";

/** Trạng thái tách vật thể mà trang scene chia sẻ cho mọi nơi trong trang (xem `useObjectifyState`). */
export type ObjectifyHandle = ReturnType<typeof useObjectifyState>;

export const ObjectifyContext = createContext<ObjectifyHandle | null>(null);

/**
 * Trong trang scene: dùng trạng thái chung do `ScenePage` giữ, nên thao tác ở tab Tiến trình và ở Studio luôn thấy cùng
 * một kết quả. Ngoài trang scene (màn khác, test) thì tự giữ một bản riêng; `options` chỉ có tác dụng ở trường hợp đó.
 */
export function useObjectify(options: Parameters<typeof useObjectifyState>[0]): ObjectifyHandle {
  const shared = useContext(ObjectifyContext);
  const local = useObjectifyState({ ...options, enabled: (options.enabled ?? true) && shared === null });
  return shared ?? local;
}
