import Link from "next/link";

import { PageHeader } from "@/components/shell";
import { listProjects } from "@/lib/api/endpoints";
import { ErrorState } from "@/components/states";

/**
 * Trang chủ: điểm vào duy nhất, và là nơi kiểm tra nhanh backend có sống không.
 *
 * Cố ý gọi API thật thay vì hiện trang tĩnh — nếu backend chết thì người xem
 * thấy ngay ở đây chứ không phải sau ba lần bấm.
 */
export default async function HomePage() {
  const result = await listProjects();

  return (
    <>
      <PageHeader
        title="Web Studio"
        subtitle="Luồng M1: mock project → mock job → browser viewer → mock review."
      />
      <nav className="mb-6 flex flex-wrap gap-2 text-sm">
        <Link href="/projects" className="rounded bg-sky-600 px-3 py-1 text-white hover:bg-sky-500">
          Danh sách project
        </Link>
        <Link
          href="/jobs/job-fixture-001"
          className="rounded bg-slate-800 px-3 py-1 text-slate-200 hover:bg-slate-700"
        >
          Job mẫu (job-fixture-001)
        </Link>
        <Link
          href="/jobs/job-fixture-001/viewer"
          className="rounded bg-slate-800 px-3 py-1 text-slate-200 hover:bg-slate-700"
        >
          Scene viewer
        </Link>
      </nav>
      {result.ok ? (
        <p className="text-sm text-emerald-300" data-testid="backend-status">
          Backend trả {result.data.projects.length} project.
        </p>
      ) : (
        <ErrorState
          title="Không gọi được backend"
          detail={`${result.error.status}: ${result.error.detail}\n\nChạy \`make run\` (hoặc \`uvicorn src.main:app --reload\`) rồi tải lại.`}
        />
      )}
    </>
  );
}
