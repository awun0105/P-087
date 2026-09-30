import Link from "next/link";

import { Button } from "@/components/studio/primitives";

/** 404 chung: nói rõ không tìm thấy và đưa về Scenes (PRODUCT.md §6 trạng thái chung). */
export default function NotFound() {
  return (
    <main className="studio-root flex min-h-dvh flex-col items-center justify-center gap-3 bg-paper px-4 text-center text-ink">
      <h1 className="text-2xl font-semibold">Không tìm thấy trang</h1>
      <p className="max-w-md text-sm text-ink-muted">
        Đường dẫn không tồn tại hoặc scene không còn truy cập được với tài khoản này.
      </p>
      <Button asChild variant="secondary">
        <Link href="/">Về Scenes</Link>
      </Button>
    </main>
  );
}
