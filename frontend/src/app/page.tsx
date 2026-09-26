import Link from "next/link";

import { PageHeader } from "@/components/shell";
import { listProjects } from "@/lib/api/endpoints";
import { ErrorState } from "@/components/states";

/**
 * Trang chủ / Demo route (PRODUCT-12).
 *
 * Gọi backend thật để kiểm tra live status. Hiện workflow steps để pitching.
 */
export default async function HomePage() {
  const result = await listProjects();
  const FIXTURE_JOB = "job-fixture-001";
  const FIXTURE_PROJECT = "project-fixture-001";

  const WORKFLOW_STEPS = [
    {
      step: "01",
      label: "Projects",
      href: "/projects",
      desc: "Tạo project, kiểm tra privacy gate & source rights",
      icon: "⬡",
      color: "border-sky-800 bg-sky-950/40",
    },
    {
      step: "02",
      label: "Job",
      href: `/jobs/${FIXTURE_JOB}`,
      desc: "Dispatch job, theo dõi stage pipeline REC→SCENE→SIM",
      icon: "⚙",
      color: "border-violet-800 bg-violet-950/40",
    },
    {
      step: "03",
      label: "Scene Viewer",
      href: `/jobs/${FIXTURE_JOB}/viewer`,
      desc: "Inspect geometry, point cloud, collider · edit transform · thêm obstacle",
      icon: "◈",
      color: "border-indigo-800 bg-indigo-950/40",
    },
    {
      step: "04",
      label: "Validation",
      href: `/jobs/${FIXTURE_JOB}/validation`,
      desc: "Xem báo cáo validation checks + path results của candidate",
      icon: "✓",
      color: "border-emerald-800 bg-emerald-950/40",
    },
    {
      step: "05",
      label: "Review",
      href: `/jobs/${FIXTURE_JOB}/review`,
      desc: "Approve / reject với ràng buộc checksum lineage",
      icon: "◎",
      color: "border-amber-800 bg-amber-950/40",
    },
    {
      step: "06",
      label: "Release",
      href: `/jobs/${FIXTURE_JOB}/release`,
      desc: "Seal exact candidate → ReleaseManifest (PRODUCT-11)",
      icon: "⬆",
      color: "border-rose-800 bg-rose-950/40",
    },
  ];

  return (
    <>
      <PageHeader
        title="Real2Sim Studio"
        subtitle="Human-in-the-Loop pipeline: Input → REC → SCENE → SIM → Review → Release"
      />

      {/* Backend health */}
      <div className="mb-6">
        {result.ok ? (
          <div className="inline-flex items-center gap-2 rounded-lg border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            Backend sống · {result.data.projects.length} project · fixture mode
          </div>
        ) : (
          <ErrorState
            title="Không gọi được backend"
            detail={`${result.error.status}: ${result.error.detail}\n\nChạy \`uvicorn src.main:app --reload\` rồi tải lại.`}
          />
        )}
      </div>

      {/* Workflow steps (PRODUCT-12 demo route) */}
      <section className="mb-8">
        <h2 className="mb-4 text-sm font-semibold text-slate-300">Demo workflow</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {WORKFLOW_STEPS.map((step, idx) => (
            <Link
              key={step.step}
              href={step.href}
              className={`group relative rounded-xl border p-4 transition-all hover:scale-[1.02] hover:shadow-lg ${step.color}`}
            >
              <div className="mb-3 flex items-center gap-2">
                <span className="text-2xl leading-none">{step.icon}</span>
                <div>
                  <p className="text-[10px] text-slate-600 font-mono">step {step.step}</p>
                  <p className="text-sm font-semibold text-slate-200">{step.label}</p>
                </div>
                {idx < WORKFLOW_STEPS.length - 1 && (
                  <span className="absolute -right-1.5 top-1/2 -translate-y-1/2 text-slate-700 text-xs hidden lg:block">
                    →
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">{step.desc}</p>
              <span className="mt-2 block text-[10px] text-sky-600 group-hover:text-sky-400 transition-colors">
                Mở →
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* Quick links */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-slate-300">Quick access</h2>
        <div className="flex flex-wrap gap-2">
          <QuickLink href="/projects" label="⬡ Projects" />
          <QuickLink href={`/projects/${FIXTURE_PROJECT}`} label="◳ Project fixture" />
          <QuickLink href={`/jobs/${FIXTURE_JOB}`} label="⚙ Job fixture" />
          <QuickLink href={`/jobs/${FIXTURE_JOB}/viewer`} label="◈ Scene viewer" />
          <QuickLink href={`/jobs/${FIXTURE_JOB}/validation`} label="✓ Validation" />
          <QuickLink href={`/jobs/${FIXTURE_JOB}/review`} label="◎ Review" />
          <QuickLink href={`/jobs/${FIXTURE_JOB}/release`} label="⬆ Release" />
        </div>
      </section>

      {/* Task status summary */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-300">Trạng thái task EX-PRODUCT</h2>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 text-xs">
          {[
            { id: "PRODUCT-01", name: "Mock-First API", status: "IN_PROGRESS" },
            { id: "PRODUCT-02", name: "Job State Machine", status: "DONE" },
            { id: "PRODUCT-03", name: "Worker Abstraction", status: "TODO" },
            { id: "PRODUCT-04", name: "Artifact Registry", status: "TODO" },
            { id: "PRODUCT-05", name: "Web Shell", status: "DONE" },
            { id: "PRODUCT-06", name: "3D Viewer", status: "IN_PROGRESS" },
            { id: "PRODUCT-07", name: "Object Actions", status: "IN_PROGRESS" },
            { id: "PRODUCT-07A", name: "Obstacle/Collider UI", status: "IN_PROGRESS" },
            { id: "PRODUCT-08", name: "Real Worker Orch.", status: "TODO" },
            { id: "PRODUCT-09", name: "Progress/Error UI", status: "IN_PROGRESS" },
            { id: "PRODUCT-10", name: "Review Lifecycle", status: "IN_PROGRESS" },
            { id: "PRODUCT-11", name: "Exact Release", status: "IN_PROGRESS" },
            { id: "PRODUCT-12", name: "Demo Route", status: "IN_PROGRESS" },
          ].map((task) => (
            <div
              key={task.id}
              className="flex items-center justify-between rounded-lg border border-slate-800 px-3 py-2"
            >
              <span className="font-mono text-[10px] text-slate-500">{task.id}</span>
              <span className="text-slate-300">{task.name}</span>
              <StatusBadge status={task.status} />
            </div>
          ))}
        </div>
        <p className="mt-4 text-[10px] text-slate-700">
          AC-11 (3DGS render) chờ REC-04 · PRODUCT-08 chờ real workers · release backend là fake stub.
        </p>
      </section>
    </>
  );
}

function QuickLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-all"
    >
      {label}
    </Link>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    DONE: "bg-emerald-900/60 text-emerald-400",
    IN_PROGRESS: "bg-sky-900/60 text-sky-400",
    TODO: "bg-slate-800 text-slate-600",
    BLOCKED: "bg-rose-900/60 text-rose-400",
  };
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${styles[status] ?? styles.TODO}`}
    >
      {status}
    </span>
  );
}
