import { LandingAnchors } from "@/features/landing/LandingAnchors";
import { LandingHeader } from "@/features/landing/LandingHeader";
import { LandingSamples } from "@/features/landing/LandingSamples";
import { HeroScene } from "@/features/landing/HeroScene";
import { StatusTag } from "@/features/landing/StatusTag";
import {
  FOOTER,
  HERO,
  PROBLEM,
  PROGRESS,
  ROADMAP,
  SOLUTION,
  START,
  WORKFLOW,
} from "@/features/landing/content";
import { STUDIO_LOGIN_URL, STUDIO_URL } from "@/lib/api";

const LOGIN_HREF = STUDIO_LOGIN_URL;
const TRY_DEMO_HREF = `${STUDIO_URL}/new/try-demo`;

/**
 * Landing Real2Sim Studio, theo mạch Homematch:
 * Bài toán → Giải pháp → Quy trình → Tiến độ (bằng chứng) → Định hướng → Bắt đầu.
 * Chữ nằm ở `content.ts`. Trang render phía server; chỉ header (menu mobile)
 * và danh sách scene mẫu (gọi API) là client component.
 */
export function LandingPage() {
  return (
    <main id="landing-top" className="landing-page">
      <LandingAnchors />
      <LandingHeader tryDemoHref={TRY_DEMO_HREF} />

      {/* ── HERO ── */}
      <section className="lp-hero">
        <div className="lp-wrap grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:items-center">
          <div>
            <p className="lp-kicker">{HERO.eyebrow}</p>
            <h1 className="lp-display mt-5">
              {HERO.titleLead}
              <span className="block text-ember-strong">{HERO.titleEmphasis}</span>
            </h1>
            <p className="lp-lead mt-6">{HERO.lead}</p>
            <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-muted">{HERO.note}</p>

            <div className="mt-9 flex flex-wrap gap-3">
              <a href={TRY_DEMO_HREF} className="lp-btn lp-btn-primary">
                Thử scene mẫu
              </a>
              <a href={LOGIN_HREF} className="lp-btn lp-btn-ghost">
                Đăng nhập Studio
              </a>
            </div>

            <ul className="mt-10 grid gap-3 border-t border-line pt-6 sm:grid-cols-3">
              {HERO.benefits.map((b) => (
                <li key={b} className="flex gap-2.5 text-[14px] leading-snug text-ink">
                  <span aria-hidden className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ember-strong" />
                  {b}
                </li>
              ))}
            </ul>
          </div>

          <HeroScene />
        </div>
      </section>

      {/* ── 01 BÀI TOÁN ── */}
      <section id="problem" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={PROBLEM.index} lead={PROBLEM.titleLead} emphasis={PROBLEM.titleEmphasis} body={PROBLEM.lead} />

          <ol className="mt-14 grid gap-px overflow-hidden rounded-xl border border-line bg-line lg:grid-cols-3">
            {PROBLEM.personas.map((p) => (
              <li key={p.role} className="relative flex flex-col bg-paper-raised p-7 sm:p-8">
                <p className="lp-label">{p.tag}</p>
                <h3 className="mt-1 text-xl font-bold tracking-tight text-ink">{p.role}</h3>
                <p className="mt-6 text-[1.75rem] font-extrabold leading-none tracking-tight text-ember-strong">{p.highlight}</p>
                <p className="mt-2 text-[14px] leading-snug text-ink-muted">{p.highlightNote}</p>
                <ul className="mt-6 space-y-2.5 border-t border-line pt-5">
                  {p.pains.map((pain) => (
                    <li key={pain} className="flex gap-3 text-[15px] leading-snug text-ink">
                      <span aria-hidden className="mt-2 h-px w-3 shrink-0 bg-ink-muted" />
                      {pain}
                    </li>
                  ))}
                </ul>
                <p className="mt-auto pt-7 font-mono text-[12px] text-ink-muted">
                  {p.handoff}
                  <span aria-hidden className="lp-handoff-arrow" />
                </p>
              </li>
            ))}
          </ol>

          <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {PROBLEM.rootCauses.map((c) => (
              <div key={c.title} className="border-l-2 border-rust pl-4">
                <h3 className="text-[15px] font-bold text-ink">{c.title}</h3>
                <p className="mt-1.5 text-[14px] leading-relaxed text-ink-muted">{c.body}</p>
              </div>
            ))}
          </div>

          <p className="mt-10 max-w-3xl text-[13px] leading-relaxed text-ink-muted">{PROBLEM.footnote}</p>
        </div>
      </section>

      {/* ── 02 GIẢI PHÁP ── */}
      <section id="solution" className="lp-section bg-paper-sunken">
        <div className="lp-wrap">
          <SectionHead index={SOLUTION.index} lead={SOLUTION.titleLead} emphasis={SOLUTION.titleEmphasis} body={SOLUTION.lead} />

          <div className="mt-14 grid gap-10 lg:grid-cols-3 lg:gap-8">
            {SOLUTION.columns.map((c) => (
              <article key={c.title} className="flex flex-col">
                <p className="lp-label">{c.for}</p>
                <h3 className="mt-1 text-xl font-bold tracking-tight text-ink">{c.title}</h3>
                <ul className="mt-5 space-y-3">
                  {c.points.map((pt) => (
                    <li key={pt} className="flex gap-3 text-[15px] leading-snug text-ink">
                      <CheckIcon />
                      {pt}
                    </li>
                  ))}
                </ul>
                <p className="mt-auto pt-6 text-[14px] font-semibold text-sage">{c.outcome}</p>
              </article>
            ))}
          </div>

          {/* Ba lớp biểu diễn: xếp chồng như các lớp của một scene */}
          <div className="mt-16 grid gap-10 rounded-2xl bg-viewport p-6 text-on-dark sm:p-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center">
            <div>
              <h3 className="text-2xl font-extrabold tracking-tight">Một vật, ba lớp, một transform.</h3>
              <p className="mt-3 max-w-md text-[15px] leading-relaxed text-on-dark/70">{SOLUTION.layersNote}</p>
              <p className="mt-8 text-[13px] text-on-dark/60">Những chỗ con người quyết định</p>
              <ul className="mt-3 flex flex-wrap gap-2">
                {SOLUTION.checkpoints.map((c) => (
                  <li key={c} className="rounded-md border border-line-dark px-3 py-1.5 text-[13px] font-medium">
                    {c}
                  </li>
                ))}
              </ul>
            </div>
            <ol className="lp-layers">
              {SOLUTION.layers.map((l) => (
                <li key={l.code} className="lp-layer" data-tone={l.tone}>
                  <span className="font-mono text-[12px] font-semibold">{l.code}</span>
                  <span className="mt-1 block text-[15px] font-bold">{l.question}</span>
                  <span className="mt-1 block text-[14px] leading-snug text-on-dark/70">{l.answer}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ── 03 QUY TRÌNH ── */}
      <section id="workflow" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={WORKFLOW.index} lead={WORKFLOW.titleLead} emphasis={WORKFLOW.titleEmphasis} body={WORKFLOW.lead} />

          <ol className="lp-timeline mt-14">
            {WORKFLOW.steps.map((s) => (
              <li key={s.code} className="lp-step" data-status={s.status}>
                <span className="lp-step-dot" aria-hidden>{s.code}</span>
                <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_14rem] md:gap-10">
                  <div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      <h3 className="text-lg font-bold tracking-tight text-ink">{s.title}</h3>
                      <span className="font-mono text-[12px] text-ink-muted">{s.actor}</span>
                      <StatusTag status={s.status} />
                    </div>
                    <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-muted">{s.body}</p>
                    {s.image ? (
                      // eslint-disable-next-line @next/next/no-img-element -- ảnh tĩnh, trang có thể xuất static
                      <img src={s.image} alt={`Studio, bước ${s.title}`} loading="lazy" className="mt-4 w-full max-w-2xl rounded-lg border border-line" />
                    ) : null}
                  </div>
                  <div className="md:border-l md:border-line md:pl-5">
                    <p className="text-[12px] text-ink-muted">Kết quả</p>
                    <p className="mt-0.5 text-[15px] font-semibold text-ink">{s.output}</p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── 04 TIẾN ĐỘ ── */}
      <section id="progress" className="lp-section bg-paper-sunken">
        <div className="lp-wrap">
          <SectionHead index={PROGRESS.index} lead={PROGRESS.titleLead} emphasis={PROGRESS.titleEmphasis} body={PROGRESS.lead} />

          <div className="mt-14 grid gap-px overflow-hidden rounded-xl border border-line bg-line lg:grid-cols-3">
            {PROGRESS.tiers.map((t) => (
              <div key={t.title} className="bg-paper-raised p-7 sm:p-8">
                <StatusTag status={t.status} />
                <h3 className="mt-4 text-xl font-bold tracking-tight text-ink">{t.title}</h3>
                <ul className="mt-4 space-y-2.5">
                  {t.items.map((it) => (
                    <li key={it} className="flex gap-3 text-[15px] leading-snug text-ink">
                      <span aria-hidden className="mt-2 h-px w-3 shrink-0 bg-ink-muted" />
                      {it}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-12">
            <h3 className="text-lg font-bold text-ink">{PROGRESS.metricsTitle}</h3>
            <dl className="mt-4 grid gap-x-8 gap-y-5 border-t border-line pt-5 sm:grid-cols-2 lg:grid-cols-4">
              {PROGRESS.metrics.map((m) => (
                <div key={m.group}>
                  <dt className="text-[13px] text-ink-muted">{m.group}</dt>
                  <dd className="mt-1 text-[15px] font-medium leading-snug text-ink">{m.items}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-5 text-[13px] text-ink-muted">{PROGRESS.metricsNote}</p>
          </div>

          <LandingSamples title={PROGRESS.samplesTitle} lead={PROGRESS.samplesLead} studioUrl={STUDIO_URL} />
        </div>
      </section>

      {/* ── 05 DÙNG Ở ĐÂU ── */}
      <section id="roadmap" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={ROADMAP.index} lead={ROADMAP.titleLead} emphasis={ROADMAP.titleEmphasis} body={ROADMAP.lead} />

          <div className="mt-14 grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)] lg:items-stretch">
            <div className="flex flex-col justify-center rounded-xl bg-viewport p-6 text-on-dark">
              <p className="text-lg font-extrabold tracking-tight">{ROADMAP.core}</p>
              <ul className="mt-4 space-y-2">
                {ROADMAP.adapters.map((a) => (
                  <li key={a} className="rounded-md border border-line-dark px-3 py-2 font-mono text-[12px] text-on-dark/80">
                    {a}
                  </li>
                ))}
              </ul>
            </div>
            <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
              {ROADMAP.tracks.map((t) => {
                const borderBg =
                  t.state === "current"
                    ? "border-2 border-ember-strong bg-paper-raised"
                    : t.state === "partial"
                      ? "border border-line-strong bg-paper-raised"
                      : "border border-dashed border-line-strong";
                const tagColor =
                  t.state === "current"
                    ? "text-ember-strong"
                    : t.state === "partial"
                      ? "text-ink"
                      : "text-ink-muted";
                return (
                  <div
                    key={t.domain}
                    className={`rounded-xl p-6 sm:p-7 ${borderBg}`}
                  >
                    <p className={`text-[13px] font-semibold ${tagColor}`}>{t.tag}</p>
                    <p className="mt-3 text-xl font-bold tracking-tight text-ink">{t.domain}</p>
                    <p className="mt-1 font-mono text-[13px] text-ink-muted">↳ {t.simulator}</p>
                    <p className="mt-4 text-[15px] leading-relaxed text-ink-muted">{t.body}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ── BẮT ĐẦU ── */}
      <section id="start" className="lp-section bg-viewport text-on-dark">
        <div className="lp-wrap grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
          <div>
            <h2 className="lp-h2 text-on-dark">
              {START.titleLead}
              <span className="block text-on-dark/60">{START.titleEmphasis}</span>
            </h2>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href={TRY_DEMO_HREF} className="lp-btn lp-btn-primary">
                Thử scene mẫu
              </a>
              <a href={LOGIN_HREF} className="lp-btn lp-btn-ghost-dark">
                Đăng nhập Studio
              </a>
            </div>
          </div>
          <ol className="space-y-px overflow-hidden rounded-xl border border-line-dark">
            {START.steps.map((s, i) => (
              <li key={s.title} className="flex gap-4 bg-viewport-deep p-5">
                <span className="font-mono text-[13px] font-semibold text-ember">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <p className="text-[15px] font-bold">{s.title}</p>
                  <p className="mt-1 text-[14px] leading-relaxed text-on-dark/70">{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer className="border-t border-line py-10">
        <div className="lp-wrap flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[15px] font-bold text-ink">Real2Sim Studio</p>
            <p className="mt-1 max-w-sm text-[14px] text-ink-muted">{FOOTER.tagline}</p>
            <p className="mt-4 text-[13px] text-ink-muted">{FOOTER.team}</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[14px] text-ink-muted">
            <a href={FOOTER.github} target="_blank" rel="noreferrer" className="lp-link">
              Mã nguồn trên GitHub
            </a>
            <span>{FOOTER.license}</span>
          </div>
        </div>
      </footer>
    </main>
  );
}

function SectionHead({ index, lead, emphasis, body }: { index: string; lead: string; emphasis: string; body: string }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:items-end">
      <div>
        <p className="lp-index">{index}</p>
        <h2 className="lp-h2 mt-3 text-ink">
          {lead}
          <span className="block text-ink-muted">{emphasis}</span>
        </h2>
      </div>
      <p className="max-w-xl text-[16px] leading-relaxed text-ink-muted">{body}</p>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className="mt-[3px] h-4 w-4 shrink-0 text-sage" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 8.5l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
