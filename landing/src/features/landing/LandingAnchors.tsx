"use client";

import { useEffect } from "react";

/**
 * Điều hướng tới mục trong landing (`#problem`, `#workflow`…) mà không tạo history entry mới.
 *
 * Link `#…` thuần của trình duyệt tạo entry có `history.state = null`. App Router của Next bỏ qua `popstate`
 * không mang state của nó, nên sau khi sang app rồi bấm Back, địa chỉ đổi thành `/#workflow` nhưng màn hình vẫn
 * là app (phải Back qua hết các mục mới về được landing). Ở đây cuộn tới mục và cập nhật hash bằng
 * `replaceState` với đúng state đang có: Back từ app về thẳng landing, và landing không rải một chuỗi entry
 * theo từng lần bấm menu. Không có JavaScript thì link `#…` vẫn chạy theo cách gốc của trình duyệt.
 */
export function LandingAnchors() {
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      // Click có phím bổ trợ / nút khác: để trình duyệt xử lý (mở tab mới…).
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest('a[href^="#"]') : null;
      if (!(link instanceof HTMLAnchorElement) || !link.closest(".landing-page")) return;
      let id = link.hash.slice(1);
      try {
        id = decodeURIComponent(id);
      } catch {
        // hash hỏng: dùng nguyên văn
      }
      const target = document.getElementById(id);
      if (!target) return;
      event.preventDefault();
      const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      history.replaceState(history.state, "", link.hash);
      // Giữ hành vi bàn phím của link mục: phím Tab tiếp theo bắt đầu từ mục vừa tới.
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
  return null;
}
