"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LandingAnchors } from "@/features/landing/LandingAnchors";
import { listSamples, getProcessingOptions } from "@/lib/api/studio";
import type { SampleSummary, ProcessingOptions } from "@/lib/contracts/studio";
import { STUDIO_ENTRY } from "@/lib/routes";

/**
 * Landing Page Real2Sim Studio — Thiết kế theo chuẩn trực quan, gãy gọn và mạch lạc.
 * Tham chiếu phong cách Homematch (c3-app-038): Cấu trúc 5 phần logic, số liệu lớn,
 * chuỗi mắt xích liên kết trực quan, tích hợp dữ liệu thật từ API backend.
 */
export function LandingPage() {
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [capability, setCapability] = useState<ProcessingOptions["capability"] | null>(null);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const [isLoadingApi, setIsLoadingApi] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileMenuOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileMenuOpen]);

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
          {/* Brand */}
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

          {/* Menu Desktop */}
          <nav aria-label="Landing page sections" className="hidden lg:flex items-center gap-8 text-[14px] font-medium text-[var(--studio-ink-muted)]">
            <a href="#product" aria-label="Product" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Sản phẩm
            </a>
            <a href="#problem" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Bài toán
            </a>
            <a href="#workflow" aria-label="Workflow" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Quy trình
            </a>
            <a href="#samples" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Dữ liệu thật
            </a>
            <a href="#start" className="hover:text-[var(--studio-ink)] transition-colors py-1">
              Bắt đầu
            </a>
          </nav>

          {/* Action CTAs */}
          <div className="flex items-center gap-3">
            <div className="hidden sm:inline-flex text-xs font-mono-tech text-[var(--studio-ink-muted)] items-center gap-1.5 px-2.5 py-1 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]">
              <span className={`w-1.5 h-1.5 rounded-full ${apiConnected ? "bg-[var(--studio-sage)]" : "bg-[var(--studio-ochre)]"}`}></span>
              <span>{isLoadingApi ? "Đang kết nối API" : apiConnected ? "API v1 Trực tuyến" : "Chế độ ngoại tuyến"}</span>
            </div>

            <Link
              href={STUDIO_ENTRY}
              aria-label="Open Studio"
              className="inline-flex items-center justify-center px-4 py-2 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm active:translate-y-px"
            >
              <span>Vào Studio</span>
              <svg className="w-4 h-4 ml-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </Link>

            {/* Hamburger Mobile */}
            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="lg:hidden p-2 rounded-md text-[var(--studio-ink-muted)] hover:text-[var(--studio-ink)] hover:bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"
              aria-label="Mở menu"
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
          <div className="lg:hidden border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)] bg-[var(--studio-paper-raised)] px-6 py-4 space-y-3 font-medium text-sm text-[var(--studio-ink)]">
            <a href="#product" aria-label="Product" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Sản phẩm
            </a>
            <a href="#problem" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Bài toán
            </a>
            <a href="#workflow" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Quy trình
            </a>
            <a href="#samples" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Dữ liệu thật
            </a>
            <a href="#start" onClick={() => setMobileMenuOpen(false)} className="block py-1 hover:text-[var(--studio-ember-strong)]">
              Bắt đầu
            </a>
          </div>
        )}
      </header>

      {/* ── HERO SECTION: THÔNG ĐIỆP GÃY GỌN & TÍN HIỆU ── */}
      <section className="relative pt-16 pb-20 md:pt-24 md:pb-28 bg-grid-tech border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] overflow-hidden">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
            {/* Cột trái */}
            <div className="lg:col-span-7 flex flex-col justify-center">
              <p className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-4">
                SPATIAL RECONSTRUCTION FOR ISAAC SIM & ROBOTICS
              </p>

              <h1 className="text-4xl sm:text-5xl lg:text-[3.75rem] font-extrabold tracking-tight text-[var(--studio-ink)] leading-[1.08] mb-6">
                Từ video khảo sát đến scene mô phỏng.
                <br />
                <span className="text-[var(--studio-ember-strong)]">Sẵn sàng chạy trong Isaac Sim.</span>
              </h1>

              <p className="text-lg font-medium text-[var(--studio-ink)] mb-4 leading-relaxed max-w-xl">
                Real2Sim Studio biến video kho bãi và scan LiDAR thành scene 3D có cấu trúc, đúng tỉ lệ mét, sẵn sàng chạy mô phỏng robot — có người kiểm duyệt từng bước.
              </p>

              <p className="text-sm text-[var(--studio-ink-muted)] mb-8 leading-relaxed max-w-xl">
                Quy trình khép kín: tái tạo 3D, căn tỉ lệ mét, tách vật thể khỏi mặt sàn, tạo collider và xuất OpenUSD — con người kiểm duyệt ở từng khâu then chốt.
              </p>

              {/* CTAs */}
              <div className="flex flex-wrap items-center gap-4 mb-10">
                <Link
                  href={STUDIO_ENTRY}
                  aria-label="Open Studio"
                  className="px-6 py-3.5 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm flex items-center gap-2 group"
                >
                  <span>Mở Real2Sim Studio</span>
                  <svg className="w-4 h-4 transform group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </Link>

                <a
                  href="#product"
                  className="px-6 py-3.5 text-sm font-semibold text-[var(--studio-ink)] rounded-md bg-[var(--studio-paper-raised)] hover:bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] transition-all"
                >
                  Tìm hiểu sản phẩm →
                </a>
              </div>

              {/* 3 Tín hiệu bảo chứng (Signals) theo phong cách Homematch */}
              <div className="pt-6 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex flex-wrap gap-6 text-xs font-mono-tech text-[var(--studio-ink-muted)]">
                <span className="inline-flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[var(--studio-geometry)]"></span>
                  Tỉ lệ mét thực tế
                </span>
                <span className="inline-flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[var(--studio-sage)]"></span>
                  Xuất OpenUSD (.usda) cho Isaac Sim
                </span>
                <span className="inline-flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[var(--studio-ochre)]"></span>
                  Có người kiểm duyệt từng bước
                </span>
              </div>
            </div>

            {/* Cột phải: Card tổng quan kỹ thuật */}
            <div className="lg:col-span-5">
              <div className="p-6 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-lg space-y-5">
                <div className="flex items-center justify-between pb-3 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs">
                  <span className="text-[var(--studio-geometry)] font-semibold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--studio-geometry)] animate-pulse"></span>
                    TRẠNG THÁI HỆ THỐNG
                  </span>
                  <span className="text-[var(--studio-ink-muted)]">API v1</span>
                </div>

                <div className="space-y-3 font-mono-tech text-xs">
                  <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                    <span className="text-[var(--studio-ink-muted)]">Máy trạm GPU:</span>
                    <span className="text-[var(--studio-ink)] font-semibold">{capability?.gpu_name ?? "GPU Worker Sẵn sàng"}</span>
                  </div>
                  <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                    <span className="text-[var(--studio-ink-muted)]">Dung lượng VRAM:</span>
                    <span className="text-[var(--studio-ink)] font-semibold">{capability?.vram_total_gb ? `${capability.vram_total_gb} GB GDDR` : "Chưa xác định"}</span>
                  </div>
                  <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                    <span className="text-[var(--studio-ink-muted)]">Định dạng đầu ra:</span>
                    <span className="text-[var(--studio-ember-strong)] font-semibold">OpenUSD (.usda)</span>
                  </div>
                  <div className="p-3 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex justify-between items-center">
                    <span className="text-[var(--studio-ink-muted)]">Kịch bản mẫu có sẵn:</span>
                    <span className="text-[var(--studio-sage)] font-semibold">{samples.length > 0 ? `${samples.length} kịch bản mẫu` : "Đang nạp"}</span>
                  </div>
                </div>

                <div className="p-3.5 rounded bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                  Gói phát hành được niêm phong bằng chữ ký SHA-256 để truy vết nguồn gốc.
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── TICKER TRACK ── */}
      <section className="py-4 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)]">
        <div className="max-w-7xl mx-auto px-6 flex flex-wrap items-center justify-between gap-4 font-mono-tech text-xs text-[var(--studio-ink-muted)]">
          <span>01 — MULTIMODAL INGESTION</span>
          <span>02 — 3D GAUSSIAN RECONSTRUCTION</span>
          <span>03 — METRIC SCALE GROUNDING</span>
          <span>04 — PHYSICS & SIMULATION PACKAGING</span>
        </div>
      </section>

      {/* ── 01 / SẢN PHẨM: BẠN NHẬN ĐƯỢC GÌ (#product) ── */}
      <section id="product" className="py-20 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-14 text-center mx-auto">
            <p className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-2">
              01 / SẢN PHẨM
            </p>
            <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)]">
              Từ video khảo sát đến scene sẵn sàng mô phỏng
            </h2>
            <p className="text-sm text-[var(--studio-ink-muted)] mt-2">
              Mỗi vật thể và scene được giữ đồng bộ ở ba biểu diễn — chỉnh một chỗ, ba biểu diễn cập nhật cùng lúc.
            </p>
          </div>

          {/* 3 biểu diễn đồng bộ */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
            <div className="p-7 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-4">
              <div className="w-9 h-9 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-geometry)] flex items-center justify-center font-mono-tech font-bold text-sm">
                01
              </div>
              <div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)]">Biểu diễn hình ảnh</h3>
                <p className="text-[11px] font-mono-tech text-[var(--studio-geometry)] mt-0.5">VISUAL</p>
              </div>
              <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                Scene trông thế nào — bản render 3D Gaussian để xem và điều hướng ngay trên trình duyệt.
              </p>
            </div>

            <div className="p-7 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-4">
              <div className="w-9 h-9 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ochre)] flex items-center justify-center font-mono-tech font-bold text-sm">
                02
              </div>
              <div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)]">Biểu diễn hình học</h3>
                <p className="text-[11px] font-mono-tech text-[var(--studio-ochre)] mt-0.5">GEOMETRY</p>
              </div>
              <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                Bề mặt vật lý nằm ở đâu — sàn, tường, vật cản được tách rời và đo đúng tỉ lệ mét.
              </p>
            </div>

            <div className="p-7 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-4">
              <div className="w-9 h-9 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-sage)] flex items-center justify-center font-mono-tech font-bold text-sm">
                03
              </div>
              <div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)]">Biểu diễn vật lý</h3>
                <p className="text-[11px] font-mono-tech text-[var(--studio-sage)] mt-0.5">PHYSICS</p>
              </div>
              <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed">
                Trình mô phỏng dùng hình gì để tính va chạm — collider cho từng vật thể, sẵn sàng cho Isaac Sim.
              </p>
            </div>
          </div>

          <p className="text-center text-sm text-[var(--studio-ink-muted)]">
            Dành cho <span className="font-semibold text-[var(--studio-ink)]">kỹ sư mô phỏng</span>, kỹ sư tích hợp AMR và người kiểm duyệt chất lượng.
          </p>
        </div>
      </section>

      {/* ── 02 / BÀI TOÁN: CHUỖI 3 MẮT XÍCH ĐỨT GÃY (#problem) ── */}
      <section id="problem" className="py-20 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-8 mb-14 items-start">
            <div className="md:col-span-6">
              <p className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-2">
                02 / BÀI TOÁN
              </p>
              <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] leading-tight">
                Một chu trình mô phỏng.
                <br />
                <span className="text-[var(--studio-ink-muted)]">Ba mắt xích đang bị đứt gãy.</span>
              </h2>
            </div>
            <div className="md:col-span-6">
              <p className="text-base text-[var(--studio-ink-muted)] leading-relaxed">
                Khảo sát hiện trường ghi nhận lượng dữ liệu không gian khổng lồ. Nhưng biến video thô thành môi trường mô phỏng vật lý chính xác đòi hỏi vượt qua 3 rào cản lớn mà công cụ truyền thống chưa giải quyết trọn vẹn.
              </p>
            </div>
          </div>

          {/* 3 Mắt xích nối tiếp có mũi tên (Chain Links) */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-stretch">
            {/* Mắt xích 1 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4 font-mono-tech text-xs text-[var(--studio-ink-muted)]">
                  <span className="font-bold text-[var(--studio-ink)]">01 / DỮ LIỆU THÔ</span>
                  <span>NGUỒN CẤP</span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2">Khảo Sát Hiện Trường</h3>
                <div className="text-xl font-bold font-mono-tech text-[var(--studio-ember-strong)] mb-4">
                  Video & LiDAR
                  <span className="text-xs font-normal text-[var(--studio-ink-muted)] block font-sans">
                    dữ liệu pcap, MP4 và điểm quét rời rạc
                  </span>
                </div>
                <ul className="text-xs text-[var(--studio-ink-muted)] space-y-2 leading-relaxed">
                  <li>• Video bị méo quang học và che khuất động</li>
                  <li>• Đám mây điểm LiDAR dày đặc nhưng thiếu ngữ nghĩa</li>
                  <li>• Thiếu dấu mốc thời gian và vị trí camera chuẩn xác</li>
                </ul>
              </div>
            </div>

            {/* Mắt xích 2 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4 font-mono-tech text-xs text-[var(--studio-geometry)]">
                  <span className="font-bold">02 / TÁI TẠO</span>
                  <span>CHUYỂN ĐỔI</span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2">Dựng Hình 3D</h3>
                <div className="text-xl font-bold font-mono-tech text-[var(--studio-geometry)] mb-4">
                  Thủ công, nhiều tuần
                  <span className="text-xs font-normal text-[var(--studio-ink-muted)] block font-sans">
                    dọn dẹp đa giác và đo đạc bằng tay
                  </span>
                </div>
                <ul className="text-xs text-[var(--studio-ink-muted)] space-y-2 leading-relaxed">
                  <li>• Tỉ lệ mét bị đoán mò, thiếu cơ sở xác thực số đo</li>
                  <li>• Mặt sàn bị thủng lỗ, lượn sóng làm lệch bánh xe</li>
                  <li>• Vật cản và sàn nhà dính liền thành một khối tĩnh</li>
                </ul>
              </div>
            </div>

            {/* Mắt xích 3 */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4 font-mono-tech text-xs text-[var(--studio-ochre)]">
                  <span className="font-bold">03 / SIMULATION</span>
                  <span>RUNTIME</span>
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2">Isaac Sim</h3>
                <div className="text-xl font-bold font-mono-tech text-[var(--studio-ochre)] mb-4">
                  Thiếu kiểm định
                  <span className="text-xs font-normal text-[var(--studio-ink-muted)] block font-sans">
                    dẫn đến sập solver hoặc xung đột nổ động năng
                  </span>
                </div>
                <ul className="text-xs text-[var(--studio-ink-muted)] space-y-2 leading-relaxed">
                  <li>• Va chạm xuyên thấu ban đầu (initial penetration)</li>
                  <li>• Thiếu vỏ bao lồi khiến tính toán vật lý quá tải</li>
                  <li>• Không thể truy vết thay đổi khi cập nhật scene nháp</li>
                </ul>
              </div>
            </div>

            {/* Kết cục */}
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] flex flex-col justify-between">
              <div>
                <div className="font-mono-tech text-xs text-[var(--studio-rust)] font-bold mb-4">
                  HẬU QUẢ TỒN ĐỌNG
                </div>
                <h3 className="text-lg font-bold text-[var(--studio-ink)] mb-2">Mô Phỏng Sai Lệch</h3>
                <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-4">
                  Mô hình xe tự hành và robot học trên môi trường ảo sai tỉ lệ sẽ thất bại hoàn toàn khi triển khai thực địa.
                </p>
              </div>
              <div className="p-3 rounded bg-[var(--studio-paper-sunken)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]">
                Lãng phí tài nguyên GPU và thời gian huấn luyện AI.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 03 / QUY TRÌNH 4 BƯỚC (#workflow) ── */}
      <section id="workflow" className="py-20 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-3xl mb-12">
            <p className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-2">
              03 / QUY TRÌNH
            </p>
            <h2 className="text-3xl font-extrabold tracking-tight text-[var(--studio-ink)]">
              Từ File Video Thô đến Scene Đã Duyệt
            </h2>
            <p className="text-sm text-[var(--studio-ink-muted)] mt-2">
              Người dùng luôn biết scene đang ở giai đoạn nào, ai cần làm gì tiếp theo và kết quả nào có thể tin cậy.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 font-mono-tech">
            <div className="p-5 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-3">
              <div className="flex justify-between items-center text-xs">
                <span className="font-bold text-[var(--studio-ember)]">BƯỚC 01</span>
                <span className="text-[var(--studio-ink-muted)]">NẠP DỮ LIỆU</span>
              </div>
              <h4 className="text-sm font-bold text-[var(--studio-ink)] font-sans">Thu Thập & Khai Báo</h4>
              <p className="text-xs text-[var(--studio-ink-muted)] font-sans leading-relaxed">
                Tải lên video MP4 hoặc scan LiDAR. Khai báo quyền sử dụng và vượt qua cổng kiểm tra riêng tư.
              </p>
            </div>

            <div className="p-5 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-3">
              <div className="flex justify-between items-center text-xs">
                <span className="font-bold text-[var(--studio-geometry)]">BƯỚC 02</span>
                <span className="text-[var(--studio-geometry)]">TÁI TẠO 3D</span>
              </div>
              <h4 className="text-sm font-bold text-[var(--studio-ink)] font-sans">Tái Tạo & Quy Đổi Mét</h4>
              <p className="text-xs text-[var(--studio-ink-muted)] font-sans leading-relaxed">
                Tạo bản xem 3DGS, tính quỹ đạo camera. Người dùng xác nhận tỉ lệ mét hoặc tự động căn chỉnh bằng LiDAR.
              </p>
            </div>

            <div className="p-5 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-3">
              <div className="flex justify-between items-center text-xs">
                <span className="font-bold text-[var(--studio-ochre)]">BƯỚC 03</span>
                <span className="text-[var(--studio-ochre)]">VẬT LÝ</span>
              </div>
              <h4 className="text-sm font-bold text-[var(--studio-ink)] font-sans">Bóc Tách & Collider</h4>
              <p className="text-xs text-[var(--studio-ink-muted)] font-sans leading-relaxed">
                Khoét vật khỏi mặt sàn, gán collider (hộp bao / convex hull) và thiết lập thông số ma sát vật thể.
              </p>
            </div>

            <div className="p-5 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] space-y-3">
              <div className="flex justify-between items-center text-xs">
                <span className="font-bold text-[var(--studio-sage)]">BƯỚC 04</span>
                <span className="text-[var(--studio-sage)]">PHÁT HÀNH</span>
              </div>
              <h4 className="text-sm font-bold text-[var(--studio-ink)] font-sans">Kiểm Định & Xuất Bản</h4>
              <p className="text-xs text-[var(--studio-ink-muted)] font-sans leading-relaxed">
                Reviewer kiểm tra báo cáo tiền kiểm, duyệt phát hành và tải file OpenUSD (.usda) hoàn chỉnh.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 04 / DỮ LIỆU THẬT TỪ BACKEND (#samples) ── */}
      <section id="samples" className="py-20 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-wrap items-end justify-between gap-4 mb-12">
            <div className="max-w-3xl">
              <p className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-2">
                04 / DỮ LIỆU THẬT
              </p>
              <h2 className="text-3xl font-extrabold tracking-tight text-[var(--studio-ink)]">
                Kịch bản mẫu chạy trực tiếp từ backend
              </h2>
              <p className="text-sm text-[var(--studio-ink-muted)] mt-2">
                Các dataset mẫu có sẵn trong hệ thống — mở trực tiếp từ Studio mà không cần GPU riêng.
              </p>
            </div>
            <span className="text-xs font-mono-tech text-[var(--studio-sage)]">
              ● {apiConnected ? "API SẴN SÀNG" : "OFFLINE"}
            </span>
          </div>

          {samples.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {samples.map((sample) => (
                <div
                  key={sample.sample_id}
                  className="p-5 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2 text-xs font-mono-tech">
                      <span className="px-2 py-0.5 rounded bg-[var(--studio-geometry)]/10 text-[var(--studio-geometry)] font-semibold">
                        {sample.source.dataset} · {sample.source.sequence}
                      </span>
                      <span className="text-[var(--studio-ink-muted)]">
                        {sample.frame_count ? `${sample.frame_count} frames` : "Sẵn sàng"}
                      </span>
                    </div>
                    <h4 className="text-base font-bold text-[var(--studio-ink)] mb-1">
                      {sample.title}
                    </h4>
                    <p className="text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-4">
                      {sample.description}
                    </p>
                  </div>

                  <div className="pt-3 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between">
                    <Link
                      href={`/new/try-demo?sample=${encodeURIComponent(sample.sample_id)}`}
                      className="text-xs font-semibold text-[var(--studio-ember-strong)] hover:text-[var(--studio-ember)] flex items-center gap-1 group"
                    >
                      <span>Mở kịch bản mẫu này</span>
                      <span className="transform group-hover:translate-x-1 transition-transform">→</span>
                    </Link>
                    <span className="text-[10px] font-mono-tech text-[var(--studio-sage)]">ĐÃ TÁI TẠO</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] text-xs text-[var(--studio-ink-muted)]">
              {isLoadingApi ? "Đang kết nối backend để tải danh sách mẫu..." : "Chưa có bundle demo nào được xuất bản."}
            </div>
          )}
        </div>
      </section>

      {/* ── BẮT ĐẦU CÙNG REAL2SIM STUDIO (#start) ── */}
      <section id="start" className="py-20 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-10 items-center">
            <div className="md:col-span-6 space-y-4">
              <p className="text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold">
                BẮT ĐẦU CÙNG REAL2SIM STUDIO
              </p>
              <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)]">
                Tái tạo scene của bạn ngay hôm nay.
              </h2>
              <p className="text-sm text-[var(--studio-ink-muted)] leading-relaxed">
                Đưa video hoặc scan thực tế vào Studio, kiểm tra trực quan và xuất file mô phỏng đã kiểm định chỉ trong vài bước.
              </p>
              <div className="pt-2">
                <Link
                  href={STUDIO_ENTRY}
                  aria-label="Open Real2Sim Studio"
                  className="inline-flex items-center justify-center px-7 py-3.5 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm"
                >
                  Mở Real2Sim Studio →
                </Link>
              </div>
            </div>

            <div className="md:col-span-6 space-y-4 font-mono-tech text-xs">
              <div className="p-4 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex items-start gap-3">
                <span className="font-bold text-[var(--studio-ember-strong)]">01</span>
                <div>
                  <strong className="text-[var(--studio-ink)] block font-sans text-sm mb-0.5">Thử nghiệm kịch bản mẫu</strong>
                  <span className="text-[var(--studio-ink-muted)] font-sans">
                    Xem trước tiến trình và kết quả trên các dataset mẫu có sẵn mà không cần GPU riêng.
                  </span>
                </div>
              </div>

              <div className="p-4 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex items-start gap-3">
                <span className="font-bold text-[var(--studio-geometry)]">02</span>
                <div>
                  <strong className="text-[var(--studio-ink)] block font-sans text-sm mb-0.5">Tải video hiện trường</strong>
                  <span className="text-[var(--studio-ink-muted)] font-sans">
                    Nạp dữ liệu của bạn, điều chỉnh thông số xử lý phù hợp với năng lực máy worker.
                  </span>
                </div>
              </div>

              <div className="p-4 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] flex items-start gap-3">
                <span className="font-bold text-[var(--studio-sage)]">03</span>
                <div>
                  <strong className="text-[var(--studio-ink)] block font-sans text-sm mb-0.5">Xuất sang NVIDIA Isaac Sim</strong>
                  <span className="text-[var(--studio-ink-muted)] font-sans">
                    Tải về gói OpenUSD (.usda) đã qua kiểm định để chạy huấn luyện trực tiếp.
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── FOOTER CHÂN TRANG ── */}
      <footer id="documentation" className="py-14 bg-[var(--studio-paper)] border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6 pb-8 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)]">
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <div className="w-5 h-5 rounded bg-[var(--studio-viewport)] flex items-center justify-center p-1">
                  <svg viewBox="0 0 24 24" fill="none" className="w-full h-full" aria-hidden="true">
                    <path d="M12 2L3 7L12 12L21 7L12 2Z" stroke="var(--studio-ember)" strokeWidth="2" />
                    <path d="M3 17L12 22L21 17" stroke="var(--studio-geometry)" strokeWidth="1.8" />
                  </svg>
                </div>
                <span className="font-bold text-[var(--studio-ink)] text-sm tracking-tight">Real2Sim Studio</span>
              </div>
              <p className="text-xs text-[var(--studio-ink-muted)] max-w-sm">
                Nền tảng tái tạo không gian thực tế thành scene 3D có cấu trúc cho mô phỏng robotics, có người kiểm duyệt.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-6 text-xs font-medium text-[var(--studio-ink-muted)]">
              <a href="#product" className="hover:text-[var(--studio-ink)] transition-colors">
                Sản phẩm
              </a>
              <a href="#problem" className="hover:text-[var(--studio-ink)] transition-colors">
                Bài toán
              </a>
              <a href="#workflow" className="hover:text-[var(--studio-ink)] transition-colors">
                Quy trình
              </a>
              <a href="#samples" className="hover:text-[var(--studio-ink)] transition-colors">
                Dữ liệu thật
              </a>
              <a href="#start" className="hover:text-[var(--studio-ink)] transition-colors">
                Bắt đầu
              </a>
              <a
                href="https://github.com/AI20K-Build-Phase-Cohort-4/P-087"
                target="_blank"
                rel="noreferrer"
                className="hover:text-[var(--studio-ink)] transition-colors flex items-center gap-1 font-mono-tech"
              >
                GitHub
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            </div>
          </div>

          <div className="pt-6 flex flex-col sm:flex-row items-center justify-between text-xs font-mono-tech text-[var(--studio-ink-muted)] gap-3">
            <div>© 2026 Real2Sim Studio. Bảo lưu mọi quyền.</div>
            <div className="flex items-center gap-4">
              <span className="text-[var(--studio-sage)]">● BẢN XEM TRƯỚC KỸ THUẬT</span>
            </div>
          </div>
        </div>
      </footer>
    </main>
  );
}
