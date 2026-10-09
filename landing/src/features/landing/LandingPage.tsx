"use client";

import { useSyncExternalStore } from "react";

import { LandingAnchors } from "@/features/landing/LandingAnchors";
import { LandingHeader } from "@/features/landing/LandingHeader";
import { LandingSamples } from "@/features/landing/LandingSamples";
import { CompareScene } from "@/features/landing/CompareScene";
import { HeroScene } from "@/features/landing/HeroScene";
import { StatusTag } from "@/features/landing/StatusTag";
import { getContent, getUiLabels } from "@/features/landing/content";
import { STUDIO_LOGIN_URL, STUDIO_URL } from "@/lib/api";
import { currentLanguage, subscribeLanguage, type Language } from "@/lib/i18n";

const LOGIN_HREF = STUDIO_LOGIN_URL;

const TRY_DEMO_HREF = `${STUDIO_URL}/new/try-demo`;

const serverLang = (): Language => "vi";

/**
 * Landing Real2Sim Studio: Hero → Bài toán → Scene mẫu → Quy trình → Cho ai → Tiến độ → Bắt đầu.
 * Chữ nằm ở `content.ts`, hỗ trợ song ngữ Tiếng Việt và Tiếng Anh.
 */
export function LandingPage() {
  const lang = useSyncExternalStore(subscribeLanguage, currentLanguage, serverLang);
  const content = getContent(lang);
  const ui = getUiLabels(lang);

  const { FOOTER, HERO, PROBLEM, PROGRESS, ROLES, SAMPLES, START, WORKFLOW, STATUS_LABEL } = content;

  return (
    <div id="landing-top" className="landing-page">
      <LandingAnchors />
      <LandingHeader tryDemoHref={TRY_DEMO_HREF} studioHref={LOGIN_HREF} />
      <main>

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

            <div className="mt-9 flex flex-wrap gap-3">
              <a href={TRY_DEMO_HREF} className="lp-btn lp-btn-primary">
                {ui.tryDemo}
              </a>
              <a href={LOGIN_HREF} className="lp-btn lp-btn-ghost">
                {ui.loginStudio}
              </a>
            </div>
            <p className="mt-3 text-[13px] text-ink-muted">{HERO.note}</p>

            <ul className="mt-10 grid gap-3 border-t border-line pt-6 sm:grid-cols-3">
              {HERO.benefits.map((b) => (
                <li key={b} className="flex gap-2.5 text-[14px] leading-snug text-ink">
                  <span aria-hidden className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ember-strong" />
                  {b}
                </li>
              ))}
            </ul>
          </div>

          <HeroScene hero={HERO} lang={lang} />
        </div>
      </section>

      {/* ── 01 BÀI TOÁN → CÁCH GỠ ── */}
      <section id="problem" className="lp-section bg-paper-sunken">
        <div className="lp-wrap">
          <SectionHead index={PROBLEM.index} lead={PROBLEM.titleLead} emphasis={PROBLEM.titleEmphasis} body={PROBLEM.lead} />

          <h3 className="mt-12 text-lg font-bold text-ink">{PROBLEM.analogy.title}</h3>
          <div className="mt-4">
            <CompareScene analogy={PROBLEM.analogy} lang={lang} />
          </div>

          <h3 className="mt-14 text-lg font-bold text-ink">{PROBLEM.issuesTitle}</h3>
          <p className="mt-1 text-[14px] text-ink-muted">{PROBLEM.issuesNote}</p>
          <ol className="lp-map mt-5">
            {PROBLEM.issues.map((m) => (
              <li key={m.title} className="lp-map-row">
                <div>
                  <p className="text-[15px] font-semibold text-ink">
                    <span aria-hidden className="mr-2 inline-block h-2 w-2 rounded-full bg-rust align-middle" />
                    {m.title}
                  </p>
                  <p className="mt-1 pl-4 text-[14px] leading-snug text-ink-muted">
                    {ui.consequence}
                    {m.effect}
                  </p>
                </div>
                <span aria-hidden className="lp-map-arrow" />
                <p className="text-[15px] leading-snug text-ink">{m.fix}</p>
                <div className="lp-map-status">
                  <StatusTag status={m.status} label={STATUS_LABEL[m.status]} />
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-6 max-w-3xl rounded-xl border border-line-strong bg-paper-raised p-5">
            <p className="text-[15px] font-bold text-ink">{PROBLEM.extra.title}</p>
            <p className="mt-1.5 text-[15px] leading-relaxed text-ink-muted">{PROBLEM.extra.body}</p>
          </div>
        </div>
      </section>

      {/* ── ẢNH MINH HOẠ SCENE (tạm, đến khi có scene mẫu thật) ── */}
      <LandingSamples
        title={SAMPLES.title}
        lead={SAMPLES.lead}
        badge={SAMPLES.badge}
        items={SAMPLES.items}
        href={TRY_DEMO_HREF}
        openLabel={ui.tryDemo}
      />

      {/* ── 02 QUY TRÌNH ── */}
      <section id="workflow" className="lp-section bg-paper-sunken">
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
                      <StatusTag status={s.status} label={STATUS_LABEL[s.status]} />
                    </div>
                    <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-muted">{s.body}</p>
                  </div>
                  <div className="md:border-l md:border-line md:pl-5">
                    <p className="text-[12px] text-ink-muted">{ui.result}</p>
                    <p className="mt-0.5 text-[15px] font-semibold text-ink">{s.output}</p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── 03 CHO AI ── */}
      <section id="roles" className="lp-section">
        <div className="lp-wrap">
          <SectionHead index={ROLES.index} lead={ROLES.titleLead} emphasis={ROLES.titleEmphasis} body={ROLES.lead} />

          <div className="mt-12 grid gap-10 lg:grid-cols-3 lg:gap-8">
            {ROLES.columns.map((c) => (
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
        </div>
      </section>

      {/* ── 04 TIẾN ĐỘ ── */}
      <section id="progress" className="lp-section bg-paper-sunken">
        <div className="lp-wrap">
          <SectionHead index={PROGRESS.index} lead={PROGRESS.titleLead} emphasis={PROGRESS.titleEmphasis} body={PROGRESS.lead} />

          <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-line bg-line lg:grid-cols-3">
            {PROGRESS.tiers.map((t) => (
              <div key={t.status} className="bg-paper-raised p-7 sm:p-8">
                <StatusTag status={t.status} label={STATUS_LABEL[t.status]} />
                <ul className="mt-5 space-y-2.5">
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

          <p className="mt-8 max-w-4xl text-[13px] leading-relaxed text-ink-muted">
            <span className="font-semibold text-ink">{PROGRESS.metricsTitle}: </span>
            {PROGRESS.metrics}
          </p>
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
                {ui.tryDemo}
              </a>
              <a href={LOGIN_HREF} className="lp-btn lp-btn-ghost-dark">
                {ui.loginStudio}
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

      </main>

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
              {ui.sourceOnGithub}
            </a>
            <span>{FOOTER.license}</span>
          </div>
        </div>
      </footer>
    </div>
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
