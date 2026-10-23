"use client";

import { ArrowRight, ChevronDown } from "lucide-react";
import Image from "next/image";
import { useSyncExternalStore } from "react";

import { LandingAnchors } from "@/features/landing/LandingAnchors";
import { LandingHeader } from "@/features/landing/LandingHeader";
import { LandingMotion } from "@/features/landing/LandingMotion";
import { LandingSamples } from "@/features/landing/LandingSamples";
import { RotatingText } from "@/features/landing/RotatingText";
import { CompareScene } from "@/features/landing/CompareScene";
import { HeroScene } from "@/features/landing/HeroScene";
import { StatusTag } from "@/features/landing/StatusTag";
import {
  getContent,
  getUiLabels,
  type TrackState,
} from "@/features/landing/content";
import { STUDIO_LOGIN_URL, STUDIO_URL } from "@/lib/api";
import { currentLanguage, subscribeLanguage, type Language } from "@/lib/i18n";

const LOGIN_HREF = STUDIO_LOGIN_URL;

const TRACK_CARD: Record<TrackState, string> = {
  current: "lp-card lp-card-featured",
  partial: "lp-card",
  later: "lp-card lp-card-dashed",
};
const TRY_DEMO_HREF = `${STUDIO_URL}/new/try-demo`;

const serverLang = (): Language => "vi";

/**
 * Landing Real2Sim Studio, theo mạch Homematch:
 * Bối cảnh → Bài toán → Giải pháp → Quy trình → Tiến độ (bằng chứng) → Dùng ở đâu → Bắt đầu.
 * Chữ nằm ở `content.ts`, hỗ trợ song ngữ Tiếng Việt và Tiếng Anh.
 */
