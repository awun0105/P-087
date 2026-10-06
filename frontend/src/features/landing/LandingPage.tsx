"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LandingAnchors } from "@/features/landing/LandingAnchors";
import { listSamples, getProcessingOptions } from "@/lib/api/studio";
import type { SampleSummary, ProcessingOptions } from "@/lib/contracts/studio";
import { STUDIO_ENTRY } from "@/lib/routes";

/**
 * Landing Page Real2Sim Studio — Phiên bản Tiếng Việt tối ưu hoá UI/UX kỹ thuật cao.
 * Tích hợp dữ liệu thời gian thực từ backend (video mẫu, năng lực máy trạm worker).
 */
export function LandingPage() {
  // Trạng thái dữ liệu thời gian thực từ backend
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [capability, setCapability] = useState<ProcessingOptions["capability"] | null>(null);
  const [presets, setPresets] = useState<ProcessingOptions["presets"] | null>(null);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const [isLoadingApi, setIsLoadingApi] = useState(true);

  // Trạng thái tương tác Viewport Cockpit & Mobile Navigation
  const [activeLayerMesh, setActiveLayerMesh] = useState(true);
  const [activeLayerCollider, setActiveLayerCollider] = useState(true);
  const [activeLayerTrajectory, setActiveLayerTrajectory] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    let active = true;
    async function fetchBackendData() {
      try {
        const [sampleRes, optionsRes] = await Promise.allSettled([
          listSamples(),
          getProcessingOptions(),
        ]);

        if (!active) return;
        let isSuccess = false;

        if (sampleRes.status === "fulfilled" && sampleRes.value.ok) {
          setSamples(sampleRes.value.data.samples);
          isSuccess = true;
        }

        if (optionsRes.status === "fulfilled" && optionsRes.value.ok) {
          setCapability(optionsRes.value.data.capability ?? null);
          setPresets(optionsRes.value.data.presets ?? null);
          isSuccess = true;
        }

        setApiConnected(isSuccess);
      } catch {
        if (active) setApiConnected(false);
      } finally {
        if (active) setIsLoadingApi(false);
      }
    }

    fetchBackendData();
    return () => {
      active = false;
    };
  }, []);

  return (
    <main
      id="landing-top"
      className="landing-page bg-[var(--studio-paper)] text-[var(--studio-ink)] selection:bg-[var(--studio-ember-soft)] selection:text-[var(--studio-ember-strong)]"
    >
      <LandingAnchors />

      {/* ── HEADER ĐIỀU HƯỚNG ── */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-[var(--studio-paper)]/90 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] transition-all">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 min-h-18 py-3 flex items-center justify-between gap-3">
          {/* Logo Brand */}
          <a href="#landing-top" className="flex items-center gap-3 group" aria-label="Real2Sim Studio Trang chủ">
            <div className="w-8 h-8 rounded-md bg-[var(--studio-viewport)] flex items-center justify-center p-1.5 shadow-sm border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)]">
              <svg viewBox="0 0 24 24" fill="none" className="w-full h-full" aria-hidden="true">
                <path d="M12 2L3 7L12 12L21 7L12 2Z" stroke="var(--studio-ember)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3 17L12 22L21 17" stroke="var(--studio-geometry)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3 12L12 17L21 12" stroke="var(--studio-ochre)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="font-bold tracking-tight text-lg text-[var(--studio-ink)]">Real2Sim</span>
              <span className="hidden min-[400px]:inline text-xs uppercase tracking-widest font-mono-tech px-1.5 py-0.5 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink-muted)] font-semibold border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                Studio
              </span>
            </div>
          </a>

          {/* Navigation Links Desktop */}
          <nav aria-label="Landing page sections" className="hidden xl:flex items-center gap-8 text-[14px] font-medium text-[var(--studio-ink-muted)]">
            <a href="#product" aria-label="Product" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Sản phẩm
            </a>
            <a href="#workflow" aria-label="Workflow" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Quy trình
            </a>
            <a href="#samples" aria-label="Samples" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Môi trường mẫu
            </a>
            <a href="#technology" aria-label="Technology" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Công nghệ
            </a>
            <a href="#evaluation" aria-label="Evaluation" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Đánh giá
            </a>
            <a href="#documentation" aria-label="Documentation" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Tài liệu
            </a>
          </nav>

          {/* Action CTAs Desktop & Mobile Toggle */}
          <div className="flex items-center gap-3">
            <div className="hidden sm:inline-flex text-xs font-mono-tech text-[var(--studio-ink-muted)] items-center gap-1.5 px-2 py-1 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--studio-sage)]"></span>
              <span>Bản xem kỹ thuật</span>
            </div>

            <Link
              href={STUDIO_ENTRY}
              aria-label="Open Studio"
              className="inline-flex items-center justify-center px-4 py-2 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm active:translate-y-px focus:outline-none focus:ring-2 focus:ring-[var(--studio-ember)] focus:ring-offset-2 focus:ring-offset-[var(--studio-paper)]"
            >
              <span>Vào Studio</span>
              <svg className="w-4 h-4 ml-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </Link>

            {/* Mobile Hamburger Button */}
            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="xl:hidden p-2 rounded-md text-[var(--studio-ink-muted)] hover:text-[var(--studio-ink)] hover:bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"
              aria-label="Mở menu điều hướng"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                {mobileMenuOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>
          </div>
        </div>

        {/* Mobile Navigation Drawer */}
        {mobileMenuOpen && (
          <div className="xl:hidden border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)] bg-[var(--studio-paper-raised)] px-6 py-4 space-y-3 font-medium text-sm text-[var(--studio-ink)]">
            <a href="#product" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Sản phẩm
            </a>
            <a href="#workflow" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Quy trình
            </a>
            <a href="#samples" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Môi trường mẫu
            </a>
            <a href="#technology" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Công nghệ
            </a>
            <a href="#evaluation" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Đánh giá chất lượng
            </a>
            <a href="#documentation" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Tài liệu kỹ thuật
            </a>
          </div>
        )}

        {/* Notice Bar */}
        <p className="border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] px-6 py-2 text-center text-xs text-[var(--studio-ink-muted)]">
          Bản xem trước kỹ thuật · Dữ liệu mẫu, chỉ số và trạng thái kiểm định kết nối với API backend Studio. Mở Studio để thao tác với scene thực tế.
        </p>
      </header>

      {/* ── 00 / HERO SECTION: TỪ HIỆN THỰC ĐẾN MÔ PHỎNG ── */}
      <section className="relative pt-16 pb-24 md:pt-24 md:pb-32 bg-grid-tech border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] overflow-hidden">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-8 items-center">
            {/* Left Hero Content */}
            <div className="lg:col-span-6 flex flex-col justify-center">
              {/* Telemetry Badge */}
              <div className="inline-flex flex-wrap items-center gap-2 px-3 py-1.5 rounded-md bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] w-fit mb-6 text-xs font-mono-tech text-[var(--studio-ink-muted)]">
                <span className="w-2 h-2 rounded-full bg-[var(--studio-geometry)] animate-pulse"></span>
                <span>TÁI TẠO KHÔNG GIAN 3D</span>
                <span className="text-[var(--studio-ink-muted)] opacity-40">|</span>
                <span className="text-[var(--studio-ink)] font-semibold">XE TỰ HÀNH & ROBOTICS</span>
              </div>

              {/* Live Worker Hardware Badge */}
              <div className="mb-4 inline-flex items-center gap-2 text-xs font-mono-tech px-2.5 py-1 rounded bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_15%,transparent)] text-[var(--studio-ink-muted)]">
                <span className={`w-2 h-2 rounded-full ${apiConnected ? "bg-[var(--studio-sage)]" : "bg-[var(--studio-ochre)]"}`}></span>
                {isLoadingApi ? (
                  <span>Đang kết nối backend worker...</span>
                ) : capability ? (
                  <span>
                    Máy trạm: <strong className="text-[var(--studio-ink)] font-medium">{capability.gpu_name}</strong> ({capability.vram_total_gb ?? 4} GB VRAM) • Trực tuyến
                  </span>
                ) : (
                  <span>Cụm máy trạm GPU sẵn sàng • Kết nối an toàn</span>
                )}
              </div>

              {/* Main Headline */}
              <h1 className="text-4xl sm:text-5xl lg:text-[3.75rem] font-extrabold tracking-tight text-[var(--studio-ink)] leading-[1.08] mb-6">
                Từ Hiện Thực
                <br />
                <span className="text-[var(--studio-ember-strong)]">đến Mô Phỏng.</span>
              </h1>

              {/* Value Proposition */}
              <p className="text-lg sm:text-xl font-medium text-[var(--studio-ink)] mb-4 leading-relaxed">
                Chuyển đổi video thực tế và dữ liệu LiDAR thành các scene 3D có cấu trúc, chỉnh sửa được và sẵn sàng mô phỏng vật lý.
              </p>

              <p className="text-base text-[var(--studio-ink-muted)] mb-8 leading-relaxed max-w-xl">
                Real2Sim Studio tái tạo các tuyến đường và kho bãi công nghiệp thành môi trường không gian 3D chính xác, cho phép kỹ sư khảo sát, biên tập và kiểm định toàn diện cho quy trình mô phỏng NVIDIA Isaac Sim và CARLA.
              </p>

              {/* CTAs */}
              <div className="flex flex-wrap items-center gap-4 mb-10">
                <Link
                  href={STUDIO_ENTRY}
                  aria-label="Open Studio"
                  className="px-6 py-3.5 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm flex items-center gap-2 group"
                >
                  <span>Mở Studio</span>
                  <svg className="w-4 h-4 transform group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </Link>

                <a
                  href="#workflow"
                  className="px-6 py-3.5 text-sm font-semibold text-[var(--studio-ink)] rounded-md bg-[var(--studio-paper-raised)] hover:bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] transition-all shadow-xs"
                >
                  Khám phá quy trình
                </a>

                <a
                  href="#samples"
                  className="px-4 py-3.5 text-sm font-mono-tech text-[var(--studio-ink-muted)] hover:text-[var(--studio-ink)] transition-colors flex items-center gap-1.5"
                >
                  <span className="text-[var(--studio-geometry)]">●</span>
                  <span>Môi trường mẫu ({samples.length > 0 ? `${samples.length} mẫu` : "Thực tế"})</span>
                </a>
              </div>

              {/* Quick Specs */}
              <div className="pt-6 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] grid grid-cols-3 gap-4">
                <div>
                  <div className="text-[11px] font-mono-tech uppercase text-[var(--studio-ink-muted)]">Định Dạng Đầu Vào</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] mt-0.5">ROS2 / pcap / MP4</div>
                </div>
                <div>
                  <div className="text-[11px] font-mono-tech uppercase text-[var(--studio-ink-muted)]">Độ Chuẩn Hình Học</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] mt-0.5">Lưới dưới cm + Hộp OBB</div>
                </div>
                <div>
                  <div className="text-[11px] font-mono-tech uppercase text-[var(--studio-ink-muted)]">Công Cụ Mô Phỏng</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] mt-0.5">Isaac Sim / CARLA</div>
                </div>
              </div>
            </div>

            {/* Right Hero: Cinematic Viewport Simulation */}
            <div className="lg:col-span-6 viewport-container">
              <div className="relative rounded-xl bg-[var(--studio-viewport)] border border-[var(--studio-ink)] shadow-2xl overflow-hidden p-1">
                {/* Viewport Top Bar */}
                <div className="px-4 py-2.5 bg-[var(--studio-viewport-deep)] flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-on-dark)_8%,transparent)]">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-rust)]"></span>
                    <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-ochre)]"></span>
                    <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-sage)]"></span>
                    <span className="ml-2 text-xs font-mono-tech text-[var(--studio-on-dark)]/60">VIEWPORT::KHO_CONG_NGHIEP_RUN_08</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[11px] font-mono-tech px-2 py-0.5 rounded bg-[var(--studio-geometry)]/20 text-[var(--studio-geometry)] border border-[var(--studio-geometry)]/30">
                      1.420.800 ĐIỂM
                    </span>
                    <span className="text-[11px] font-mono-tech px-2 py-0.5 rounded bg-[var(--studio-sage)]/20 text-[var(--studio-sage)] border border-[var(--studio-sage)]/30">
                      ĐÃ KIỂM ĐỊNH
                    </span>
                  </div>
                </div>

                {/* Viewport Screen */}
                <div className="relative h-[440px] w-full bg-[var(--studio-viewport)] bg-grid-dark flex items-center justify-center overflow-hidden">
                  {/* Metric Coordinates HUD */}
                  <div className="absolute top-4 right-4 z-20 flex flex-col items-center bg-[var(--studio-viewport-deep)]/90 backdrop-blur p-2 rounded border border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] font-mono-tech text-[10px]">
                    <div className="flex items-center gap-2 text-[var(--studio-ember)]">
                      <span>X</span>
                      <span className="text-[var(--studio-on-dark)]/60">+14.28m</span>
                    </div>
                    <div className="flex items-center gap-2 text-[var(--studio-sage)]">
                      <span>Y</span>
                      <span className="text-[var(--studio-on-dark)]/60">-03.11m</span>
                    </div>
                    <div className="flex items-center gap-2 text-[var(--studio-geometry)]">
                      <span>Z</span>
                      <span className="text-[var(--studio-on-dark)]/60">+00.42m</span>
                    </div>
                  </div>

                  {/* Interactive Layer Toggles HUD */}
                  <div className="absolute top-4 left-4 z-20 flex flex-col gap-1.5 font-mono-tech text-[11px]">
                    <button
                      type="button"
                      onClick={() => setActiveLayerMesh(!activeLayerMesh)}
                      className={`flex items-center gap-2 px-2 py-1 rounded transition-colors text-left border ${
                        activeLayerMesh
                          ? "bg-[var(--studio-viewport-deep)]/95 border-[var(--studio-geometry)]/50 text-[var(--studio-on-dark)]"
                          : "bg-[var(--studio-viewport-deep)]/40 border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-on-dark)]/40"
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-xs ${activeLayerMesh ? "bg-[var(--studio-geometry)]" : "bg-[var(--studio-ink-muted)]"}`}></span>
                      <span>Lưới bề mặt (Mesh)</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setActiveLayerCollider(!activeLayerCollider)}
                      className={`flex items-center gap-2 px-2 py-1 rounded transition-colors text-left border ${
                        activeLayerCollider
                          ? "bg-[var(--studio-viewport-deep)]/95 border-[var(--studio-ochre)]/50 text-[var(--studio-on-dark)]"
                          : "bg-[var(--studio-viewport-deep)]/40 border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-on-dark)]/40"
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-xs ${activeLayerCollider ? "bg-[var(--studio-ochre)]" : "bg-[var(--studio-ink-muted)]"}`}></span>
                      <span>Collider vật lý (Lồi)</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setActiveLayerTrajectory(!activeLayerTrajectory)}
                      className={`flex items-center gap-2 px-2 py-1 rounded transition-colors text-left border ${
                        activeLayerTrajectory
                          ? "bg-[var(--studio-viewport-deep)]/95 border-[var(--studio-ember)]/50 text-[var(--studio-ember)]"
                          : "bg-[var(--studio-viewport-deep)]/40 border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-on-dark)]/40"
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-xs ${activeLayerTrajectory ? "bg-[var(--studio-ember)] animate-pulse" : "bg-[var(--studio-ink-muted)]"}`}></span>
                      <span>Thực thể: Xe_Nang_AGV_02</span>
                    </button>
                  </div>

                  {/* SVG 3D Spatial Scene */}
                  <svg viewBox="0 0 680 440" className="w-full h-full z-10 p-4" aria-hidden="true">
                    <defs>
                      <linearGradient id="groundGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--studio-geometry)" stopOpacity="0.12" />
                        <stop offset="100%" stopColor="var(--studio-geometry)" stopOpacity="0.0" />
                      </linearGradient>

                      <pattern id="pts" width="16" height="16" patternUnits="userSpaceOnUse">
                        <circle cx="2" cy="2" r="0.9" fill="var(--studio-geometry)" opacity="0.45" />
                        <circle cx="10" cy="10" r="0.9" fill="var(--studio-geometry)" opacity="0.25" />
                      </pattern>
                    </defs>

                    {/* Ground Plane */}
                    <polygon points="340,110 630,240 340,390 50,240" fill="url(#groundGrad)" stroke="var(--studio-geometry)" strokeWidth="1.2" strokeOpacity="0.35" />
                    <polygon points="340,110 630,240 340,390 50,240" fill="url(#pts)" />

                    {/* Coordinate Origin Axes */}
                    <line x1="340" y1="250" x2="520" y2="330" stroke="var(--studio-ember)" strokeWidth="2" strokeOpacity="0.7" />
                    <line x1="340" y1="250" x2="160" y2="330" stroke="var(--studio-sage)" strokeWidth="2" strokeOpacity="0.7" />
                    <line x1="340" y1="250" x2="340" y2="150" stroke="var(--studio-geometry)" strokeWidth="2" strokeOpacity="0.7" />

                    {/* Metric Grid Ruler */}
                    <path d="M 230,290 L 450,210" stroke="var(--studio-on-dark)" strokeWidth="2.5" strokeDasharray="10 8" strokeOpacity="0.5" />
                    <path d="M 270,310 L 490,230" stroke="var(--studio-on-dark)" strokeWidth="1.5" strokeOpacity="0.25" />

                    {/* Point Cluster */}
                    {activeLayerMesh && (
                      <g fill="var(--studio-geometry)" opacity="0.75">
                        <circle cx="170" cy="210" r="1.5" />
                        <circle cx="175" cy="208" r="1.2" />
                        <circle cx="182" cy="212" r="1.6" />
                        <circle cx="190" cy="205" r="1.4" />
                        <circle cx="195" cy="209" r="1.2" />
                        <circle cx="205" cy="215" r="1.5" />
                        <circle cx="165" cy="216" r="1.3" />
                        <circle cx="178" cy="220" r="1.4" />
                        <circle cx="188" cy="218" r="1.5" />
                        <circle cx="490" cy="180" r="1.5" />
                        <circle cx="500" cy="178" r="1.2" />
                        <circle cx="510" cy="182" r="1.6" />
                        <circle cx="515" cy="175" r="1.4" />
                        <circle cx="525" cy="183" r="1.5" />
                        <circle cx="495" cy="186" r="1.3" />
                      </g>
                    )}

                    {/* Racks Structural Mesh */}
                    {activeLayerMesh && (
                      <g stroke="var(--studio-geometry)" strokeWidth="1.5" fill="none" opacity="0.85">
                        <line x1="140" y1="170" x2="140" y2="240" />
                        <line x1="190" y1="150" x2="190" y2="218" />
                        <line x1="240" y1="170" x2="240" y2="240" />
                        <line x1="190" y1="190" x2="190" y2="262" />
                        <polygon points="140,170 190,150 240,170 190,190" stroke="var(--studio-geometry)" strokeWidth="1.2" fill="var(--studio-geometry)" fillOpacity="0.08" />
                        <polygon points="140,205 190,185 240,205 190,225" stroke="var(--studio-geometry)" strokeWidth="1.2" fill="var(--studio-geometry)" fillOpacity="0.08" />
                        <polygon points="140,240 190,218 240,240 190,262" stroke="var(--studio-geometry)" strokeWidth="1.2" fill="var(--studio-geometry)" fillOpacity="0.08" />
                      </g>
                    )}

                    {/* Physical Convex Collider for Racks */}
                    {activeLayerCollider && (
                      <>
                        <g stroke="var(--studio-ochre)" strokeWidth="1.5" strokeDasharray="4 3" fill="var(--studio-ochre)" fillOpacity="0.06">
                          <polygon points="135,160 190,140 245,160 190,180" />
                          <polygon points="135,245 190,225 245,245 190,268" />
                          <line x1="135" y1="160" x2="135" y2="245" />
                          <line x1="190" y1="140" x2="190" y2="225" />
                          <line x1="245" y1="160" x2="245" y2="245" />
                          <line x1="190" y1="180" x2="190" y2="268" />
                        </g>
                        <text x="140" y="152" fill="var(--studio-ochre)" fontSize="10" fontFamily="monospace" fontWeight="bold">
                          COLLIDER::KE_HANG_01
                        </text>
                      </>
                    )}

                    {/* AGV Forklift Entity */}
                    <polygon points="310,230 370,205 420,225 360,252" fill="var(--studio-ember)" fillOpacity="0.18" stroke="var(--studio-ember)" strokeWidth="2" />
                    <polygon points="310,255 370,230 420,250 360,277" fill="var(--studio-ember)" fillOpacity="0.12" stroke="var(--studio-ember)" strokeWidth="2" />
                    <line x1="310" y1="230" x2="310" y2="255" stroke="var(--studio-ember)" strokeWidth="2" />
                    <line x1="370" y1="205" x2="370" y2="230" stroke="var(--studio-ember)" strokeWidth="2" />
                    <line x1="420" y1="225" x2="420" y2="250" stroke="var(--studio-ember)" strokeWidth="2" />
                    <line x1="360" y1="252" x2="360" y2="277" stroke="var(--studio-ember)" strokeWidth="2" />

                    {/* Kinematic Nodes */}
                    <circle cx="360" cy="277" r="3" fill="var(--studio-ember)" />
                    <circle cx="310" cy="255" r="3" fill="var(--studio-ember)" />
                    <circle cx="420" cy="250" r="3" fill="var(--studio-ember)" />
                    <circle cx="370" cy="230" r="3" fill="var(--studio-ember)" />

                    {/* Entity Tag Callout */}
                    <line x1="365" y1="210" x2="440" y2="150" stroke="var(--studio-ember)" strokeWidth="1.2" strokeDasharray="3 2" />
                    <circle cx="365" cy="210" r="4" fill="none" stroke="var(--studio-ember)" strokeWidth="1.8" />
                    <g transform="translate(440, 130)">
                      <rect width="170" height="42" rx="4" fill="var(--studio-viewport-deep)" stroke="var(--studio-ember)" strokeWidth="1.2" />
                      <text x="10" y="17" fill="var(--studio-on-dark)" fontSize="10" fontFamily="monospace" fontWeight="bold">
                        XE_NANG_PALLET_02
                      </text>
                      <text x="10" y="32" fill="var(--studio-sage)" fontSize="9" fontFamily="monospace">
                        DONG_HOC_HOP_LE [OK]
                      </text>
                    </g>

                    {/* Obstacle Box */}
                    {activeLayerCollider && (
                      <g>
                        <polygon points="460,250 510,230 550,248 500,270" fill="var(--studio-ochre)" fillOpacity="0.12" stroke="var(--studio-ochre)" strokeWidth="1.5" />
                        <polygon points="460,275 510,255 550,273 500,295" fill="var(--studio-ochre)" fillOpacity="0.08" stroke="var(--studio-ochre)" strokeWidth="1.5" />
                        <line x1="460" y1="250" x2="460" y2="275" stroke="var(--studio-ochre)" strokeWidth="1.5" />
                        <line x1="510" y1="230" x2="510" y2="255" stroke="var(--studio-ochre)" strokeWidth="1.5" />
                        <line x1="550" y1="248" x2="550" y2="273" stroke="var(--studio-ochre)" strokeWidth="1.5" />
                        <line x1="500" y1="270" x2="500" y2="295" stroke="var(--studio-ochre)" strokeWidth="1.5" />
                      </g>
                    )}

                    {/* LiDAR Trajectory Curve */}
                    {activeLayerTrajectory && (
                      <g>
                        <path d="M 280,330 Q 320,300 370,305 T 440,285" fill="none" stroke="var(--studio-geometry)" strokeWidth="2" strokeDasharray="4 3" />
                        <polygon points="310,312 322,314 316,324" fill="var(--studio-geometry)" />
                        <polygon points="390,298 402,296 398,308" fill="var(--studio-geometry)" />
                        <text x="315" y="338" fill="var(--studio-geometry)" fontSize="9" fontFamily="monospace">
                          QUỸ ĐẠO LiDAR (120 Hz)
                        </text>
                      </g>
                    )}
                  </svg>

                  {/* Viewport Bottom Status Bar */}
                  <div className="absolute bottom-3 inset-x-4 flex items-center justify-between z-20 font-mono-tech text-xs">
                    <div className="flex items-center gap-1.5 bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] rounded px-2.5 py-1 text-[var(--studio-on-dark)]/70">
                      <span className="text-[var(--studio-geometry)] font-bold">CHẾ ĐỘ:</span>
                      <span>KHẢO SÁT / BIÊN TẬP LƯỚI</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-on-dark)]/70 text-[10px]">
                        FOV: 65°
                      </span>
                      <span className="px-2 py-0.5 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-on-dark)]/70 text-[10px]">
                        FPS: 60.0
                      </span>
                      <span className="px-2 py-0.5 rounded bg-[var(--studio-sage)]/20 text-[var(--studio-sage)] border border-[var(--studio-sage)]/40 text-[10px] font-semibold">
                        SẴN SÀNG MÔ PHỎNG
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 01 / NÚT THẮT KHÔNG GIAN (THE SPATIAL BOTTLENECK) ── */}
      <section className="py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-16">
            <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
              01 / Nút Thắt Không Gian
            </div>
            <h2 className="text-3xl sm:text-4xl lg:text-[2.75rem] font-extrabold tracking-tight text-[var(--studio-ink)] leading-[1.15] mb-6">
              Hiện thực phong phú.
              <br />
              <span className="text-[var(--studio-ink-muted)]">Mô phỏng cần cấu trúc.</span>
            </h2>
            <p className="text-lg text-[var(--studio-ink-muted)] leading-relaxed">
              Video thực địa và đám mây điểm LiDAR dày đặc chứa đựng chân lý không gian chân thực. Tuy nhiên, việc chuyển đổi các bản quét thô chưa được tổ chức thành tài sản mô phỏng có căn cứ vật lý, chỉnh sửa được thường bị phân mảnh và tốn nhiều tuần xử lý thủ công.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Stage 01 */}
            <div className="p-8 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between shadow-xs">
              <div>
                <div className="flex items-center justify-between mb-6">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink-muted)] px-2 py-1 rounded bg-[var(--studio-paper-sunken)]">
                    GIAI ĐOẠN 01
                  </span>
                  <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-ink-muted)]"></span>
                </div>
                <h3 className="text-xl font-bold text-[var(--studio-ink)] mb-2 tracking-tight">THU THẬP</h3>
                <div className="text-sm font-semibold text-[var(--studio-geometry)] font-mono-tech mb-4">Video + LiDAR</div>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Dữ liệu ghi hình từ xe lái và thiết bị bay tạo ra tập điểm đồ sộ, méo quang học, điểm mù che khuất và dấu mốc thời gian rời rạc chưa có ngữ nghĩa.
                </p>
              </div>
              <div className="p-3.5 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs text-[var(--studio-ink)]/80">
                <span className="text-[var(--studio-ink-muted)]">Trạng thái thô:</span> Luồng pcap chưa tổ chức, khung hình rolling shutter, thiếu các đối tượng hình học độc lập.
              </div>
            </div>

            {/* Stage 02 */}
            <div className="p-8 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between shadow-xs">
              <div>
                <div className="flex items-center justify-between mb-6">
                  <span className="text-xs font-mono-tech text-[var(--studio-geometry)] px-2 py-1 rounded bg-[var(--studio-geometry)]/10 border border-[var(--studio-geometry)]/20">
                    GIAI ĐOẠN 02
                  </span>
                  <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-geometry)]"></span>
                </div>
                <h3 className="text-xl font-bold text-[var(--studio-ink)] mb-2 tracking-tight">TÁI TẠO</h3>
                <div className="text-sm font-semibold text-[var(--studio-geometry)] font-mono-tech mb-4">Hình Học + Cấu Trúc Không Gian</div>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Tự động căn chỉnh bundle adjustment, tái tạo bề mặt 3D Gaussian Splatting và phân tách mặt sàn để trích xuất bề mặt mét liên tục cùng tư thế camera chuẩn.
                </p>
              </div>
              <div className="p-3.5 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs text-[var(--studio-ink)]/80">
                <span className="text-[var(--studio-geometry)]">Đã giải quyết:</span> Lưới tam giác kín nước, căn chuẩn sai số dưới centimet, pháp tuyến bề mặt đồng nhất.
              </div>
            </div>

            {/* Stage 03 */}
            <div className="p-8 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ember-strong)]/40 transition-all flex flex-col justify-between shadow-xs">
              <div>
                <div className="flex items-center justify-between mb-6">
                  <span className="text-xs font-mono-tech text-[var(--studio-ember-strong)] px-2 py-1 rounded bg-[var(--studio-ember-soft)] border border-[var(--studio-ember-strong)]/20">
                    GIAI ĐOẠN 03
                  </span>
                  <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-ember-strong)]"></span>
                </div>
                <h3 className="text-xl font-bold text-[var(--studio-ink)] mb-2 tracking-tight">MÔ PHỎNG</h3>
                <div className="text-sm font-semibold text-[var(--studio-ember-strong)] font-mono-tech mb-4">Scene Biên Tập & Kiểm Định</div>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Tách rời tài sản tái tạo thành các thực thể vật lý độc lập có vỏ va chạm lồi, ràng buộc động học, lớp ngữ nghĩa và cấu trúc topo đã được thẩm định.
                </p>
              </div>
              <div className="p-3.5 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs text-[var(--studio-ink)]/80">
                <span className="text-[var(--studio-ember-strong)]">Đầu ra:</span> Gói USD, URDF, OpenSCENARIO sẵn sàng chạy trực tiếp trong solver vật lý.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 02 / QUY TRÌNH TOÀN DIỆN (END-TO-END PIPELINE) ── */}
      <section id="workflow" className="py-24 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row md:items-end justify-between mb-16 gap-6">
            <div>
              <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
                02 / Quy Trình Toàn Diện
              </div>
              <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)]">
                Một quy trình liền mạch từ thu thập đến mô phỏng.
              </h2>
            </div>
            <div className="flex items-center gap-4 text-xs font-mono-tech text-[var(--studio-ink-muted)]">
              <span className="inline-flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-xs bg-[var(--studio-ember)]"></span> Luồng xử lý
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-xs bg-[var(--studio-geometry)]"></span> Dữ liệu hình học
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-xs bg-[var(--studio-ochre)]"></span> Vật lý & Collider
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 relative">
            {/* Step 01 */}
            <div className="bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-xs relative flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]">
                  <span className="text-2xl font-mono-tech font-bold text-[var(--studio-ember)]">01</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-ink-muted)] bg-[var(--studio-paper-sunken)] px-2 py-0.5 rounded">
                    NẠP DỮ LIỆU
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">THU THẬP</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Nạp luồng dữ liệu thô từ cụm cảm biến xe tự hành hoặc robot công nghiệp với mốc thời gian đồng bộ.
                </p>
                <div className="space-y-2">
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Video</span>
                    <span className="text-[var(--studio-geometry)]">RGB 4K @ 60fps</span>
                  </div>
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">LiDAR</span>
                    <span className="text-[var(--studio-geometry)]">Gói 128 tia quét</span>
                  </div>
                </div>
              </div>
              <div className="mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                <span>Đồng bộ thời gian</span>
                <span className="text-[var(--studio-ember)] font-bold">→ Tiếp</span>
              </div>
            </div>

            {/* Step 02 */}
            <div className="bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-xs relative flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]">
                  <span className="text-2xl font-mono-tech font-bold text-[var(--studio-geometry)]">02</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-geometry)] bg-[var(--studio-geometry)]/10 px-2 py-0.5 rounded">
                    GIẢI TOÁN
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">TÁI TẠO 3D</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Trích xuất bề mặt hệ mét chuẩn xác, độ cong mặt sàn và quỹ đạo 6 bậc tự do (6-DoF) của camera.
                </p>
                <div className="space-y-2">
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Hình học</span>
                    <span className="text-[var(--studio-geometry)]">3DGS / TSDF Lưới</span>
                  </div>
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Tư thế camera</span>
                    <span className="text-[var(--studio-geometry)]">Khung SE(3)</span>
                  </div>
                </div>
              </div>
              <div className="mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                <span>Căn chuẩn tỉ lệ mét</span>
                <span className="text-[var(--studio-ember)] font-bold">→ Tiếp</span>
              </div>
            </div>

            {/* Step 03 */}
            <div className="bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-xs relative flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]">
                  <span className="text-2xl font-mono-tech font-bold text-[var(--studio-ochre)]">03</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-ochre)] bg-[var(--studio-ochre)]/10 px-2 py-0.5 rounded">
                    PHÂN TÁCH
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">XÂY DỰNG SCENE</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Tách biệt môi trường tĩnh khỏi vật cản động và gán vỏ bao va chạm vật lý tự động.
                </p>
                <div className="space-y-2">
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Đồ thị scene</span>
                    <span className="text-[var(--studio-ochre)]">USD Schema</span>
                  </div>
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Vật thể ngữ nghĩa</span>
                    <span className="text-[var(--studio-ochre)]">Vỏ lồi V-HACD</span>
                  </div>
                </div>
              </div>
              <div className="mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                <span>Vỏ va chạm vật lý</span>
                <span className="text-[var(--studio-ember)] font-bold">→ Tiếp</span>
              </div>
            </div>

            {/* Step 04 */}
            <div className="bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[var(--studio-ember-strong)]/40 shadow-sm relative flex flex-col justify-between">
              <div className="absolute -top-2.5 right-4 bg-[var(--studio-ember-strong)] text-on-accent text-[10px] font-mono-tech px-2 py-0.5 rounded font-bold">
                CHUẨN SẢN XUẤT
              </div>
              <div>
                <div className="flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]">
                  <span className="text-2xl font-mono-tech font-bold text-[var(--studio-sage)]">04</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-sage)] bg-[var(--studio-sage)]/10 px-2 py-0.5 rounded">
                    KIỂM ĐỊNH
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">XÁC MINH</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Chạy kiểm tra tự động giao cắt va chạm, tính hợp lệ của pháp tuyến và toàn vẹn đóng gói.
                </p>
                <div className="space-y-2">
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Gói mô phỏng</span>
                    <span className="text-[var(--studio-sage)]">USD / URDF</span>
                  </div>
                  <div className="px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                    <span className="text-[var(--studio-ink)] font-medium">Báo cáo kiểm định</span>
                    <span className="text-[var(--studio-sage)]">Đạt (0 cảnh báo)</span>
                  </div>
                </div>
              </div>
              <div className="mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                <span>Xuất cho Physics Solver</span>
                <span className="text-[var(--studio-sage)] font-bold">Sẵn sàng</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 03 / MÔI TRƯỜNG STUDIO & COCKPIT VIEWPORT ── */}
      <section id="product" className="py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-14">
            <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
              03 / Môi Trường Studio
            </div>
            <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4">
              Được thiết kế cho khảo sát không gian độ trung thực cao.
            </h2>
            <p className="text-base text-[var(--studio-ink-muted)]">
              Buồng lái hợp nhất dành riêng cho các nhóm phát triển xe tự hành và phòng nghiên cứu robotics. Khảo sát phân bố điểm thô, biên tập vỏ va chạm lồi và xuất gói mô phỏng chuẩn xác ngay trong trình duyệt.
            </p>
          </div>

          {/* Interactive Studio Cockpit Frame */}
          <div id="studio-viewport" className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start mb-16">
            <div className="lg:col-span-8 bg-[var(--studio-paper-raised)] rounded-xl border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] shadow-xl overflow-hidden">
              {/* Studio Window Bar */}
              <div className="h-12 bg-[var(--studio-paper-sunken)] px-4 flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-bold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2.5 h-2.5 bg-[var(--studio-ember-strong)] rounded-xs"></span>
                    SCENE_IR::GIAO_LO_DO_THI_4_NGA
                  </span>
                  <span className="text-[11px] font-mono-tech px-2 py-0.5 rounded bg-[var(--studio-paper-raised)] text-[var(--studio-ink-muted)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_15%,transparent)]">
                    GOI_TU_HANH_V2
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    className="px-2.5 py-1 text-xs font-mono-tech rounded bg-[var(--studio-paper-raised)] text-[var(--studio-ink)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] opacity-80 cursor-default"
                    type="button"
                  >
                    Tính toán lại lưới
                  </button>
                  <button
                    className="px-2.5 py-1 text-xs font-mono-tech rounded bg-[var(--studio-ember-strong)] text-on-accent font-semibold opacity-90 cursor-default"
                    type="button"
                  >
                    Xuất USD
                  </button>
                </div>
              </div>

              {/* Cockpit Content Split */}
              <div className="grid grid-cols-12 h-[520px]">
                {/* Scene Hierarchy Sidebar */}
                <div className="col-span-4 sm:col-span-3 bg-[var(--studio-paper-raised)] border-r border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] p-3 flex flex-col justify-between overflow-y-auto font-mono-tech text-xs">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-[var(--studio-ink-muted)] font-bold mb-2 pb-1 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]">
                      Cây Phân Cấp Scene
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-ink-muted)]">▾</span>
                        <span className="text-[var(--studio-geometry)]">■</span>
                        <span className="font-medium truncate">WorldRoot</span>
                      </div>
                      <div className="pl-3 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-ink-muted)]">▾</span>
                        <span className="text-[var(--studio-geometry)]">■</span>
                        <span className="truncate">DiaHinh_MatDat</span>
                      </div>
                      <div className="pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-geometry)]">●</span>
                        <span className="truncate">MatDuong_Nhua_01</span>
                      </div>
                      <div className="pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-ochre)]">▲</span>
                        <span className="truncate">GoDuong_Collider</span>
                      </div>
                      <div className="pl-3 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-ink-muted)]">▾</span>
                        <span className="text-[var(--studio-ember)]">■</span>
                        <span className="font-medium truncate">ThucThe_Dong</span>
                      </div>
                      <div className="pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded bg-[var(--studio-ember-soft)] text-[var(--studio-ember-strong)] font-semibold cursor-pointer border border-[var(--studio-ember)]/40">
                        <span className="text-[var(--studio-ember)]">★</span>
                        <span className="truncate">Xe_Sedan_04</span>
                      </div>
                      <div className="pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-ochre)]">▲</span>
                        <span className="truncate">VoLoi_Hull_04</span>
                      </div>
                      <div className="pl-3 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer">
                        <span className="text-[var(--studio-ink-muted)]">▸</span>
                        <span className="text-[var(--studio-sage)]">■</span>
                        <span className="truncate">CamBien_Rig</span>
                      </div>
                    </div>
                  </div>

                  {/* Display Layer Switches */}
                  <div className="pt-3 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] space-y-1.5">
                    <div className="text-[10px] uppercase tracking-wider text-[var(--studio-ink-muted)] font-bold">Lớp Hiển Thị</div>
                    <label className="flex items-center gap-2 text-[11px] text-[var(--studio-ink)] cursor-pointer">
                      <input type="checkbox" defaultChecked className="rounded accent-[var(--studio-geometry)]" />
                      <span className="text-[var(--studio-geometry)]">Lớp hình học</span>
                    </label>
                    <label className="flex items-center gap-2 text-[11px] text-[var(--studio-ink)] cursor-pointer">
                      <input type="checkbox" defaultChecked className="rounded accent-[var(--studio-ochre)]" />
                      <span className="text-[var(--studio-ochre)]">Vỏ va chạm lồi</span>
                    </label>
                    <label className="flex items-center gap-2 text-[11px] text-[var(--studio-ink)] cursor-pointer">
                      <input type="checkbox" defaultChecked className="rounded accent-[var(--studio-ember)]" />
                      <span className="text-[var(--studio-ember)]">Hộp bao thực thể</span>
                    </label>
                  </div>
                </div>

                {/* Main 3D Viewport in Cockpit */}
                <div className="col-span-8 sm:col-span-9 bg-[var(--studio-viewport)] relative flex flex-col justify-between p-3 overflow-hidden">
                  <div className="absolute inset-0 bg-grid-dark opacity-80 pointer-events-none"></div>

                  <div className="relative z-10 flex items-center justify-between font-mono-tech text-[11px]">
                    <div className="flex items-center gap-2 bg-[var(--studio-viewport-deep)]/90 backdrop-blur px-2 py-1 rounded border border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-on-dark)]">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--studio-sage)]"></span>
                      <span>CAM: QUỸ ĐẠO [45°, -18°]</span>
                    </div>
                    <div className="bg-[var(--studio-viewport-deep)]/90 px-2 py-1 rounded border border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[var(--studio-geometry)]">
                      <span>ĐỘ PHÂN GIẢI: VOXEL 0.02m</span>
                    </div>
                  </div>

                  {/* Wireframe Intersection Mockup */}
                  <div className="relative z-0 my-auto flex items-center justify-center">
                    <svg viewBox="0 0 360 260" className="w-full max-w-[340px] h-auto" aria-hidden="true">
                      <polygon points="180,40 330,120 180,210 30,120" fill="none" stroke="var(--studio-geometry)" strokeWidth="1.2" strokeOpacity="0.4" />
                      <line x1="180" y1="40" x2="180" y2="210" stroke="var(--studio-geometry)" strokeWidth="0.8" strokeOpacity="0.25" />
                      <line x1="30" y1="120" x2="330" y2="120" stroke="var(--studio-geometry)" strokeWidth="0.8" strokeOpacity="0.25" />
                      <line x1="105" y1="80" x2="255" y2="165" stroke="var(--studio-geometry)" strokeWidth="0.8" strokeOpacity="0.25" />
                      <line x1="255" y1="80" x2="105" y2="165" stroke="var(--studio-geometry)" strokeWidth="0.8" strokeOpacity="0.25" />

                      <path d="M 60,110 L 170,175" stroke="var(--studio-ochre)" strokeWidth="2" strokeDasharray="3 3" />
                      <path d="M 300,110 L 190,175" stroke="var(--studio-ochre)" strokeWidth="2" strokeDasharray="3 3" />

                      <g transform="translate(0, -10)">
                        <polygon points="150,110 190,90 230,110 190,132" fill="var(--studio-ember)" fillOpacity="0.2" stroke="var(--studio-ember)" strokeWidth="1.8" />
                        <polygon points="150,130 190,110 230,130 190,152" fill="var(--studio-ember)" fillOpacity="0.1" stroke="var(--studio-ember)" strokeWidth="1.8" />
                        <line x1="150" y1="110" x2="150" y2="130" stroke="var(--studio-ember)" strokeWidth="1.8" />
                        <line x1="190" y1="90" x2="190" y2="110" stroke="var(--studio-ember)" strokeWidth="1.8" />
                        <line x1="230" y1="110" x2="230" y2="130" stroke="var(--studio-ember)" strokeWidth="1.8" />
                        <line x1="190" y1="132" x2="190" y2="152" stroke="var(--studio-ember)" strokeWidth="1.8" />
                      </g>
                    </svg>
                  </div>

                  <div className="relative z-10 flex items-center justify-between font-mono-tech text-[10px] text-[var(--studio-on-dark)]/70">
                    <span>ĐỐI TƯỢNG ĐÃ CHỌN: XE_SEDAN_04</span>
                    <span className="text-[var(--studio-sage)]">VỎ VA CHẠM: V-HACD [HỢP LỆ]</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Inspector Details Panel */}
            <div className="lg:col-span-4 bg-[var(--studio-paper-raised)] rounded-xl border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] p-6 space-y-6">
              <div>
                <div className="text-xs font-mono-tech uppercase text-[var(--studio-ember-strong)] font-semibold mb-1">
                  Thuộc Tính Đối Tượng
                </div>
                <h4 className="text-lg font-bold text-[var(--studio-ink)]">Xe_Sedan_Obstacle_04</h4>
                <p className="text-xs text-[var(--studio-ink-muted)] mt-1">
                  Thực thể vật cản động được phân đoạn từ luồng video và gán vỏ va chạm lồi cho Isaac Sim.
                </p>
              </div>

              <div className="space-y-3 font-mono-tech text-xs">
                <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-[var(--studio-ink-muted)] mb-1 text-[11px]">Tọa Độ Không Gian Gốc</div>
                  <div className="text-[var(--studio-ink)] font-semibold">X: +14.28m · Y: -03.11m · Z: +00.42m</div>
                </div>

                <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-[var(--studio-ink-muted)] mb-1 text-[11px]">Kích Thước Hộp Bao (OBB)</div>
                  <div className="text-[var(--studio-ink)] font-semibold">4.82m × 1.95m × 1.48m</div>
                </div>

                <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between">
                  <div>
                    <div className="text-[var(--studio-ink-muted)] text-[11px]">Hệ Số Ma Sát (μ)</div>
                    <div className="text-[var(--studio-ink)] font-semibold">0.68 (Mặt đường khô)</div>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-[var(--studio-sage)]/20 text-[var(--studio-sage)] font-semibold border border-[var(--studio-sage)]/30">
                    CHUẨN PHYSX
                  </span>
                </div>
              </div>

              <div className="pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)] flex items-center justify-between text-xs font-mono-tech">
                <span className="text-[var(--studio-ink-muted)]">Trạng thái xác minh:</span>
                <span className="text-[var(--studio-sage)] font-bold">100% SẴN SÀNG RELEASE</span>
              </div>
            </div>
          </div>

          {/* 6 Core Capabilities Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {/* 1 */}
            <div className="p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-geometry)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">1. Tái Tạo Đa Nguồn</h3>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                  Kết hợp dữ liệu hình ảnh và không gian thành luồng tái tạo đồng nhất. Nạp camera vòm đồng bộ, cảm biến LiDAR quay và thể rắn mà không cần tinh chỉnh ngoại suy thủ công.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-geometry)]">
                HỢP_NHẤT_CẢM_BIẾN::KÍN_NƯỚC
              </div>
            </div>

            {/* 2 */}
            <div className="p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ember-strong)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">2. Biểu Diễn Scene Biên Tập Được</h3>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                  Biến môi trường tái tạo thành scene có cấu trúc chỉnh sửa linh hoạt. Thay đổi quỹ đạo làn đường, di chuyển kệ hàng, thay đổi thời tiết và cấy các mối nguy hiểm đối kháng.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-ember-strong)]">
                ĐỒ_THỊ_IR::SCENE_BIÊN_TẬP
              </div>
            </div>

            {/* 3 */}
            <div className="p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ochre)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">3. Hiểu Rõ Hình Học & Ngữ Nghĩa</h3>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                  Phân tách dữ liệu hình học khỏi thông tin ngữ nghĩa và vật lý. Nhận diện rõ ràng bề mặt xe chạy, thảm thực vật che khuất và tường chịu lực kèm cờ biên ranh giới xác thực.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-ochre)]">
                NGỮ_NGHĨA::RANH_GIỚI_RÕ_RÀNG
              </div>
            </div>

            {/* 4 */}
            <div className="p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-geometry)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">4. Khảo Sát Không Gian 3D</h3>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                  Trực quan hóa môi trường tái tạo qua khung nhìn 3D tương tác mượt mà. Đo đạc khoảng hở, kiểm tra phân bố vector pháp tuyến bề mặt và độ gồ ghề của mặt đường trực quan.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-geometry)]">
                VIEWPORT::KIỂM_TRA_TRỰC_QUAN
              </div>
            </div>

            {/* 5 */}
            <div className="p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-sage)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">5. Kiểm Định Mô Phỏng Tự Động</h3>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                  Kiểm tra toàn diện gói scene trước khi đưa vào luồng mô phỏng hạ tầng. Bộ linter tự động phát hiện giao cắt xuyên thấu, vật thể lơ lửng và lỗi suy biến đa giác.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-sage)]">
                LINTER::CAM_KẾT_KHÔNG_LỖI
              </div>
            </div>

            {/* 6 */}
            <div className="p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink-muted)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2m-4-1v8m0 0l3-3m-3 3L9 8m-5 5h2.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293h3.172a1 1 0 00.707-.293l2.414-2.414a1 1 0 01.707-.293H20" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight">6. Đóng Gói Tái Lập Được</h3>
                <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                  Tạo đầu ra có cấu trúc chuẩn xác để đánh giá, chia sẻ và tái sử dụng giữa các nhóm phân tán. Các gói bundle được niêm phong chữ ký mã hóa liên kết ngược lại nguồn gốc.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-ink-muted)]">
                ARTIFACT::TRUY_XUẤT_SHA256
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 04 / DỮ LIỆU THẬT TỪ BACKEND: MÔI TRƯỜNG MẪU & CỤM TÍNH TOÁN ── */}
      <section id="samples" className="py-24 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-14">
            <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
              04 / Dữ Liệu Thời Gian Thực
            </div>
            <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4">
              Môi trường mẫu và cụm máy trạm tính toán.
            </h2>
            <p className="text-base text-[var(--studio-ink-muted)]">
              Dữ liệu được nạp trực tiếp từ backend Studio: các kịch bản mẫu sẵn sàng phát lại và thông số phần cứng của máy trạm xử lý.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            {/* Real Demo Samples Showcase */}
            <div className="lg:col-span-8 space-y-6">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-[var(--studio-ink)] flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-geometry)]"></span>
                  Kịch Bản Mẫu Có Sẵn ({samples.length > 0 ? samples.length : "Đang kết nối"})
                </h3>
                <span className="text-xs font-mono-tech text-[var(--studio-ink-muted)]">
                  Nguồn: Thư viện TorWIC-SLAM / Pipeline
                </span>
              </div>

              {samples.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {samples.map((sample) => (
                    <div
                      key={sample.sample_id}
                      className="p-6 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] hover:border-[var(--studio-geometry)]/40 transition-all flex flex-col justify-between shadow-xs"
                    >
                      <div>
                        <div className="flex items-center justify-between mb-3 text-xs font-mono-tech">
                          <span className="px-2 py-0.5 rounded bg-[var(--studio-geometry)]/10 text-[var(--studio-geometry)] border border-[var(--studio-geometry)]/20 font-semibold">
                            {sample.source.dataset}
                          </span>
                          <span className="text-[var(--studio-ink-muted)]">
                            {sample.frame_count ? `${sample.frame_count} frames` : "Sẵn sàng"}
                          </span>
                        </div>
                        <h4 className="text-base font-bold text-[var(--studio-ink)] mb-2">
                          {sample.title}
                        </h4>
                        <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-4">
                          {sample.description}
                        </p>

                        <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-[11px] space-y-1 mb-4 text-[var(--studio-ink-muted)]">
                          <div className="flex justify-between">
                            <span>Chuỗi quay:</span>
                            <span className="text-[var(--studio-ink)] font-semibold">{sample.source.sequence}</span>
                          </div>
                          {sample.machine && sample.machine.gpu && (
                            <div className="flex justify-between">
                              <span>Máy xử lý:</span>
                              <span className="text-[var(--studio-ink)]">{sample.machine.gpu}</span>
                            </div>
                          )}
                          {sample.total_seconds && (
                            <div className="flex justify-between">
                              <span>Thời gian chạy:</span>
                              <span className="text-[var(--studio-ink)]">{Math.round(sample.total_seconds)}s</span>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="pt-3 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between">
                        <Link
                          href={`/new/try-demo?sample=${encodeURIComponent(sample.sample_id)}`}
                          className="text-xs font-semibold text-[var(--studio-ember-strong)] hover:text-[var(--studio-ember)] flex items-center gap-1 group"
                        >
                          <span>Thử kịch bản này</span>
                          <span className="transform group-hover:translate-x-1 transition-transform">→</span>
                        </Link>
                        <span className="text-[10px] font-mono-tech text-[var(--studio-sage)]">ĐÃ TÁI TẠO</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                /* Fallback Technical Card if offline */
                <div className="p-8 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono-tech text-[var(--studio-geometry)] px-2 py-0.5 rounded bg-[var(--studio-geometry)]/10">
                      DATASET::TorWIC-SLAM
                    </span>
                    <span className="text-xs font-mono-tech text-[var(--studio-ink-muted)]">Aisle_CW · 50 frames</span>
                  </div>
                  <h4 className="text-base font-bold text-[var(--studio-ink)]">
                    Kho TorWIC · Lối Đi Trung Tâm Aisle CW
                  </h4>
                  <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                    Kịch bản quay lối đi nhà kho công nghiệp bằng camera di chuyển trên robot AGV. Tái tạo 7.000 bước với độ phân giải 960px trên GPU Quadro T2000.
                  </p>
                  <div className="pt-3 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between">
                    <Link
                      href={STUDIO_ENTRY}
                      className="text-xs font-semibold text-[var(--studio-ember-strong)] hover:text-[var(--studio-ember)]"
                    >
                      Mở Studio để xem chi tiết →
                    </Link>
                    <span className="text-xs font-mono-tech text-[var(--studio-ink-muted)]">
                      {isLoadingApi ? "Đang truy vấn dữ liệu..." : "Chế độ offline chuẩn"}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Live Worker Hardware Telemetry */}
            <div className="lg:col-span-4 bg-[var(--studio-paper-raised)] rounded-xl border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] p-6 space-y-6">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono-tech uppercase text-[var(--studio-geometry)] font-semibold">
                    Máy Trạm Worker Hiện Hành
                  </span>
                  <span className={`w-2 h-2 rounded-full ${apiConnected ? "bg-[var(--studio-sage)]" : "bg-[var(--studio-ochre)]"}`}></span>
                </div>
                <h4 className="text-lg font-bold text-[var(--studio-ink)]">
                  {capability?.gpu_name ?? "NVIDIA GPU Worker"}
                </h4>
                <p className="text-xs text-[var(--studio-ink-muted)] mt-1">
                  Thông số thực tế được backend báo cáo qua endpoint <code className="font-mono-tech">/processing/options</code>.
                </p>
              </div>

              <div className="space-y-3 font-mono-tech text-xs">
                <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                  <span className="text-[var(--studio-ink-muted)]">Dung lượng VRAM:</span>
                  <span className="text-[var(--studio-ink)] font-semibold">
                    {capability?.vram_total_gb ? `${capability.vram_total_gb} GB GDDR` : "4.0 GB GDDR"}
                  </span>
                </div>

                <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                  <span className="text-[var(--studio-ink-muted)]">Bộ nhớ RAM hệ thống:</span>
                  <span className="text-[var(--studio-ink)] font-semibold">
                    {capability?.ram_total_gb ? `${capability.ram_total_gb} GB RAM` : "32.0 GB RAM"}
                  </span>
                </div>

                <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                  <span className="text-[var(--studio-ink-muted)]">Luồng CPU xử lý:</span>
                  <span className="text-[var(--studio-ink)] font-semibold">
                    {capability?.cpu_count ? `${capability.cpu_count} Luồng` : "16 Luồng"}
                  </span>
                </div>

                {presets && (
                  <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <div className="text-[var(--studio-ink-muted)] mb-1 text-[11px]">Cấu hình Presets có sẵn:</div>
                    <div className="text-[var(--studio-geometry)] font-semibold text-[11px]">
                      minimum_quality · maximum · machine_maximum
                    </div>
                  </div>
                )}
              </div>

              <div className="p-3.5 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                Hệ thống tự động đối chiếu thông số xử lý với bộ nhớ worker nhằm ngăn chặn tràn RAM và lỗi crash phần cứng.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 05 / KIẾN TRÚC ĐƯỜNG ỐNG (DETERMINISTIC COMPILER) ── */}
      <section id="technology" className="py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-16">
            <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
              05 / Kiến Trúc Hệ Thống
            </div>
            <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4">
              Đường ống chuyển đổi xác định bốn tầng.
            </h2>
            <p className="text-base text-[var(--studio-ink-muted)]">
              Luồng biên dịch tách biệt bốn tầng chuyển đổi dữ liệu cảm biến thô thành các tài sản scene hoàn chỉnh cho môi trường vật lý.
            </p>
          </div>

          <div className="bg-[var(--studio-paper-raised)] rounded-xl border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] p-8 lg:p-12 shadow-sm">
            <div className="flex flex-wrap items-center justify-between pb-8 mb-10 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)] gap-4">
              <div className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">
                ĐẶC TẢ BIÊN DỊCH :: R2S-IR-2026
              </div>
              <div className="flex items-center gap-6 text-xs font-mono-tech">
                <span className="flex items-center gap-2">
                  <span className="w-3 h-0.5 bg-[var(--studio-geometry)]"></span> Luồng dữ liệu
                </span>
                <span className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[var(--studio-ember)]"></span> Nút biên dịch
                </span>
                <span className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-xs bg-[var(--studio-ochre)]"></span> Vật lý & Collider
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 relative">
              {/* EX-REC */}
              <div className="p-6 rounded-lg bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] relative flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-mono-tech text-[var(--studio-ember)] font-bold px-2 py-0.5 rounded bg-[var(--studio-ember-soft)]">
                      EX-REC
                    </span>
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-ember)] animate-pulse"></span>
                  </div>
                  <h4 className="text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech">ReconstructionBundle</h4>
                  <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                    Hiệu chuẩn đa cảm biến, ước lượng tư thế ngoại suy và tái tạo mật độ 3DGS.
                  </p>
                </div>
                <div className="space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]">
                  <div className="text-[var(--studio-geometry)] flex items-center justify-between">
                    <span>+ pose_graph.bin</span>
                    <span>SE(3)</span>
                  </div>
                  <div className="text-[var(--studio-geometry)] flex items-center justify-between">
                    <span>+ depth_voxels.raw</span>
                    <span>TSDF</span>
                  </div>
                </div>
              </div>

              {/* EX-SCENE */}
              <div className="p-6 rounded-lg bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] relative flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-mono-tech text-[var(--studio-geometry)] font-bold px-2 py-0.5 rounded bg-[var(--studio-geometry)]/10 border border-[var(--studio-geometry)]/20">
                      EX-SCENE
                    </span>
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-geometry)]"></span>
                  </div>
                  <h4 className="text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech">SceneIR</h4>
                  <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                    Phân đoạn ngữ nghĩa và phân rã hình học thành đồ thị nút không gian độc lập.
                  </p>
                </div>
                <div className="space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]">
                  <div className="text-[var(--studio-geometry)] flex items-center justify-between">
                    <span>+ surface_mesh.usda</span>
                    <span>Dưới-cm</span>
                  </div>
                  <div className="text-[var(--studio-ochre)] flex items-center justify-between">
                    <span>+ semantic_labels.json</span>
                    <span>Cityscapes</span>
                  </div>
                </div>
              </div>

              {/* EX-SIM */}
              <div className="p-6 rounded-lg bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] relative flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-mono-tech text-[var(--studio-ochre)] font-bold px-2 py-0.5 rounded bg-[var(--studio-ochre)]/10 border border-[var(--studio-ochre)]/20">
                      EX-SIM
                    </span>
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-ochre)]"></span>
                  </div>
                  <h4 className="text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech">CandidatePackage</h4>
                  <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                    Tạo vỏ va chạm lồi, khớp động học và chạy bộ kiểm tra kiểm định vật lý.
                  </p>
                </div>
                <div className="space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]">
                  <div className="text-[var(--studio-ochre)] flex items-center justify-between">
                    <span>+ collision_hulls.obj</span>
                    <span>V-HACD</span>
                  </div>
                  <div className="text-[var(--studio-sage)] flex items-center justify-between">
                    <span>+ ValidationReport</span>
                    <span>LINTER_OK</span>
                  </div>
                </div>
              </div>

              {/* EX-PRODUCT */}
              <div className="p-6 rounded-lg bg-[var(--studio-paper)] border border-[var(--studio-ember-strong)]/40 relative flex flex-col justify-between">
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-mono-tech text-[var(--studio-ember-strong)] font-bold px-2 py-0.5 rounded bg-[var(--studio-ember-soft)]">
                      EX-PRODUCT
                    </span>
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                  </div>
                  <h4 className="text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech">Duyệt Web & Phát Hành</h4>
                  <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                    Đánh số phiên bản xác định, thẩm định phê duyệt chéo và phát hành scene đã niêm phong.
                  </p>
                </div>
                <div className="space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]">
                  <div className="text-[var(--studio-ink)] flex items-center justify-between">
                    <span>+ Studio Web Review</span>
                    <span>WebGL</span>
                  </div>
                  <div className="text-[var(--studio-sage)] font-semibold flex items-center justify-between">
                    <span>+ Release Ký Số</span>
                    <span>CARLA/ISAAC</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-8 pt-6 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
              <div className="flex items-center justify-between text-xs font-mono-tech text-[var(--studio-ink-muted)]">
                <span>Dữ liệu thô (LiDAR + Cam)</span>
                <span className="text-[var(--studio-geometry)]">─── Tái tạo ───</span>
                <span className="text-[var(--studio-ochre)]">─── Phân tách ───</span>
                <span className="text-[var(--studio-sage)]">─── Scene Đã Kiểm Định ───</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 06 / KHUNG ĐÁNH GIÁ CHẤT LƯỢNG (QUALITY FRAMEWORK) ── */}
      <section id="evaluation" className="py-24 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-16">
            <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
              06 / Khung Đánh Giá Chất Lượng
            </div>
            <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4">
              Đo lường tái tạo.
              <br />
              <span className="text-[var(--studio-ink-muted)]">Kiểm định scene.</span>
            </h2>
            <p className="text-base text-[var(--studio-ink-muted)]">
              Mọi gói scene đều phải trải qua bộ kiểm định xác định trước khi phát hành. Các giá trị chỉ số phản ánh đường ống kiểm tra tự động thay vì ước lượng cảm tính.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* 01 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">CHỈ SỐ 01</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-geometry)] bg-[var(--studio-geometry)]/10 px-2 py-0.5 rounded">
                    KHÔNG GIAN
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-1">Chất Lượng Tái Tạo</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Sai số chiếu lại giữa tư thế camera và mẫu bề mặt LiDAR được kiểm soát chặt chẽ.
                </p>
                <div className="p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1">Trạng thái</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                    Từ quy trình kiểm định
                  </div>
                  <div className="mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                    Mục tiêu: Sai số bundle adjustment &lt; 0.4px
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Dữ liệu benchmark cập nhật theo từng run
              </div>
            </div>

            {/* 02 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">CHỈ SỐ 02</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-geometry)] bg-[var(--studio-geometry)]/10 px-2 py-0.5 rounded">
                    DUNG SAI
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-1">Độ Chính Xác Hình Học</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Khoảng cách Chamfer và độ lệch điểm-mặt phẳng được đối chiếu với dữ liệu đo đạc thực tế.
                </p>
                <div className="p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1">Trạng thái</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                    Đang theo dõi kiểm định
                  </div>
                  <div className="mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                    Mục tiêu: Biên Hausdorff 95% &lt; 12mm
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Kiểm định LiDAR dưới milimet
              </div>
            </div>

            {/* 03 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">CHỈ SỐ 03</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-ochre)] bg-[var(--studio-ochre)]/10 px-2 py-0.5 rounded">
                    ĐỘ PHỦ
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-1">Độ Hoàn Thiện Scene</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Tỉ lệ lỗ khuyết do che khuất được tái tạo liền mạch với đường biên đa tạp kín.
                </p>
                <div className="p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1">Trạng thái</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                    Dữ liệu benchmark
                  </div>
                  <div className="mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                    Mục tiêu: 100% mặt sàn phẳng kín nước
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Kiểm định qua bộ tái tạo Poisson
              </div>
            </div>

            {/* 04 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">CHỈ SỐ 04</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-ochre)] bg-[var(--studio-ochre)]/10 px-2 py-0.5 rounded">
                    NHÃN NGỮ NGHĨA
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-1">Độ Nhất Quán Ngữ Nghĩa</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Sự đồng nhất giữa nhãn thị giác 2D và định nghĩa hộp bao thực thể 3D.
                </p>
                <div className="p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1">Trạng thái</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                    Từ quy trình kiểm định
                  </div>
                  <div className="mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                    Mục tiêu: Khớp entropy đa góc nhìn
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Không có vật cản động vô danh
              </div>
            </div>

            {/* 05 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">CHỈ SỐ 05</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-sage)] bg-[var(--studio-sage)]/10 px-2 py-0.5 rounded">
                    VẬT LÝ
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-1">Tính Hợp Lệ Mô Phỏng</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Kiểm tra xâm nhập đa tạp và độ ổn định của solver vật thể rắn qua 1.000 frame mô phỏng.
                </p>
                <div className="p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1">Trạng thái</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                    Đang theo dõi kiểm định
                  </div>
                  <div className="mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                    Mục tiêu: 0 tự giao cắt, 0 đột biến động năng
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Xác minh chạy headless trong PhysX 5.3
              </div>
            </div>

            {/* 06 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono-tech text-[var(--studio-ink)] font-bold">CHỈ SỐ 06</span>
                  <span className="text-[11px] font-mono-tech text-[var(--studio-ink-muted)] bg-[var(--studio-paper-sunken)] px-2 py-0.5 rounded">
                    TÍNH TOÁN
                  </span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-1">Chi Phí Xử Lý</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Số giờ GPU tiêu hao trên mỗi kilomet vuông không gian công nghiệp được tái tạo.
                </p>
                <div className="p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                  <div className="text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1">Trạng thái</div>
                  <div className="text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                    Dữ liệu benchmark
                  </div>
                  <div className="mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                    Mục tiêu: Tỉ lệ tuyến tính trên cụm máy phân tán
                  </div>
                </div>
              </div>
              <div className="mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Tối ưu hóa tài nguyên phần cứng
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 07 / ỨNG DỤNG LĨNH VỰC (DOMAIN APPLICATIONS) ── */}
      <section className="py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-16">
            <div className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3">
              07 / Ứng Dụng Thực Tế
            </div>
            <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4">
              Kiểm chứng thực tế trên các lĩnh vực tự hành.
            </h2>
            <p className="text-base text-[var(--studio-ink-muted)]">
              Được xây dựng cho các đội ngũ đòi hỏi độ trung thực vật lý tuyệt đối, không chấp nhận ảo giác thuật toán.
            </p>
          </div>

          <div className="space-y-8">
            {/* Domain 01: Xe tự hành */}
            <div className="p-8 lg:p-10 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-sm grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
              <div className="lg:col-span-7">
                <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[var(--studio-ember-soft)] text-[var(--studio-ember-strong)] font-mono-tech text-xs font-bold mb-4">
                  LĨNH VỰC 01 // ADAS & XE TỰ HÀNH L4
                </div>
                <h3 className="text-2xl font-bold text-[var(--studio-ink)] mb-3">XE TỰ HÀNH</h3>
                <p className="text-base text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Chuyển đổi các môi trường đường sá phức tạp thành scene sẵn sàng mô phỏng phục vụ thử nghiệm vòng lặp kín và kiểm định an toàn. Tái tạo nút giao cao tốc, giao lộ có đèn tín hiệu và công trường trực tiếp từ dữ liệu nhật ký đội xe.
                </p>
                <div className="grid grid-cols-2 gap-4 text-xs font-mono-tech">
                  <div className="p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <span className="text-[var(--studio-ink-muted)] block">Độ trung thực quỹ đạo</span>
                    <span className="text-[var(--studio-ink)] font-semibold">ASAM OpenDRIVE & OpenSCENARIO</span>
                  </div>
                  <div className="p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <span className="text-[var(--studio-ink-muted)] block">Cấy tình huống nguy hiểm</span>
                    <span className="text-[var(--studio-ink)] font-semibold">Cắt đầu xe & Người đi bộ khuất</span>
                  </div>
                </div>
              </div>
              <div className="lg:col-span-5 bg-[var(--studio-viewport)] rounded-lg p-5 border border-[var(--studio-ink)] font-mono-tech text-xs text-[var(--studio-on-dark)]/80 flex flex-col justify-between h-56">
                <div className="flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] pb-2 text-[11px]">
                  <span className="text-[var(--studio-ember)]">SCENE::TUYEN_DUONG_CAO_TOC_101</span>
                  <span className="text-[var(--studio-sage)]">ĐÃ CĂN CHUẨN</span>
                </div>
                <div className="space-y-2 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Chiều dài đoạn:</span>
                    <span>2.4 km đa làn</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Độ chuẩn độ cong:</span>
                    <span className="text-[var(--studio-geometry)]">Độ lệch ± 4.2 mm</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Vỏ bao vật lý:</span>
                    <span className="text-[var(--studio-ochre)]">Collider lan can liên tục</span>
                  </div>
                </div>
                <div className="pt-2 border-t border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[10px] text-[var(--studio-sage)]">
                  ✓ SẴN SÀNG CHẠY TRONG CARLA
                </div>
              </div>
            </div>

            {/* Domain 02: Robotics */}
            <div className="p-8 lg:p-10 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-sm grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
              <div className="lg:col-span-7">
                <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[var(--studio-geometry)]/15 text-[var(--studio-geometry)] font-mono-tech text-xs font-bold mb-4">
                  LĨNH VỰC 02 // LOGISTICS & ROBOT TỰ HÀNH AMR
                </div>
                <h3 className="text-2xl font-bold text-[var(--studio-ink)] mb-3">ROBOTICS</h3>
                <p className="text-base text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Tái tạo môi trường kho bãi và nhà xưởng công nghiệp cho mô phỏng robot. Xây dựng bản sao số chính xác của trung tâm hoàn tất đơn hàng với hệ thống giá kệ, băng chuyền và điểm thả pallet động để huấn luyện chính sách điều hướng và gắp thả.
                </p>
                <div className="grid grid-cols-2 gap-4 text-xs font-mono-tech">
                  <div className="p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <span className="text-[var(--studio-ink-muted)] block">Bao bọc động học</span>
                    <span className="text-[var(--studio-ink)] font-semibold">Khớp URDF & Vỏ va chạm lồi</span>
                  </div>
                  <div className="p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <span className="text-[var(--studio-ink-muted)] block">Mật độ đội xe</span>
                    <span className="text-[var(--studio-ink)] font-semibold">Điều phối đa AGV không gian</span>
                  </div>
                </div>
              </div>
              <div className="lg:col-span-5 bg-[var(--studio-viewport)] rounded-lg p-5 border border-[var(--studio-ink)] font-mono-tech text-xs text-[var(--studio-on-dark)]/80 flex flex-col justify-between h-56">
                <div className="flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] pb-2 text-[11px]">
                  <span className="text-[var(--studio-geometry)]">SCENE::KHO_HANG_BAY_04</span>
                  <span className="text-[var(--studio-sage)]">ĐÃ KIỂM ĐỊNH</span>
                </div>
                <div className="space-y-2 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Diện tích mặt sàn:</span>
                    <span>8.400 m² có cấu trúc</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Kệ chứa hàng:</span>
                    <span className="text-[var(--studio-ochre)]">48 collider lồi</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Hệ số ma sát:</span>
                    <span>μ = 0.65 đã xác thực</span>
                  </div>
                </div>
                <div className="pt-2 border-t border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[10px] text-[var(--studio-sage)]">
                  ✓ SẴN SÀNG CHẠY TRONG NVIDIA ISAAC SIM
                </div>
              </div>
            </div>

            {/* Domain 03: Nghiên cứu */}
            <div className="p-8 lg:p-10 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-sm grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
              <div className="lg:col-span-7">
                <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] font-mono-tech text-xs font-bold mb-4">
                  LĨNH VỰC 03 // VIỆN NGHIÊN CỨU & BENCHMARK
                </div>
                <h3 className="text-2xl font-bold text-[var(--studio-ink)] mb-3">NGHIÊN CỨU KHOA HỌC</h3>
                <p className="text-base text-[var(--studio-ink-muted)] leading-relaxed mb-6">
                  Tạo lập môi trường 3D có thể tái lập cho các thí nghiệm và đánh giá khoa học. Đóng gói các trường hợp biên phức tạp ngoài đời thực kèm mã hash sha256 bất biến và siêu dữ liệu, giúp các nhóm nghiên cứu chia sẻ benchmark chuẩn mực không sai lệch.
                </p>
                <div className="grid grid-cols-2 gap-4 text-xs font-mono-tech">
                  <div className="p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <span className="text-[var(--studio-ink-muted)] block">Định dạng mở</span>
                    <span className="text-[var(--studio-ink)] font-semibold">USD, glTF 2.0, OBJ + MTL</span>
                  </div>
                  <div className="p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
                    <span className="text-[var(--studio-ink-muted)] block">Kiểm tra nguồn gốc</span>
                    <span className="text-[var(--studio-ink)] font-semibold">Seed xác định & Mốc thời gian</span>
                  </div>
                </div>
              </div>
              <div className="lg:col-span-5 bg-[var(--studio-viewport)] rounded-lg p-5 border border-[var(--studio-ink)] font-mono-tech text-xs text-[var(--studio-on-dark)]/80 flex flex-col justify-between h-56">
                <div className="flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] pb-2 text-[11px]">
                  <span className="text-[var(--studio-ember)]">BENCHMARK::MUA_DEM_TRUONG_HOP_BIEN</span>
                  <span className="text-[var(--studio-sage)]">BẤT BIẾN</span>
                </div>
                <div className="space-y-2 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Mã hash manifest:</span>
                    <span className="font-mono-tech text-[10px]">sha256:7f8a9...b4c2</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Dàn camera:</span>
                    <span className="text-[var(--studio-geometry)]">8 luồng đồng bộ</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--studio-on-dark)]/60">Chân lý mặt đất:</span>
                    <span>RTK-GNSS dưới centimet</span>
                  </div>
                </div>
                <div className="pt-2 border-t border-[color-mix(in_srgb,var(--studio-on-dark)_10%,transparent)] text-[10px] text-[var(--studio-sage)]">
                  ✓ SẴN SÀNG PHÁT HÀNH TRÍCH DẪN MỞ
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 08 / CTA BANNER CHUYÊN NGHIỆP ── */}
      <section className="py-24 bg-[var(--studio-viewport)] text-[var(--studio-paper-raised)] relative overflow-hidden">
        <div className="absolute inset-0 bg-grid-dark opacity-40 pointer-events-none"></div>

        <div className="max-w-5xl mx-auto px-6 relative z-10 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded bg-[var(--studio-ink)] border border-[color-mix(in_srgb,var(--studio-on-dark)_15%,transparent)] text-xs font-mono-tech text-[var(--studio-ember)] mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--studio-ember)] animate-ping"></span>
            <span>REAL2SIM STUDIO</span>
          </div>

          <h2 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-[var(--studio-paper-raised)] mb-6">
            Xây dựng môi trường mô phỏng từ thế giới thực.
          </h2>

          <p className="text-xl sm:text-2xl font-mono-tech text-[var(--studio-ember)] mb-10 tracking-wide">
            Tái tạo. Khảo sát. Kiểm định.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-5">
            <Link
              href={STUDIO_ENTRY}
              aria-label="Open Real2Sim Studio"
              className="px-8 py-4 text-base font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-md active:translate-y-px"
            >
              Mở Real2Sim Studio
            </Link>
            <a
              href="#documentation"
              className="px-8 py-4 text-base font-semibold text-[var(--studio-paper-raised)] rounded-md bg-[var(--studio-ink)] hover:bg-[var(--studio-viewport-raised)] border border-[color-mix(in_srgb,var(--studio-on-dark)_15%,transparent)] transition-all"
            >
              Xem tài liệu kỹ thuật
            </a>
          </div>

          <div className="mt-12 text-xs font-mono-tech text-[var(--studio-on-dark)]/60 flex flex-wrap justify-center items-center gap-6">
            <span>Không yêu cầu thẻ tín dụng</span>
            <span>•</span>
            <span>Nạp ROS2 trực tiếp</span>
            <span>•</span>
            <span>Xuất thẳng USD & URDF</span>
            <span>•</span>
            <span>Cam kết độ chính xác kỹ thuật</span>
          </div>
        </div>
      </section>

      {/* ── FOOTER CHÂN TRANG ── */}
      <footer id="documentation" className="py-16 bg-[var(--studio-paper)] border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pb-12 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-6 h-6 rounded bg-[var(--studio-viewport)] flex items-center justify-center p-1">
                  <svg viewBox="0 0 24 24" fill="none" className="w-full h-full" aria-hidden="true">
                    <path d="M12 2L3 7L12 12L21 7L12 2Z" stroke="var(--studio-ember)" strokeWidth="2" />
                    <path d="M3 17L12 22L21 17" stroke="var(--studio-geometry)" strokeWidth="1.8" />
                  </svg>
                </div>
                <span className="font-bold text-[var(--studio-ink)] text-base tracking-tight">Real2Sim Studio</span>
              </div>
              <p className="text-xs text-[var(--studio-ink-muted)] max-w-sm">
                Tái tạo môi trường giao thông và nhà xưởng công nghiệp thực tế thành các scene 3D có cấu trúc, sẵn sàng cho mô phỏng vật lý robotics.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-8 text-sm font-medium text-[var(--studio-ink-muted)]">
              <a href="#product" className="hover:text-[var(--studio-ink)] transition-colors">
                Sản phẩm
              </a>
              <a href="#workflow" className="hover:text-[var(--studio-ink)] transition-colors">
                Quy trình
              </a>
              <a href="#samples" className="hover:text-[var(--studio-ink)] transition-colors">
                Môi trường mẫu
              </a>
              <a href="#technology" className="hover:text-[var(--studio-ink)] transition-colors">
                Công nghệ
              </a>
              <a href="#evaluation" className="hover:text-[var(--studio-ink)] transition-colors">
                Đánh giá
              </a>
              <a href="#documentation" className="hover:text-[var(--studio-ink)] transition-colors">
                Tài liệu
              </a>
              <a
                href="https://github.com/AI20K-Build-Phase-Cohort-4/P-087"
                target="_blank"
                rel="noreferrer"
                className="hover:text-[var(--studio-ink)] transition-colors flex items-center gap-1.5 font-mono-tech text-xs"
              >
                GitHub
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            </div>
          </div>

          <div className="pt-8 flex flex-col sm:flex-row items-center justify-between text-xs font-mono-tech text-[var(--studio-ink-muted)] gap-4">
            <div>
              © 2026 Real2Sim Studio. Bảo lưu mọi quyền. Hệ thống không gian cấp độ kỹ thuật chuyên sâu.
            </div>
            <div className="flex items-center gap-6">
              <span className="text-[var(--studio-sage)]">● BẢN XEM TRƯỚC KỸ THUẬT</span>
              <span aria-disabled="true" title="Chưa kích hoạt trong bản xem trước">
                Chính sách bảo mật
              </span>
              <span aria-disabled="true" title="Chưa kích hoạt trong bản xem trước">
                Báo cáo an toàn
              </span>
            </div>
          </div>
        </div>
      </footer>
    </main>
  );
}