export function LandingPage() {
  const lang = useSyncExternalStore(subscribeLanguage, currentLanguage, serverLang);
  const content = getContent(lang);
  const ui = getUiLabels(lang);

  const {
    CONTEXT,
    FOOTER,
    HERO,
    HERO_CHAIN,
    PROBLEM,
    PROGRESS,
    ROADMAP,
    SOLUTION,
    START,
    WORKFLOW,
    STATUS_LABEL,
  } = content;

  return (
    <main id="landing-top" className="landing-page">
      <LandingAnchors />
      <LandingMotion />
      <LandingHeader tryDemoHref={TRY_DEMO_HREF} studioHref={LOGIN_HREF} />

      {/* ── HERO ── */}
      <section className="lp-hero">
        <div className="lp-hero-bg" aria-hidden />
        <div className="lp-hero-shade" aria-hidden />
        <svg className="lp-ribbons" viewBox="0 0 1600 900" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id="lp-rg1" x1="0" x2="1">
              <stop offset="0" stopColor="var(--lp-primary)" stopOpacity="0" />
              <stop offset="0.5" stopColor="var(--lp-primary)" />
              <stop offset="1" stopColor="var(--lp-ok)" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="lp-rg2" x1="0" x2="1">
              <stop offset="0" stopColor="var(--lp-accent)" stopOpacity="0" />
              <stop offset="0.5" stopColor="var(--lp-accent)" />
              <stop offset="1" stopColor="var(--lp-warn)" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="lp-rg3" x1="0" x2="1">
              <stop offset="0" stopColor="var(--lp-ok)" stopOpacity="0" />
              <stop offset="0.5" stopColor="var(--lp-fg)" />
              <stop offset="1" stopColor="var(--lp-primary)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path className="r1" d="M -100 650 C 300 450, 700 900, 1100 600 S 1500 300, 1750 450" />
          <path className="r2" d="M -100 300 C 400 100, 600 500, 1000 350 S 1400 150, 1750 250" />
          <path className="r3" d="M -100 760 C 500 600, 800 820, 1200 700 S 1500 600, 1750 680" />
        </svg>

        <div className="lp-wrap lp-hero-inner">
          <div className="lp-hero-mark" aria-hidden>
            <Image src="/icon.svg" alt="" width={40} height={40} />
          </div>
          <p className="lp-kicker">{HERO.eyebrow}</p>
          <h1 className="lp-display">
            <span className="lp-gradient">{HERO.titleLead}</span> {HERO.titleEmphasis}
          </h1>
          <RotatingText items={HERO.benefits} />
          <p className="lp-lead">{HERO.lead}</p>
          <p className="lp-body">{HERO.note}</p>
          <div className="lp-hero-cta">
            <a href={TRY_DEMO_HREF} className="lp-btn lp-btn-primary">
              {ui.tryDemo}
              <ArrowRight aria-hidden />
            </a>
            <a href={LOGIN_HREF} className="lp-btn lp-btn-ghost">
              {ui.loginStudio}
            </a>
          </div>
          <div className="lp-viewport-tilt">
            <HeroScene hero={HERO} heroChain={HERO_CHAIN} lang={lang} />
          </div>
          <a href="#context" className="lp-scroll-cue">
            {ui.explore}
            <ChevronDown aria-hidden />
          </a>
        </div>
      </section>

      {/* ── 01 BỐI CẢNH ── */}
      <section id="context" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={CONTEXT.index} lead={CONTEXT.titleLead} emphasis={CONTEXT.titleEmphasis} body={CONTEXT.lead} />

          <ol className="lp-flow lp-section-sub" data-reveal>
            {CONTEXT.steps.map((s, i) => (
              <li key={s.title} className="lp-flow-step">
                <span className="lp-flow-num">{String(i + 1).padStart(2, "0")}</span>
                <h3 className="lp-h3 mt-4">{s.title}</h3>
                <p className="lp-body mt-2">{s.body}</p>
              </li>
            ))}
          </ol>

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{CONTEXT.waysTitle}</h3>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              {CONTEXT.ways.map((w, i) => (
                <div key={w.name} className={i === 1 ? "lp-card lp-card-featured" : "lp-card"} data-reveal style={{ "--lp-delay": `${i * 100}ms` } as React.CSSProperties}>
                  <p className="text-[17px] font-semibold text-ink">{w.name}</p>
                  <p className="mt-1 text-[14px] text-ink-subtle">{w.verdict}</p>
                  <p className="lp-body mt-4">{w.body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── 02 BÀI TOÁN ── */}
      <section id="problem" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={PROBLEM.index} lead={PROBLEM.titleLead} emphasis={PROBLEM.titleEmphasis} body={PROBLEM.lead} />

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{PROBLEM.analogy.title}</h3>
            <div className="mt-5">
              <CompareScene analogy={PROBLEM.analogy} lang={lang} />
            </div>
          </div>

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{PROBLEM.issuesTitle}</h3>
            <ul className="lp-issues mt-6">
              {PROBLEM.issues.map((c, i) => (
                <li key={c.title} className="lp-issue" data-reveal style={{ "--lp-delay": `${i * 90}ms` } as React.CSSProperties}>
                  <h4 className="text-[16px] font-semibold text-ink">{c.title}</h4>
                  <p className="lp-body mt-2 text-[14px]">{c.body}</p>
                  <p className="mt-3 text-[14px] leading-snug text-ink">
                    <span className="text-ink-subtle">{ui.consequence}</span>
                    {c.effect}
                  </p>
                </li>
              ))}
            </ul>
            <p className="lp-consequence mt-14" data-reveal>{PROBLEM.consequence}</p>
          </div>

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{PROBLEM.personasTitle}</h3>
            <ol className="lp-cells mt-6 lg:grid-cols-3">
              {PROBLEM.personas.map((p) => (
                <li key={p.role} className="lp-cell">
                  <p className="lp-label">{p.tag}</p>
                  <h4 className="mt-1 text-xl font-semibold tracking-tight text-ink">{p.role}</h4>
                  <p className="mt-6 text-[1.5rem] font-semibold leading-tight tracking-tight text-ink">{p.highlight}</p>
                  <p className="lp-body mt-2 text-[14px]">{p.highlightNote}</p>
                  <ul className="lp-list mt-6 border-t border-line pt-5">
                    {p.pains.map((pain) => (
                      <li key={pain}>{pain}</li>
                    ))}
                  </ul>
                  <p className="mt-auto pt-7 text-[13px] text-ink-subtle">{p.handoff}</p>
                </li>
              ))}
            </ol>
            <p className="mt-8 max-w-3xl text-[13px] leading-relaxed text-ink-subtle">{PROBLEM.footnote}</p>
          </div>
        </div>
      </section>

      {/* ── 03 GIẢI PHÁP ── */}
      <section id="solution" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={SOLUTION.index} lead={SOLUTION.titleLead} emphasis={SOLUTION.titleEmphasis} body={SOLUTION.lead} />

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{SOLUTION.mapTitle}</h3>
            <ol className="lp-map mt-6">
              {SOLUTION.map.map((m) => (
                <li key={m.problem} className="lp-map-row">
                  <p className="text-[15px] font-medium text-ink-muted">{m.problem}</p>
                  <p className="text-[15px] leading-snug text-ink">{m.answer}</p>
                  <div className="lp-map-status">
                    <StatusTag status={m.status} label={STATUS_LABEL[m.status]} />
                  </div>
                </li>
              ))}
            </ol>
            <div className="mt-6 max-w-3xl">
              <p className="text-[15px] font-semibold text-ink">{SOLUTION.extra.title}</p>
              <p className="lp-body mt-1.5">{SOLUTION.extra.body}</p>
            </div>
          </div>

          <div className="lp-section-sub grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]" data-reveal>
            <div className="lp-card lp-card-dashed">
              <p className="lp-label">{SOLUTION.contribution.notTitle}</p>
              <p className="lp-body mt-2">{SOLUTION.contribution.not}</p>
            </div>
            <div className="lp-card lp-card-featured">
              <p className="lp-label text-ink">{SOLUTION.contribution.isTitle}</p>
              <p className="mt-2 text-[17px] font-medium leading-snug text-ink">{SOLUTION.contribution.is}</p>
            </div>
          </div>

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{SOLUTION.columnsTitle}</h3>
            <div className="mt-6 grid gap-10 lg:grid-cols-3 lg:gap-8">
              {SOLUTION.columns.map((c) => (
                <article key={c.title} className="flex flex-col border-t border-line-strong pt-5">
                  <p className="lp-label">{c.for}</p>
                  <h4 className="mt-1 text-xl font-semibold tracking-tight text-ink">{c.title}</h4>
                  <ul className="lp-list mt-5">
                    {c.points.map((pt) => (
                      <li key={pt}>{pt}</li>
                    ))}
                  </ul>
                  <p className="mt-auto pt-6 text-[14px] font-medium text-ink-muted">{c.outcome}</p>
                </article>
              ))}
            </div>
          </div>

          {/* Ba lớp biểu diễn: xếp chồng như các lớp của một scene */}
          <div className="lp-layers-block lp-section-sub" data-reveal>
            <div>
              <h3 className="text-2xl font-semibold tracking-tight text-ink">{ui.oneObjectThreeLayers}</h3>
              <p className="lp-body mt-3 max-w-md">{SOLUTION.layersNote}</p>
              <p className="lp-label mt-8">{ui.humanDecisions}</p>
              <ul className="lp-chips mt-3">
                {SOLUTION.checkpoints.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
            <ol className="lp-layers">
              {SOLUTION.layers.map((l) => (
                <li key={l.code} className="lp-layer" data-tone={l.tone}>
                  <span className="lp-layer-code">{l.code}</span>
                  <span className="mt-1 block text-[15px] font-semibold text-ink">{l.question}</span>
                  <span className="lp-body mt-1 block text-[14px]">{l.answer}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ── 04 QUY TRÌNH ── */}
      <section id="workflow" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={WORKFLOW.index} lead={WORKFLOW.titleLead} emphasis={WORKFLOW.titleEmphasis} body={WORKFLOW.lead} />

          <ol className="lp-timeline lp-section-sub" data-reveal>
            {WORKFLOW.steps.map((s) => (
              <li key={s.code} className="lp-step" data-status={s.status}>
                <span className="lp-step-dot" aria-hidden>{s.code}</span>
                <div className="lp-step-grid">
                  <div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      <h3 className="lp-h3">{s.title}</h3>
                      <span className="text-[13px] text-ink-subtle">{s.actor}</span>
                      <StatusTag status={s.status} label={STATUS_LABEL[s.status]} />
                    </div>
                    <p className="lp-body mt-2 max-w-2xl">{s.body}</p>
                    {s.image ? (
                      // eslint-disable-next-line @next/next/no-img-element -- ảnh tĩnh, trang có thể xuất static
                      <img src={s.image} alt={`Studio, ${ui.step} ${s.title}`} loading="lazy" className="lp-step-shot" />
                    ) : null}
                  </div>
                  <div className="lp-step-result">
                    <p className="lp-label">{ui.result}</p>
                    <p className="mt-0.5 text-[15px] font-medium text-ink">{s.output}</p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── 05 TIẾN ĐỘ ── */}
      <section id="progress" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={PROGRESS.index} lead={PROGRESS.titleLead} emphasis={PROGRESS.titleEmphasis} body={PROGRESS.lead} />

          <div className="lp-cells lp-section-sub lg:grid-cols-3" data-reveal>
            {PROGRESS.tiers.map((t) => (
              <div key={t.title} className="lp-cell">
                <div>
                  <StatusTag status={t.status} label={STATUS_LABEL[t.status]} />
                </div>
                <h3 className="mt-4 text-xl font-semibold tracking-tight text-ink">{t.title}</h3>
                <ul className="lp-list mt-5">
                  {t.items.map((it) => (
                    <li key={it}>{it}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="lp-section-sub" data-reveal>
            <h3 className="lp-h3">{PROGRESS.metricsTitle}</h3>
            <dl className="lp-metrics mt-5">
              {PROGRESS.metrics.map((m) => (
                <div key={m.group}>
                  <dt className="lp-label">{m.group}</dt>
                  <dd className="mt-1 text-[15px] font-medium leading-snug text-ink">{m.items}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-5 text-[13px] leading-relaxed text-ink-subtle">{PROGRESS.metricsNote}</p>
          </div>

          <LandingSamples
            title={PROGRESS.samplesTitle}
            lead={PROGRESS.samplesLead}
            studioUrl={STUDIO_URL}
            openLabel={ui.openSample}
          />
        </div>
      </section>

      {/* ── 06 DÙNG Ở ĐÂU ── */}
      <section id="roadmap" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={ROADMAP.index} lead={ROADMAP.titleLead} emphasis={ROADMAP.titleEmphasis} body={ROADMAP.lead} />

          <div className="lp-section-sub grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)]" data-reveal>
            <div className="lp-card lp-card-sunken flex flex-col justify-center">
              <p className="text-lg font-semibold tracking-tight text-ink">{ROADMAP.core}</p>
              <ul className="mt-4 space-y-2">
                {ROADMAP.adapters.map((a) => (
                  <li key={a} className="text-[14px] text-ink-muted">
                    {a}
                  </li>
                ))}
              </ul>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {ROADMAP.tracks.map((t, i) => (
                <div key={t.domain} className={TRACK_CARD[t.state]} data-reveal style={{ "--lp-delay": `${100 + i * 100}ms` } as React.CSSProperties}>
                  <p className="lp-label">{t.tag}</p>
                  <p className="mt-3 text-xl font-semibold tracking-tight text-ink">{t.domain}</p>
                  <p className="mt-1 text-[13px] text-ink-subtle">{t.simulator}</p>
                  <p className="lp-body mt-4">{t.body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── BẮT ĐẦU ── */}
      <section id="start" className="lp-section lp-start">
        <div className="lp-wrap">
          <div className="lp-start-card" data-reveal>
            <h2 className="lp-h2">
              {START.titleLead} <span className="lp-gradient">{START.titleEmphasis}</span>
            </h2>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <a href={TRY_DEMO_HREF} className="lp-btn lp-btn-on-dark">
                {ui.tryDemo}
                <ArrowRight aria-hidden />
              </a>
              <a href={LOGIN_HREF} className="lp-btn lp-btn-ghost-dark">
                {ui.loginStudio}
              </a>
            </div>
            <ol className="lp-start-steps">
              {START.steps.map((s, i) => (
                <li key={s.title}>
                  <span className="lp-start-num">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <p className="text-[15px] font-semibold">{s.title}</p>
                    <p className="mt-1 text-[14px] leading-relaxed text-on-dark/65">{s.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer className="border-t border-line py-10">
        <div className="lp-wrap flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[15px] font-semibold text-ink">Real2Sim Studio</p>
            <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-ink-muted">{FOOTER.tagline}</p>
            <p className="mt-4 text-[13px] text-ink-subtle">{FOOTER.team}</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[14px] text-ink-muted">
            <a href={FOOTER.github} target="_blank" rel="noreferrer" className="lp-link">
              {ui.sourceOnGithub}
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
    <div className="lp-section-head" data-reveal>
      <p className="lp-index">{index}</p>
      <h2 className="lp-h2">
        {lead} <span className="lp-gradient">{emphasis}</span>
      </h2>
      <p>{body}</p>
    </div>
  );
}
