import Link from "next/link";

import { LandingAnchors } from "@/features/landing/LandingAnchors";
import { STUDIO_ENTRY } from "@/lib/routes";

/** Adapt từ export Stitch user cung cấp; SVG/metrics là minh họa, CTA mở app thật qua màn đăng nhập. */
export function LandingPage() {
  return (
    <main id="landing-top" className="landing-page bg-[var(--studio-paper)] text-[var(--studio-ink)] selection:bg-[var(--studio-ember-soft)] selection:text-[var(--studio-ember-strong)]">
      <LandingAnchors />




  <header className={"sticky top-0 z-50 backdrop-blur-md bg-[var(--studio-paper)]/90 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] transition-all"}>
    <div className={"max-w-7xl mx-auto px-4 sm:px-6 min-h-18 py-3 flex items-center justify-between gap-3"}>

      <a href={"#landing-top"} className={"flex items-center gap-3 group"}>
        <div className={"w-8 h-8 rounded-md bg-[var(--studio-viewport)] flex items-center justify-center p-1.5 shadow-sm border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)]"}>
          <svg viewBox={"0 0 24 24"} fill={"none"} className={"w-full h-full"} aria-hidden={"true"}>

            <path d={"M12 2L3 7L12 12L21 7L12 2Z"} stroke={"var(--studio-ember)"} strokeWidth={"2"} strokeLinecap={"round"} strokeLinejoin={"round"} />
            <path d={"M3 17L12 22L21 17"} stroke={"var(--studio-geometry)"} strokeWidth={"1.8"} strokeLinecap={"round"} strokeLinejoin={"round"} />
            <path d={"M3 12L12 17L21 12"} stroke={"var(--studio-ochre)"} strokeWidth={"1.8"} strokeLinecap={"round"} strokeLinejoin={"round"} />
          </svg>
        </div>
        <div className={"flex items-baseline gap-1.5"}>
          <span className={"font-bold tracking-tight text-lg text-[var(--studio-ink)]"}>{"Real2Sim"}</span>
          <span className={"hidden min-[400px]:inline text-xs uppercase tracking-widest font-mono-tech px-1.5 py-0.5 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink-muted)] font-semibold border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>{"Studio"}</span>
        </div>
      </a>


      <nav aria-label="Landing page sections" className={"hidden xl:flex items-center gap-8 text-[14px] font-medium text-[var(--studio-ink-muted)]"}>
        <a href={"#product"} className={"hover:text-[var(--studio-ink)] transition-colors py-1"}>{"Product"}</a>
        <a href={"#workflow"} className={"hover:text-[var(--studio-ink)] transition-colors py-1"}>{"Workflow"}</a>
        <a href={"#technology"} className={"hover:text-[var(--studio-ink)] transition-colors py-1"}>{"Technology"}</a>
        <a href={"#evaluation"} className={"hover:text-[var(--studio-ink)] transition-colors py-1"}>{"Evaluation"}</a>
        <a href={"#documentation"} className={"hover:text-[var(--studio-ink)] transition-colors py-1"}>{"Documentation"}</a>
      </nav>


      <div className={"flex items-center gap-4"}>
        <a href={"#documentation"} className={"hidden sm:inline-flex text-xs font-mono-tech text-[var(--studio-ink-muted)] hover:text-[var(--studio-ink)] items-center gap-1.5"}>
          <span className={"w-1.5 h-1.5 rounded-full bg-[var(--studio-sage)]"}></span>{"\n          Design preview\n        "}</a>
        <Link href={STUDIO_ENTRY} className={"inline-flex items-center justify-center px-4 py-2 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm active:translate-y-px focus:outline-none focus:ring-2 focus:ring-[var(--studio-ember)] focus:ring-offset-2 focus:ring-offset-[var(--studio-paper)]"}>{"\n          Open Studio\n          "}<svg className={"w-4 h-4 ml-1.5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
            <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"2"} d={"M14 5l7 7m0 0l-7 7m7-7H3"} />
          </svg>
        </Link>
      </div>
    </div>

    <p className="border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] px-6 py-2 text-center text-xs text-[var(--studio-ink-muted)]">Design preview · Scene illustrations, metrics and validation statuses are examples. Open Studio to work with actual scenes.</p>
  </header>




  <section className={"relative pt-16 pb-24 md:pt-24 md:pb-32 bg-grid-tech border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] overflow-hidden"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-8 items-center"}>

        <div className={"lg:col-span-6 flex flex-col justify-center"}>

          <div className={"inline-flex flex-wrap items-center gap-2 px-3 py-1.5 rounded-md bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] w-fit mb-6 text-xs font-mono-tech text-[var(--studio-ink-muted)]"}>
            <span className={"w-2 h-2 rounded-full bg-[var(--studio-geometry)] animate-pulse"}></span>
            <span>{"SPATIAL RECONSTRUCTION PIPELINE"}</span>
            <span className={"text-[var(--studio-ink)]/30"}>{"|"}</span>
            <span className={"text-[var(--studio-ink)] font-semibold"}>{"AUTONOMOUS & ROBOTICS"}</span>
          </div>

          <h1 className={"text-4xl sm:text-5xl lg:text-[3.75rem] font-extrabold tracking-tight text-[var(--studio-ink)] leading-[1.08] mb-6"}>{"\n            From Reality"}<br />
            <span className={"text-[var(--studio-ember-strong)]"}>{"to Simulation."}</span>
          </h1>

          <p className={"text-lg sm:text-xl font-medium text-[var(--studio-ink)] mb-4 leading-relaxed"}>{"\n            Turn real-world video and LiDAR data into editable, simulation-ready 3D scenes.\n          "}</p>

          <p className={"text-base text-[var(--studio-ink-muted)] mb-8 leading-relaxed max-w-xl"}>{"\n            Real2Sim Studio reconstructs roads and warehouse environments into structured scenes that engineers can inspect, edit and validate for simulation workflows.\n          "}</p>


          <div className={"flex flex-wrap items-center gap-4 mb-10"}>
            <Link href={STUDIO_ENTRY} className={"px-6 py-3.5 text-sm font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-sm flex items-center gap-2 group"}>
              <span>{"Open Studio"}</span>
              <svg className={"w-4 h-4 transform group-hover:translate-x-1 transition-transform"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"2"} d={"M14 5l7 7m0 0l-7 7m7-7H3"} />
              </svg>
            </Link>
            <a href={"#workflow"} className={"px-6 py-3.5 text-sm font-semibold text-[var(--studio-ink)] rounded-md bg-[var(--studio-paper-raised)] hover:bg-[var(--studio-paper-sunken)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] transition-all shadow-xs"}>{"\n              Explore the workflow\n            "}</a>
          </div>


          <div className={"pt-6 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] grid grid-cols-3 gap-4"}>
            <div>
              <div className={"text-[11px] font-mono-tech uppercase text-[var(--studio-ink-muted)]"}>{"Input Formats"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] mt-0.5"}>{"ROS2 / pcap / MP4"}</div>
            </div>
            <div>
              <div className={"text-[11px] font-mono-tech uppercase text-[var(--studio-ink-muted)]"}>{"Geometry Spec"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] mt-0.5"}>{"Sub-cm Mesh + OBB"}</div>
            </div>
            <div>
              <div className={"text-[11px] font-mono-tech uppercase text-[var(--studio-ink-muted)]"}>{"Target Engines"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] mt-0.5"}>{"CARLA / Isaac Sim"}</div>
            </div>
          </div>
        </div>


        <div className={"lg:col-span-6 viewport-container"}>
          <div className={"relative rounded-xl bg-[var(--studio-viewport)] border border-[var(--studio-ink)] shadow-2xl overflow-hidden p-1"}>

            <div className={"px-4 py-2.5 bg-[var(--studio-viewport-deep)] flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-paper)_8%,transparent)]"}>
              <div className={"flex items-center gap-2"}>
                <span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-rust)]"}></span>
                <span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-ochre)]"}></span>
                <span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-sage)]"}></span>
                <span className={"ml-2 text-xs font-mono-tech text-[var(--studio-paper)]/60"}>{"VIEWPORT::INDUSTRIAL_WAREHOUSE_RUN_08"}</span>
              </div>
              <div className={"flex items-center gap-3"}>
                <span className={"text-[11px] font-mono-tech px-2 py-0.5 rounded bg-[var(--studio-geometry)]/20 text-[var(--studio-geometry)] border border-[var(--studio-geometry)]/30"}>{"POINTS: 1,420,800"}</span>
                <span className={"text-[11px] font-mono-tech px-2 py-0.5 rounded bg-[var(--studio-sage)]/20 text-[var(--studio-sage)] border border-[var(--studio-sage)]/30"}>{"VALIDATED"}</span>
              </div>
            </div>


            <div className={"relative h-[440px] w-full bg-[var(--studio-viewport)] bg-grid-dark flex items-center justify-center overflow-hidden"}>


              <div className={"absolute top-4 right-4 z-20 flex flex-col items-center bg-[var(--studio-viewport-deep)]/80 backdrop-blur p-2 rounded border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] font-mono-tech text-[10px]"}>
                <div className={"flex items-center gap-2 text-[var(--studio-ember)]"}><span>{"X"}</span><span className={"text-on-accent/60"}>{"+14.28m"}</span></div>
                <div className={"flex items-center gap-2 text-[var(--studio-sage)]"}><span>{"Y"}</span><span className={"text-on-accent/60"}>{"-03.11m"}</span></div>
                <div className={"flex items-center gap-2 text-[var(--studio-geometry)]"}><span>{"Z"}</span><span className={"text-on-accent/60"}>{"+00.42m"}</span></div>
              </div>


              <div className={"absolute top-4 left-4 z-20 flex flex-col gap-1.5 font-mono-tech text-[11px]"}>
                <div className={"flex items-center gap-2 px-2 py-1 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-paper)]"}>
                  <span className={"w-2 h-2 rounded-sm bg-[var(--studio-geometry)]"}></span>
                  <span>{"Surface Geometry (Mesh)"}</span>
                </div>
                <div className={"flex items-center gap-2 px-2 py-1 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-paper)]"}>
                  <span className={"w-2 h-2 rounded-sm bg-[var(--studio-ochre)]"}></span>
                  <span>{"Physical Colliders (Convex)"}</span>
                </div>
                <div className={"flex items-center gap-2 px-2 py-1 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-ember)]"}>
                  <span className={"w-2 h-2 rounded-sm bg-[var(--studio-ember)] animate-ping"}></span>
                  <span>{"Selected: Forklift_AGV_02"}</span>
                </div>
              </div>


              <svg viewBox={"0 0 680 440"} className={"w-full h-full z-10 p-4"} aria-hidden={"true"}>
                <defs>

                  <linearGradient id={"groundGrad"} x1={"0"} y1={"0"} x2={"0"} y2={"1"}>
                    <stop offset={"0%"} stopColor={"var(--studio-geometry)"} stopOpacity={"0.1"} />
                    <stop offset={"100%"} stopColor={"var(--studio-geometry)"} stopOpacity={"0.0"} />
                  </linearGradient>

                  <pattern id={"pts"} width={"16"} height={"16"} patternUnits={"userSpaceOnUse"}>
                    <circle cx={"2"} cy={"2"} r={"0.9"} fill={"var(--studio-geometry)"} opacity={"0.45"} />
                    <circle cx={"10"} cy={"10"} r={"0.9"} fill={"var(--studio-geometry)"} opacity={"0.25"} />
                  </pattern>
                </defs>


                <polygon points={"340,110 630,240 340,390 50,240"} fill={"url(#groundGrad)"} stroke={"var(--studio-geometry)"} strokeWidth={"1.2"} strokeOpacity={"0.35"} />
                <polygon points={"340,110 630,240 340,390 50,240"} fill={"url(#pts)"} />


                <line x1={"340"} y1={"250"} x2={"520"} y2={"330"} stroke={"var(--studio-ember)"} strokeWidth={"2"} strokeOpacity={"0.7"} />
                <line x1={"340"} y1={"250"} x2={"160"} y2={"330"} stroke={"var(--studio-sage)"} strokeWidth={"2"} strokeOpacity={"0.7"} />
                <line x1={"340"} y1={"250"} x2={"340"} y2={"150"} stroke={"var(--studio-geometry)"} strokeWidth={"2"} strokeOpacity={"0.7"} />


                <path d={"M 230,290 L 450,210"} stroke={"var(--studio-paper)"} strokeWidth={"2.5"} strokeDasharray={"10 8"} strokeOpacity={"0.6"} />
                <path d={"M 270,310 L 490,230"} stroke={"var(--studio-paper)"} strokeWidth={"1.5"} strokeOpacity={"0.3"} />


                <g fill={"var(--studio-geometry)"} opacity={"0.75"}>
                  <circle cx={"170"} cy={"210"} r={"1.5"} /><circle cx={"175"} cy={"208"} r={"1.2"} /><circle cx={"182"} cy={"212"} r={"1.6"} />
                  <circle cx={"190"} cy={"205"} r={"1.4"} /><circle cx={"195"} cy={"209"} r={"1.2"} /><circle cx={"205"} cy={"215"} r={"1.5"} />
                  <circle cx={"165"} cy={"216"} r={"1.3"} /><circle cx={"178"} cy={"220"} r={"1.4"} /><circle cx={"188"} cy={"218"} r={"1.5"} />

                  <circle cx={"490"} cy={"180"} r={"1.5"} /><circle cx={"500"} cy={"178"} r={"1.2"} /><circle cx={"510"} cy={"182"} r={"1.6"} />
                  <circle cx={"515"} cy={"175"} r={"1.4"} /><circle cx={"525"} cy={"183"} r={"1.5"} /><circle cx={"495"} cy={"186"} r={"1.3"} />
                </g>



                <g stroke={"var(--studio-geometry)"} strokeWidth={"1.5"} fill={"none"} opacity={"0.85"}>
                  <line x1={"140"} y1={"170"} x2={"140"} y2={"240"} />
                  <line x1={"190"} y1={"150"} x2={"190"} y2={"218"} />
                  <line x1={"240"} y1={"170"} x2={"240"} y2={"240"} />
                  <line x1={"190"} y1={"190"} x2={"190"} y2={"262"} />

                  <polygon points={"140,170 190,150 240,170 190,190"} stroke={"var(--studio-geometry)"} strokeWidth={"1.2"} fill={"var(--studio-geometry)"} fillOpacity={"0.08"} />
                  <polygon points={"140,205 190,185 240,205 190,225"} stroke={"var(--studio-geometry)"} strokeWidth={"1.2"} fill={"var(--studio-geometry)"} fillOpacity={"0.08"} />
                  <polygon points={"140,240 190,218 240,240 190,262"} stroke={"var(--studio-geometry)"} strokeWidth={"1.2"} fill={"var(--studio-geometry)"} fillOpacity={"0.08"} />
                </g>

                <g stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} strokeDasharray={"4 3"} fill={"var(--studio-ochre)"} fillOpacity={"0.05"}>
                  <polygon points={"135,160 190,140 245,160 190,180"} />
                  <polygon points={"135,245 190,225 245,245 190,268"} />
                  <line x1={"135"} y1={"160"} x2={"135"} y2={"245"} />
                  <line x1={"190"} y1={"140"} x2={"190"} y2={"225"} />
                  <line x1={"245"} y1={"160"} x2={"245"} y2={"245"} />
                  <line x1={"190"} y1={"180"} x2={"190"} y2={"268"} />
                </g>
                <text x={"145"} y={"152"} fill={"var(--studio-ochre)"} fontSize={"10"} fontFamily={"monospace"} fontWeight={"bold"}>{"COLLIDER::RACK_STRUCT_01"}</text>



                <polygon points={"310,230 370,205 420,225 360,252"} fill={"var(--studio-ember)"} fillOpacity={"0.18"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />
                <polygon points={"310,255 370,230 420,250 360,277"} fill={"var(--studio-ember)"} fillOpacity={"0.12"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />
                <line x1={"310"} y1={"230"} x2={"310"} y2={"255"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />
                <line x1={"370"} y1={"205"} x2={"370"} y2={"230"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />
                <line x1={"420"} y1={"225"} x2={"420"} y2={"250"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />
                <line x1={"360"} y1={"252"} x2={"360"} y2={"277"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />


                <circle cx={"360"} cy={"277"} r={"3"} fill={"var(--studio-ember)"} />
                <circle cx={"310"} cy={"255"} r={"3"} fill={"var(--studio-ember)"} />
                <circle cx={"420"} cy={"250"} r={"3"} fill={"var(--studio-ember)"} />
                <circle cx={"370"} cy={"230"} r={"3"} fill={"var(--studio-ember)"} />


                <line x1={"365"} y1={"210"} x2={"440"} y2={"150"} stroke={"var(--studio-ember)"} strokeWidth={"1.2"} strokeDasharray={"3 2"} />
                <circle cx={"365"} cy={"210"} r={"4"} fill={"none"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />
                <g transform={"translate(440, 130)"}>
                  <rect width={"160"} height={"42"} rx={"4"} fill={"var(--studio-viewport-deep)"} stroke={"var(--studio-ember)"} strokeWidth={"1.2"} />
                  <text x={"10"} y={"17"} fill={"var(--studio-paper)"} fontSize={"10"} fontFamily={"monospace"} fontWeight={"bold"}>{"FORKLIFT_PALLET_02"}</text>
                  <text x={"10"} y={"32"} fill={"var(--studio-sage)"} fontSize={"9"} fontFamily={"monospace"}>{"VALID_KINEMATICS [OK]"}</text>
                </g>


                <polygon points={"460,250 510,230 550,248 500,270"} fill={"var(--studio-ochre)"} fillOpacity={"0.12"} stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} />
                <polygon points={"460,275 510,255 550,273 500,295"} fill={"var(--studio-ochre)"} fillOpacity={"0.08"} stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} />
                <line x1={"460"} y1={"250"} x2={"460"} y2={"275"} stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} />
                <line x1={"510"} y1={"230"} x2={"510"} y2={"255"} stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} />
                <line x1={"550"} y1={"248"} x2={"550"} y2={"273"} stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} />
                <line x1={"500"} y1={"270"} x2={"500"} y2={"295"} stroke={"var(--studio-ochre)"} strokeWidth={"1.5"} />


                <path d={"M 280,330 Q 320,300 370,305 T 440,285"} fill={"none"} stroke={"var(--studio-geometry)"} strokeWidth={"2"} strokeDasharray={"4 3"} />
                <polygon points={"310,312 322,314 316,324"} fill={"var(--studio-geometry)"} />
                <polygon points={"390,298 402,296 398,308"} fill={"var(--studio-geometry)"} />
                <text x={"325"} y={"338"} fill={"var(--studio-geometry)"} fontSize={"9"} fontFamily={"monospace"}>{"LiDAR POSE TRAJECTORY (120 Hz)"}</text>
              </svg>


              <div className={"absolute bottom-3 inset-x-4 flex items-center justify-between z-20 font-mono-tech text-xs"}>
                <div className={"flex items-center gap-1.5 bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] rounded px-2.5 py-1 text-[var(--studio-paper)]/70"}>
                  <span className={"text-[var(--studio-geometry)] font-bold"}>{"MODE:"}</span>
                  <span>{"INSPECT / MESH EDIT"}</span>
                </div>
                <div className={"flex items-center gap-2"}>
                  <span className={"px-2 py-0.5 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-paper)]/70 text-[10px]"}>{"FOV: 65°"}</span>
                  <span className={"px-2 py-0.5 rounded bg-[var(--studio-viewport-deep)]/90 border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-paper)]/70 text-[10px]"}>{"FPS: 60.0"}</span>
                  <span className={"px-2 py-0.5 rounded bg-[var(--studio-sage)]/20 text-[var(--studio-sage)] border border-[var(--studio-sage)]/40 text-[10px] font-semibold"}>{"SIM_READY"}</span>
                </div>
              </div>

            </div>
          </div>
        </div>
      </div>

    </div>
  </section>




  <section className={"py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>
      <div className={"max-w-3xl mb-16"}>
        <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"01 / The Spatial Bottleneck"}</div>
        <h2 className={"text-3xl sm:text-4xl lg:text-[2.75rem] font-extrabold tracking-tight text-[var(--studio-ink)] leading-[1.15] mb-6"}>{"\n          Reality is rich."}<br />
          <span className={"text-[var(--studio-ink-muted)]"}>{"Simulation needs structure."}</span>
        </h2>
        <p className={"text-lg text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n          Raw video sequences and dense LiDAR point clouds contain immense spatial truth. Yet converting unorganized scans into editable, physically-grounded simulation assets remains fragmented, manual, and prone to weeks of cleanup.\n        "}</p>
      </div>


      <div className={"grid grid-cols-1 md:grid-cols-3 gap-8"}>


        <div className={"p-8 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between shadow-xs"}>
          <div>
            <div className={"flex items-center justify-between mb-6"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] px-2 py-1 rounded bg-[var(--studio-paper-sunken)]"}>{"STAGE 01"}</span>
              <span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-ink-muted)]"}></span>
            </div>
            <h3 className={"text-xl font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"CAPTURE"}</h3>
            <div className={"text-sm font-semibold text-[var(--studio-geometry)] font-mono-tech mb-4"}>{"Video + LiDAR"}</div>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Multi-sensor drive-by and aerial captures generate massive point sets, lens distortion, dynamic occlusions, and sparse timestamps without semantic grounding.\n            "}</p>
          </div>
          <div className={"p-3.5 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs text-[var(--studio-ink)]/80"}>
            <span className={"text-[var(--studio-ink-muted)]"}>{"Raw State:"}</span>{" Unstructured pcap streams, rolling shutter frames, no object primitives.\n          "}</div>
        </div>


        <div className={"p-8 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between shadow-xs"}>
          <div>
            <div className={"flex items-center justify-between mb-6"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-geometry)] px-2 py-1 rounded bg-[var(--studio-geometry)]/10 border border-[var(--studio-geometry)]/20"}>{"STAGE 02"}</span>
              <span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-geometry)]"}></span>
            </div>
            <h3 className={"text-xl font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"RECONSTRUCT"}</h3>
            <div className={"text-sm font-semibold text-[var(--studio-geometry)] font-mono-tech mb-4"}>{"Geometry + Spatial Structure"}</div>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Automated bundle adjustment, neural surface reconstruction, and ground-plane segmentation extract continuous metric surfaces and calibrated camera rigs.\n            "}</p>
          </div>
          <div className={"p-3.5 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs text-[var(--studio-ink)]/80"}>
            <span className={"text-[var(--studio-geometry)]"}>{"Solved:"}</span>{" Watertight meshes, sub-centimeter alignment, normal consistency.\n          "}</div>
        </div>


        <div className={"p-8 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ember-strong)]/40 transition-all flex flex-col justify-between shadow-xs"}>
          <div>
            <div className={"flex items-center justify-between mb-6"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ember-strong)] px-2 py-1 rounded bg-[var(--studio-ember-soft)] border border-[var(--studio-ember-strong)]/20"}>{"STAGE 03"}</span>
              <span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-ember-strong)]"}></span>
            </div>
            <h3 className={"text-xl font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"SIMULATE"}</h3>
            <div className={"text-sm font-semibold text-[var(--studio-ember-strong)] font-mono-tech mb-4"}>{"Editable + Validated Scene"}</div>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Reconstructed assets are decomposed into discrete physical entities with collision envelopes, kinematic constraints, semantic classes, and verified topology.\n            "}</p>
          </div>
          <div className={"p-3.5 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] font-mono-tech text-xs text-[var(--studio-ink)]/80"}>
            <span className={"text-[var(--studio-ember-strong)]"}>{"Output:"}</span>{" USD, URDF, OpenSCENARIO packages ready for physics runtimes.\n          "}</div>
        </div>

      </div>
    </div>
  </section>




  <section id={"workflow"} className={"py-24 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"flex flex-col md:flex-row md:items-end justify-between mb-16 gap-6"}>
        <div>
          <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"02 / End-to-End Pipeline"}</div>
          <h2 className={"text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)]"}>{"\n            One workflow from capture to simulation.\n          "}</h2>
        </div>
        <div className={"flex items-center gap-4 text-xs font-mono-tech text-[var(--studio-ink-muted)]"}>
          <span className={"inline-flex items-center gap-1.5"}><span className={"w-2 h-2 rounded bg-[var(--studio-ember)]"}></span>{" Active / Flow"}</span>
          <span className={"inline-flex items-center gap-1.5"}><span className={"w-2 h-2 rounded bg-[var(--studio-geometry)]"}></span>{" Data & Geometry"}</span>
          <span className={"inline-flex items-center gap-1.5"}><span className={"w-2 h-2 rounded bg-[var(--studio-ochre)]"}></span>{" Physical / Collider"}</span>
        </div>
      </div>


      <div className={"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 relative"}>


        <div className={"bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-xs relative flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
              <span className={"text-2xl font-mono-tech font-bold text-[var(--studio-ember)]"}>{"01"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-ink-muted)] bg-[var(--studio-paper-sunken)] px-2 py-0.5 rounded"}>{"INGEST"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"CAPTURE"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Ingest raw feeds from vehicular or robotic perception suites with sensor timestamps.\n            "}</p>
            <div className={"space-y-2"}>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Video"}</span>
                <span className={"text-[var(--studio-geometry)]"}>{"RGB 4K @ 60fps"}</span>
              </div>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"LiDAR"}</span>
                <span className={"text-[var(--studio-geometry)]"}>{"128-beam packet"}</span>
              </div>
            </div>
          </div>
          <div className={"mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>
            <span>{"Time-synchronized"}</span>
            <span className={"text-[var(--studio-ember)] font-bold"}>{"→ Next"}</span>
          </div>
        </div>


        <div className={"bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-xs relative flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
              <span className={"text-2xl font-mono-tech font-bold text-[var(--studio-geometry)]"}>{"02"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-geometry)] bg-[var(--studio-geometry)]/10 px-2 py-0.5 rounded"}>{"SOLVE"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"RECONSTRUCT"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Extract accurate metric surfaces, ground plane curvature, and 6-DoF sensor trajectories.\n            "}</p>
            <div className={"space-y-2"}>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Geometry"}</span>
                <span className={"text-[var(--studio-geometry)]"}>{"TSDF / Poisson"}</span>
              </div>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Camera Structure"}</span>
                <span className={"text-[var(--studio-geometry)]"}>{"SE(3) Rigs"}</span>
              </div>
            </div>
          </div>
          <div className={"mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>
            <span>{"Metric Calibration"}</span>
            <span className={"text-[var(--studio-ember)] font-bold"}>{"→ Next"}</span>
          </div>
        </div>


        <div className={"bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-xs relative flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
              <span className={"text-2xl font-mono-tech font-bold text-[var(--studio-ochre)]"}>{"03"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-ochre)] bg-[var(--studio-ochre)]/10 px-2 py-0.5 rounded"}>{"DECOMPOSE"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"BUILD SCENE"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Isolate static scenery from dynamic obstacles and assign physics-based collision proxies.\n            "}</p>
            <div className={"space-y-2"}>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Scene Graph"}</span>
                <span className={"text-[var(--studio-ochre)]"}>{"USD Schema"}</span>
              </div>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Semantic Objects"}</span>
                <span className={"text-[var(--studio-ochre)]"}>{"V-HACD Hull"}</span>
              </div>
            </div>
          </div>
          <div className={"mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>
            <span>{"Physical Colliders"}</span>
            <span className={"text-[var(--studio-ember)] font-bold"}>{"→ Next"}</span>
          </div>
        </div>


        <div className={"bg-[var(--studio-paper-raised)] p-7 rounded-lg border border-[var(--studio-ember-strong)]/40 shadow-sm relative flex flex-col justify-between"}>
          <div className={"absolute -top-2.5 right-4 bg-[var(--studio-ember-strong)] text-on-accent text-[10px] font-mono-tech px-2 py-0.5 rounded font-bold"}>{"\n            PRODUCTION READY\n          "}</div>
          <div>
            <div className={"flex items-center justify-between pb-4 mb-4 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
              <span className={"text-2xl font-mono-tech font-bold text-[var(--studio-sage)]"}>{"04"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-sage)] bg-[var(--studio-sage)]/10 px-2 py-0.5 rounded"}>{"VERIFY"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"VALIDATE"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Run automated collision manifold audits, normal verification, and packaging checks.\n            "}</p>
            <div className={"space-y-2"}>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Simulation Pkg"}</span>
                <span className={"text-[var(--studio-sage)]"}>{"USD / URDF"}</span>
              </div>
              <div className={"px-3 py-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)] flex items-center justify-between text-xs font-mono-tech"}>
                <span className={"text-[var(--studio-ink)] font-medium"}>{"Validation Report"}</span>
                <span className={"text-[var(--studio-sage)]"}>{"Pass (0 warnings)"}</span>
              </div>
            </div>
          </div>
          <div className={"mt-8 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] flex items-center justify-between text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>
            <span>{"Engine Export"}</span>
            <span className={"text-[var(--studio-sage)] font-bold"}>{"Ready"}</span>
          </div>
        </div>

      </div>
    </div>
  </section>




  <section id={"product"} className={"py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"max-w-3xl mb-14"}>
        <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"03 / Studio Environment"}</div>
        <h2 className={"text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4"}>{"\n          Engineered for high-fidelity spatial inspection.\n        "}</h2>
        <p className={"text-base text-[var(--studio-ink-muted)]"}>{"\n          A unified cockpit designed for autonomous vehicle simulation teams and robotics labs. Inspect raw point distributions, edit convex collision hulls, and export clean simulation packages without leaving your browser.\n        "}</p>
      </div>


      <div id={"studio-viewport"} className={"grid grid-cols-1 lg:grid-cols-12 gap-8 items-start"}>


        <div className={"lg:col-span-8 bg-[var(--studio-paper-raised)] rounded-xl border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] shadow-xl overflow-hidden"}>


          <div className={"h-12 bg-[var(--studio-paper-sunken)] px-4 flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
            <div className={"flex items-center gap-3"}>
              <span className={"text-xs font-bold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2.5 h-2.5 bg-[var(--studio-ember-strong)] rounded-xs"}></span>{"\n                SCENE_IR::ROAD_JUNCTION_URBAN_4WAY\n              "}</span>
              <span className={"text-[11px] font-mono-tech px-2 py-0.5 rounded bg-[var(--studio-paper-raised)] text-[var(--studio-ink-muted)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_15%,transparent)]"}>{"AUTOPILOT_SUITE_V2"}</span>
            </div>
            <div className={"flex items-center gap-2"}>
              <button className={"px-2.5 py-1 text-xs font-mono-tech rounded bg-[var(--studio-paper-raised)] text-[var(--studio-ink)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] hover:bg-[var(--studio-paper)]"} disabled title={"Illustration only — open Studio for interactive tools"} type={"button"}>{"Recalculate Mesh"}</button>
              <button className={"px-2.5 py-1 text-xs font-mono-tech rounded bg-[var(--studio-ember-strong)] text-on-accent hover:bg-[var(--studio-ember)] font-semibold"} disabled title={"Illustration only — open Studio for interactive tools"} type={"button"}>{"Export USD"}</button>
            </div>
          </div>


          <div className={"grid grid-cols-12 h-[520px]"}>


            <div className={"col-span-3 bg-[var(--studio-paper-raised)] border-r border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] p-3 flex flex-col justify-between overflow-y-auto font-mono-tech text-xs"}>
              <div>
                <div className={"text-[10px] uppercase tracking-wider text-[var(--studio-ink-muted)] font-bold mb-2 pb-1 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>{"\n                  Scene Hierarchy\n                "}</div>
                <div className={"space-y-1"}>

                  <div className={"flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-ink-muted)]"}>{"▾"}</span>
                    <span className={"text-[var(--studio-geometry)]"}>{"■"}</span>
                    <span className={"font-medium truncate"}>{"WorldRoot"}</span>
                  </div>
                  <div className={"pl-3 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-ink-muted)]"}>{"▾"}</span>
                    <span className={"text-[var(--studio-geometry)]"}>{"■"}</span>
                    <span className={"truncate"}>{"Ground_Terrain"}</span>
                  </div>
                  <div className={"pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-geometry)]"}>{"●"}</span>
                    <span className={"truncate"}>{"Asphalt_Surface_01"}</span>
                  </div>
                  <div className={"pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-ochre)]"}>{"▲"}</span>
                    <span className={"truncate"}>{"Curbs_Collider"}</span>
                  </div>
                  <div className={"pl-3 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-ink-muted)]"}>{"▾"}</span>
                    <span className={"text-[var(--studio-ember)]"}>{"■"}</span>
                    <span className={"font-medium truncate"}>{"Dynamic_Entities"}</span>
                  </div>

                  <div className={"pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded bg-[var(--studio-ember-soft)] text-[var(--studio-ember-strong)] font-semibold cursor-pointer border border-[var(--studio-ember)]/40"}>
                    <span className={"text-[var(--studio-ember)]"}>{"★"}</span>
                    <span className={"truncate"}>{"Sedan_Obstacle_04"}</span>
                  </div>
                  <div className={"pl-6 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-ochre)]"}>{"▲"}</span>
                    <span className={"truncate"}>{"Convex_Hull_04"}</span>
                  </div>
                  <div className={"pl-3 flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] cursor-pointer"}>
                    <span className={"text-[var(--studio-ink-muted)]"}>{"▸"}</span>
                    <span className={"text-[var(--studio-sage)]"}>{"■"}</span>
                    <span className={"truncate"}>{"Sensors_Rig"}</span>
                  </div>
                </div>
              </div>


              <div className={"pt-3 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] space-y-1.5"}>
                <div className={"text-[10px] uppercase tracking-wider text-[var(--studio-ink-muted)] font-bold"}>{"Display Layers"}</div>
                <label className={"flex items-center gap-2 text-[11px] text-[var(--studio-ink)] cursor-pointer"}>
                  <input type={"checkbox"} defaultChecked className={"rounded accent-[var(--studio-geometry)]"} disabled title={"Illustration only — open Studio for interactive tools"} />
                  <span className={"text-[var(--studio-geometry)]"}>{"Geometry Layer"}</span>
                </label>
                <label className={"flex items-center gap-2 text-[11px] text-[var(--studio-ink)] cursor-pointer"}>
                  <input type={"checkbox"} defaultChecked className={"rounded accent-[var(--studio-ochre)]"} disabled title={"Illustration only — open Studio for interactive tools"} />
                  <span className={"text-[var(--studio-ochre)]"}>{"Collider Hull"}</span>
                </label>
                <label className={"flex items-center gap-2 text-[11px] text-[var(--studio-ink)] cursor-pointer"}>
                  <input type={"checkbox"} defaultChecked className={"rounded accent-[var(--studio-ember)]"} disabled title={"Illustration only — open Studio for interactive tools"} />
                  <span className={"text-[var(--studio-ember)]"}>{"Bounding Boxes"}</span>
                </label>
              </div>
            </div>


            <div className={"col-span-6 bg-[var(--studio-viewport)] relative flex flex-col justify-between p-3 overflow-hidden"}>

              <div className={"absolute inset-0 bg-grid-dark opacity-80 pointer-events-none"}></div>


              <div className={"relative z-10 flex items-center justify-between font-mono-tech text-[11px]"}>
                <div className={"flex items-center gap-2 bg-[var(--studio-viewport-deep)]/90 backdrop-blur px-2 py-1 rounded border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-paper)]"}>
                  <span className={"w-1.5 h-1.5 rounded-full bg-[var(--studio-sage)]"}></span>
                  <span>{"CAM: ORBIT_FREE [45°, -18°]"}</span>
                </div>
                <div className={"bg-[var(--studio-viewport-deep)]/90 px-2 py-1 rounded border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[var(--studio-geometry)]"}>
                  <span>{"RES: 0.02m VOXEL"}</span>
                </div>
              </div>


              <div className={"relative z-0 my-auto flex items-center justify-center"}>
                <svg viewBox={"0 0 360 260"} className={"w-full max-w-[340px] h-auto"} aria-hidden={"true"}>

                  <polygon points={"180,40 330,120 180,210 30,120"} fill={"none"} stroke={"var(--studio-geometry)"} strokeWidth={"1.2"} strokeOpacity={"0.4"} />

                  <line x1={"180"} y1={"40"} x2={"180"} y2={"210"} stroke={"var(--studio-geometry)"} strokeWidth={"0.8"} strokeOpacity={"0.25"} />
                  <line x1={"30"} y1={"120"} x2={"330"} y2={"120"} stroke={"var(--studio-geometry)"} strokeWidth={"0.8"} strokeOpacity={"0.25"} />
                  <line x1={"105"} y1={"80"} x2={"255"} y2={"165"} stroke={"var(--studio-geometry)"} strokeWidth={"0.8"} strokeOpacity={"0.25"} />
                  <line x1={"255"} y1={"80"} x2={"105"} y2={"165"} stroke={"var(--studio-geometry)"} strokeWidth={"0.8"} strokeOpacity={"0.25"} />


                  <path d={"M 60,110 L 170,175"} stroke={"var(--studio-ochre)"} strokeWidth={"2"} strokeDasharray={"3 3"} />
                  <path d={"M 300,110 L 190,175"} stroke={"var(--studio-ochre)"} strokeWidth={"2"} strokeDasharray={"3 3"} />


                  <g transform={"translate(0, -10)"}>

                    <polygon points={"150,110 190,90 230,110 190,132"} fill={"var(--studio-ember)"} fillOpacity={"0.2"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />
                    <polygon points={"150,135 190,115 230,135 190,157"} fill={"var(--studio-ember)"} fillOpacity={"0.1"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />
                    <line x1={"150"} y1={"110"} x2={"150"} y2={"135"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />
                    <line x1={"190"} y1={"90"} x2={"190"} y2={"115"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />
                    <line x1={"230"} y1={"110"} x2={"230"} y2={"135"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />
                    <line x1={"190"} y1={"132"} x2={"190"} y2={"157"} stroke={"var(--studio-ember)"} strokeWidth={"1.8"} />


                    <circle cx={"190"} cy={"120"} r={"2.5"} fill={"var(--studio-ember)"} />
                    <line x1={"190"} y1={"120"} x2={"215"} y2={"120"} stroke={"var(--studio-ember)"} strokeWidth={"1.5"} />
                    <line x1={"190"} y1={"120"} x2={"190"} y2={"100"} stroke={"var(--studio-sage)"} strokeWidth={"1.5"} />
                  </g>


                  <polygon points={"90,135 120,120 145,135 115,150"} fill={"var(--studio-ochre)"} fillOpacity={"0.15"} stroke={"var(--studio-ochre)"} strokeWidth={"1.2"} strokeDasharray={"2 2"} />


                  <g transform={"translate(195, 60)"}>
                    <rect width={"110"} height={"28"} rx={"3"} fill={"var(--studio-viewport-deep)"} stroke={"var(--studio-ember)"} strokeWidth={"1"} />
                    <text x={"8"} y={"13"} fill={"var(--studio-paper)"} fontSize={"9"} fontFamily={"monospace"} fontWeight={"bold"}>{"TARGET_SEDAN"}</text>
                    <text x={"8"} y={"23"} fill={"var(--studio-ember)"} fontSize={"8"} fontFamily={"monospace"}>{"VEL: +8.4 m/s"}</text>
                  </g>
                </svg>
              </div>


              <div className={"relative z-10 flex items-center justify-between font-mono-tech text-[10px] text-[var(--studio-paper)]/60 bg-[var(--studio-viewport-deep)]/80 backdrop-blur px-2.5 py-1 rounded border border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)]"}>
                <span className={"flex items-center gap-1.5"}>
                  <span className={"w-1.5 h-1.5 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                  PHYSICS SIMULATION READY\n                "}</span>
                <span>{"TRIANGLES: 84,210 | VERTICES: 42,912"}</span>
              </div>
            </div>


            <div className={"col-span-3 bg-[var(--studio-paper-raised)] border-l border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] p-3 flex flex-col justify-between overflow-y-auto font-mono-tech text-xs"}>
              <div>
                <div className={"text-[10px] uppercase tracking-wider text-[var(--studio-ink-muted)] font-bold mb-2 pb-1 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>{"\n                  Entity Inspector\n                "}</div>


                <div className={"p-2 rounded bg-[var(--studio-paper-sunken)]/70 border border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] mb-3"}>
                  <div className={"text-[10px] text-[var(--studio-ink-muted)]"}>{"IDENTIFIER"}</div>
                  <div className={"font-bold text-[var(--studio-ink)] truncate"}>{"Sedan_Obstacle_04"}</div>
                  <div className={"text-[10px] text-[var(--studio-ember)] font-semibold mt-1"}>{"CLASS: GroundVehicle"}</div>
                </div>

                <div className={"space-y-2 mb-4"}>
                  <div className={"text-[10px] uppercase text-[var(--studio-ink-muted)] font-bold"}>{"Transform (WGS84 / Local)"}</div>
                  <div className={"grid grid-cols-3 gap-1 text-[10px]"}>
                    <div className={"bg-[var(--studio-paper)] p-1 rounded border border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
                      <span className={"text-[var(--studio-ink-muted)]"}>{"X:"}</span>{" 24.12\n                    "}</div>
                    <div className={"bg-[var(--studio-paper)] p-1 rounded border border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
                      <span className={"text-[var(--studio-ink-muted)]"}>{"Y:"}</span>{" -08.45\n                    "}</div>
                    <div className={"bg-[var(--studio-paper)] p-1 rounded border border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
                      <span className={"text-[var(--studio-ink-muted)]"}>{"Z:"}</span>{" +00.18\n                    "}</div>
                  </div>
                </div>

                <div className={"space-y-2 mb-4"}>
                  <div className={"text-[10px] uppercase text-[var(--studio-ink-muted)] font-bold"}>{"Collision Envelope"}</div>
                  <div className={"text-[11px] p-2 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                    <div className={"flex justify-between"}>
                      <span className={"text-[var(--studio-ink-muted)]"}>{"Type:"}</span>
                      <span className={"text-[var(--studio-ochre)] font-semibold"}>{"Convex Decomposition"}</span>
                    </div>
                    <div className={"flex justify-between mt-1"}>
                      <span className={"text-[var(--studio-ink-muted)]"}>{"Hulls:"}</span>
                      <span>{"8 hulls"}</span>
                    </div>
                    <div className={"flex justify-between mt-1"}>
                      <span className={"text-[var(--studio-ink-muted)]"}>{"Margin:"}</span>
                      <span>{"0.005 m"}</span>
                    </div>
                  </div>
                </div>


                <div>
                  <div className={"text-[10px] uppercase text-[var(--studio-ink-muted)] font-bold mb-1.5"}>{"Validation Audit"}</div>
                  <div className={"p-2 rounded bg-[var(--studio-sage)]/10 border border-[var(--studio-sage)]/25 text-[11px] text-[var(--studio-sage)]"}>
                    <div className={"flex items-center gap-1.5 font-bold"}>
                      <svg className={"w-3.5 h-3.5"} viewBox={"0 0 20 20"} fill={"currentColor"} aria-hidden={"true"}>
                        <path fillRule={"evenodd"} d={"M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"} clipRule={"evenodd"} />
                      </svg>{"\n                      Topology Validated\n                    "}</div>
                    <div className={"text-[10px] text-[var(--studio-ink)]/80 mt-1"}>{"\n                      Zero non-manifold edges. Watertight geometry confirmed.\n                    "}</div>
                  </div>
                </div>

              </div>


              <div className={"pt-3 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)]"}>
                <div className={"text-[10px] text-[var(--studio-ink-muted)] font-bold uppercase mb-1"}>{"Viewpoint Presets"}</div>
                <div className={"grid grid-cols-3 gap-1 text-[10px]"}>
                  <button className={"p-1 rounded bg-[var(--studio-paper-sunken)] hover:bg-[var(--studio-paper)] text-center"} disabled title={"Illustration only — open Studio for interactive tools"} type={"button"}>{"Top"}</button>
                  <button className={"p-1 rounded bg-[var(--studio-paper-sunken)] hover:bg-[var(--studio-paper)] text-center"} disabled title={"Illustration only — open Studio for interactive tools"} type={"button"}>{"Driver"}</button>
                  <button className={"p-1 rounded bg-[var(--studio-paper-sunken)] hover:bg-[var(--studio-paper)] text-center"} disabled title={"Illustration only — open Studio for interactive tools"} type={"button"}>{"Sensor"}</button>
                </div>
              </div>
            </div>

          </div>
        </div>


        <div className={"lg:col-span-4 flex flex-col gap-6"}>
          <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs"}>
            <div className={"w-8 h-8 rounded bg-[var(--studio-ember-soft)] text-[var(--studio-ember-strong)] flex items-center justify-center font-mono-tech font-bold text-sm mb-4"}>{"\n              01\n            "}</div>
            <h3 className={"text-base font-bold text-[var(--studio-ink)] mb-2"}>{"Integrated Spatial Viewport"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Examine sub-millimeter reconstructed meshes alongside unprojected LiDAR points in a low-latency WebGL engine built strictly for technical review.\n            "}</p>
          </div>

          <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs"}>
            <div className={"w-8 h-8 rounded bg-[var(--studio-geometry)]/15 text-[var(--studio-geometry)] flex items-center justify-center font-mono-tech font-bold text-sm mb-4"}>{"\n              02\n            "}</div>
            <h3 className={"text-base font-bold text-[var(--studio-ink)] mb-2"}>{"Decoupled Physics & Geometry"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              High-resolution visual textures remain separate from simplified, mathematically stable convex collision hulls, preventing numerical instabilities during sim execution.\n            "}</p>
          </div>

          <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs"}>
            <div className={"w-8 h-8 rounded bg-[var(--studio-sage)]/15 text-[var(--studio-sage)] flex items-center justify-center font-mono-tech font-bold text-sm mb-4"}>{"\n              03\n            "}</div>
            <h3 className={"text-base font-bold text-[var(--studio-ink)] mb-2"}>{"One-Click Validation & Export"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Verify normal directions, penetrations, and kinematics against CARLA, Isaac Sim, and Unreal Engine specs prior to bundling into immutable scene artifacts.\n            "}</p>
          </div>
        </div>

      </div>

    </div>
  </section>




  <section className={"py-24 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"max-w-3xl mb-16"}>
        <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"04 / Capabilities"}</div>
        <h2 className={"text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4"}>{"\n          Core engineering capabilities.\n        "}</h2>
        <p className={"text-base text-[var(--studio-ink-muted)]"}>{"\n          Purpose-built architectural components designed to resolve the boundary between uncurated physical sensory data and deterministic virtual worlds.\n        "}</p>
      </div>


      <div className={"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"}>


        <div className={"p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between"}>
          <div>
            <div className={"w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-geometry)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <svg className={"w-5 h-5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"} />
              </svg>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"1. Multi-source Reconstruction"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Combine visual and spatial data into a unified reconstruction workflow. Ingest synchronized surround cameras, spinning LiDAR, and solid-state sensors without manual extrinsic tuning.\n            "}</p>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-geometry)]"}>{"\n            SENSOR_FUSION::WATERTIGHT\n          "}</div>
        </div>


        <div className={"p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between"}>
          <div>
            <div className={"w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ember-strong)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <svg className={"w-5 h-5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"} />
              </svg>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"2. Editable Scene Representation"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Turn reconstructed environments into structured, editable scenes. Modify road trajectories, relocate shelving units, change weather conditions, and inject novel adversarial hazards.\n            "}</p>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-ember-strong)]"}>{"\n            GRAPH_IR::MUTABLE_SCENE\n          "}</div>
        </div>


        <div className={"p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between"}>
          <div>
            <div className={"w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ochre)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <svg className={"w-5 h-5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"} />
              </svg>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"3. Geometry & Semantic Understanding"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Separate geometric data from semantic and physical information. Distinguish drivable surfaces from vegetative occlusions and structural walls with verified boundary flags.\n            "}</p>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-ochre)]"}>{"\n            SEMANTICS::EXPLICIT_BOUNDS\n          "}</div>
        </div>


        <div className={"p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between"}>
          <div>
            <div className={"w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-geometry)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <svg className={"w-5 h-5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M15 12a3 3 0 11-6 0 3 3 0 016 0z"} />
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"} />
              </svg>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"4. 3D Scene Inspection"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Inspect reconstructed environments through an interactive viewport. Measure clearance, verify surface normal distribution, and audit ground roughness interactively.\n            "}</p>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-geometry)]"}>{"\n            VIEWPORT::INTERACTIVE_AUDIT\n          "}</div>
        </div>


        <div className={"p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between"}>
          <div>
            <div className={"w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-sage)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <svg className={"w-5 h-5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"} />
              </svg>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"5. Simulation Validation"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Validate scene packages before they enter downstream simulation workflows. Automated linters check for intersection collisions, floating bodies, and mesh degeneracy.\n            "}</p>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-sage)]"}>{"\n            LINTER::ZERO_DEFECT_GUARANTEE\n          "}</div>
        </div>


        <div className={"p-7 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] hover:border-[var(--studio-ink-muted)]/40 transition-all flex flex-col justify-between"}>
          <div>
            <div className={"w-10 h-10 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink-muted)] flex items-center justify-center mb-5 border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <svg className={"w-5 h-5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
                <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"1.8"} d={"M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2m-4-1v8m0 0l3-3m-3 3L9 8m-5 5h2.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293h3.172a1 1 0 00.707-.293l2.414-2.414a1 1 0 01.707-.293H20"} />
              </svg>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-2 tracking-tight"}>{"6. Reproducible Scene Packages"}</h3>
            <p className={"text-sm text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n              Produce structured outputs that can be reviewed, shared and reused across distributed teams. Cryptographically signed bundles link back to raw source captures.\n            "}</p>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-xs font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            ARTIFACT::SHA256_PROVENANCE\n          "}</div>
        </div>

      </div>

    </div>
  </section>




  <section id={"technology"} className={"py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"max-w-3xl mb-16"}>
        <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"05 / Architecture"}</div>
        <h2 className={"text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4"}>{"\n          Deterministic transformation pipeline.\n        "}</h2>
        <p className={"text-base text-[var(--studio-ink-muted)]"}>{"\n          A decoupled four-tier compilation flow translating raw sensor telemetry into validated runtime scene artifacts.\n        "}</p>
      </div>


      <div className={"bg-[var(--studio-paper-raised)] rounded-xl border border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)] p-8 lg:p-12 shadow-sm"}>


        <div className={"flex flex-wrap items-center justify-between pb-8 mb-10 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_14%,transparent)] gap-4"}>
          <div className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"\n            COMPILER SPECIFICATION :: R2S-IR-2025\n          "}</div>
          <div className={"flex items-center gap-6 text-xs font-mono-tech"}>
            <span className={"flex items-center gap-2"}><span className={"w-3 h-0.5 bg-[var(--studio-geometry)]"}></span>{" Data Flow Stream"}</span>
            <span className={"flex items-center gap-2"}><span className={"w-2.5 h-2.5 rounded-full bg-[var(--studio-ember)]"}></span>{" Active Compilation Node"}</span>
            <span className={"flex items-center gap-2"}><span className={"w-2.5 h-2.5 rounded bg-[var(--studio-ochre)]"}></span>{" Physics / Collider Schema"}</span>
          </div>
        </div>


        <div className={"grid grid-cols-1 md:grid-cols-4 gap-6 relative"}>


          <div className={"p-6 rounded-lg bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] relative flex flex-col justify-between"}>
            <div className={"mb-6"}>
              <div className={"flex items-center justify-between mb-3"}>
                <span className={"text-xs font-mono-tech text-[var(--studio-ember)] font-bold px-2 py-0.5 rounded bg-[var(--studio-ember-soft)]"}>{"EX-REC"}</span>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-ember)] animate-pulse"}></span>
              </div>
              <h4 className={"text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech"}>{"ReconstructionBundle"}</h4>
              <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n                Raw multimodal calibration, extrinsic estimation, and initial dense depth fusion.\n              "}</p>
            </div>
            <div className={"space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]"}>
              <div className={"text-[var(--studio-geometry)] flex items-center justify-between"}>
                <span>{"+ pose_graph.bin"}</span>
                <span>{"SE(3)"}</span>
              </div>
              <div className={"text-[var(--studio-geometry)] flex items-center justify-between"}>
                <span>{"+ depth_voxels.raw"}</span>
                <span>{"TSDF"}</span>
              </div>
            </div>
          </div>


          <div className={"p-6 rounded-lg bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] relative flex flex-col justify-between"}>
            <div className={"mb-6"}>
              <div className={"flex items-center justify-between mb-3"}>
                <span className={"text-xs font-mono-tech text-[var(--studio-geometry)] font-bold px-2 py-0.5 rounded bg-[var(--studio-geometry)]/10 border border-[var(--studio-geometry)]/20"}>{"EX-SCENE"}</span>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-geometry)]"}></span>
              </div>
              <h4 className={"text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech"}>{"SceneIR"}</h4>
              <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n                Semantic segmentation and parametric geometry decomposition into node graphs.\n              "}</p>
            </div>
            <div className={"space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]"}>
              <div className={"text-[var(--studio-geometry)] flex items-center justify-between"}>
                <span>{"+ surface_mesh.usda"}</span>
                <span>{"Sub-cm"}</span>
              </div>
              <div className={"text-[var(--studio-ochre)] flex items-center justify-between"}>
                <span>{"+ semantic_labels.json"}</span>
                <span>{"Cityscapes"}</span>
              </div>
            </div>
          </div>


          <div className={"p-6 rounded-lg bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] relative flex flex-col justify-between"}>
            <div className={"mb-6"}>
              <div className={"flex items-center justify-between mb-3"}>
                <span className={"text-xs font-mono-tech text-[var(--studio-ochre)] font-bold px-2 py-0.5 rounded bg-[var(--studio-ochre)]/10 border border-[var(--studio-ochre)]/20"}>{"EX-SIM"}</span>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-ochre)]"}></span>
              </div>
              <h4 className={"text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech"}>{"CandidatePackage"}</h4>
              <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n                Generation of convex colliders, kinematic joints, and physics validation audits.\n              "}</p>
            </div>
            <div className={"space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]"}>
              <div className={"text-[var(--studio-ochre)] flex items-center justify-between"}>
                <span>{"+ collision_hulls.obj"}</span>
                <span>{"V-HACD"}</span>
              </div>
              <div className={"text-[var(--studio-sage)] flex items-center justify-between"}>
                <span>{"+ ValidationReport"}</span>
                <span>{"LINTER_OK"}</span>
              </div>
            </div>
          </div>


          <div className={"p-6 rounded-lg bg-[var(--studio-paper)] border border-[var(--studio-ember-strong)]/40 relative flex flex-col justify-between"}>
            <div className={"mb-6"}>
              <div className={"flex items-center justify-between mb-3"}>
                <span className={"text-xs font-mono-tech text-[var(--studio-ember-strong)] font-bold px-2 py-0.5 rounded bg-[var(--studio-ember-soft)]"}>{"EX-PRODUCT"}</span>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>
              </div>
              <h4 className={"text-base font-bold text-[var(--studio-ink)] mb-1 font-mono-tech"}>{"Web Review & Release"}</h4>
              <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed"}>{"\n                Deterministic versioning, collaborative peer approval, and release distribution.\n              "}</p>
            </div>
            <div className={"space-y-1.5 font-mono-tech text-[11px] p-3 rounded bg-[var(--studio-paper-sunken)]/80 text-[var(--studio-ink)]"}>
              <div className={"text-[var(--studio-ink)] flex items-center justify-between"}>
                <span>{"+ Studio Web Review"}</span>
                <span>{"WebGL"}</span>
              </div>
              <div className={"text-[var(--studio-sage)] font-semibold flex items-center justify-between"}>
                <span>{"+ Signed Scene Release"}</span>
                <span>{"CARLA/ISAAC"}</span>
              </div>
            </div>
          </div>

        </div>


        <div className={"mt-8 pt-6 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
          <div className={"flex items-center justify-between text-xs font-mono-tech text-[var(--studio-ink-muted)]"}>
            <span>{"Raw Capture Feeds (LiDAR + Cam)"}</span>
            <span className={"text-[var(--studio-geometry)]"}>{"─── Transform ───"}</span>
            <span className={"text-[var(--studio-ochre)]"}>{"─── Decompose ───"}</span>
            <span className={"text-[var(--studio-sage)]"}>{"─── Validated Target Run ───"}</span>
          </div>
        </div>

      </div>

    </div>
  </section>




  <section id={"evaluation"} className={"py-24 bg-[var(--studio-paper-sunken)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"max-w-3xl mb-16"}>
        <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"06 / Quality Framework"}</div>
        <h2 className={"text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4"}>{"\n          Measure the reconstruction."}<br />
          <span className={"text-[var(--studio-ink-muted)]"}>{"Validate the scene."}</span>
        </h2>
        <p className={"text-base text-[var(--studio-ink-muted)]"}>{"\n          All scene packages pass through a deterministic evaluation harness prior to release. Metric values reflect automated verification pipelines rather than marketing estimates.\n        "}</p>
      </div>


      <div className={"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"}>


        <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between mb-4"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"METRIC CATEGORY 01"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-geometry)] bg-[var(--studio-geometry)]/10 px-2 py-0.5 rounded"}>{"SPATIAL"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-1"}>{"Reconstruction Quality"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Residual re-projection error between camera poses and LiDAR surface samples.\n            "}</p>
            <div className={"p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <div className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1"}>{"Status"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                Coming from validation pipeline\n              "}</div>
              <div className={"mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n                Target: Bundle adjustment residual < 0.4px\n              "}</div>
            </div>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            Benchmark data pending run completion\n          "}</div>
        </div>


        <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between mb-4"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"METRIC CATEGORY 02"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-geometry)] bg-[var(--studio-geometry)]/10 px-2 py-0.5 rounded"}>{"TOLERANCE"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-1"}>{"Geometric Accuracy"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Chamfer distance and point-to-plane deviation verified against survey ground truth.\n            "}</p>
            <div className={"p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <div className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1"}>{"Status"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                Metric pending evaluation\n              "}</div>
              <div className={"mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n                Target: Hausdorff 95% bound < 12mm\n              "}</div>
            </div>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            Sub-millimeter LiDAR audit pending\n          "}</div>
        </div>


        <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between mb-4"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"METRIC CATEGORY 03"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-ochre)] bg-[var(--studio-ochre)]/10 px-2 py-0.5 rounded"}>{"COVERAGE"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-1"}>{"Scene Completeness"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Percentage of occlusion holes reconstructed with closed manifold boundaries.\n            "}</p>
            <div className={"p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <div className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1"}>{"Status"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                Benchmark data\n              "}</div>
              <div className={"mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n                Target: 100% watertight ground plane closure\n              "}</div>
            </div>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            Audited via Poisson reconstructor\n          "}</div>
        </div>


        <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between mb-4"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"METRIC CATEGORY 04"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-ochre)] bg-[var(--studio-ochre)]/10 px-2 py-0.5 rounded"}>{"LABEL"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-1"}>{"Semantic Consistency"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Agreement between visual semantics and 3D bounding envelope definitions.\n            "}</p>
            <div className={"p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <div className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1"}>{"Status"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                Coming from validation pipeline\n              "}</div>
              <div className={"mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n                Target: Multi-view cross-entropy validation\n              "}</div>
            </div>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            Zero unidentified dynamic objects\n          "}</div>
        </div>


        <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between mb-4"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"METRIC CATEGORY 05"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-sage)] bg-[var(--studio-sage)]/10 px-2 py-0.5 rounded"}>{"PHYSICS"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-1"}>{"Simulation Validity"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Manifold penetration checks and rigid-body solver stability across 1,000 sim frames.\n            "}</p>
            <div className={"p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <div className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1"}>{"Status"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                Metric pending evaluation\n              "}</div>
              <div className={"mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n                Target: 0 self-intersections, 0 kinetic spikes\n              "}</div>
            </div>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            PhysX 5.3 headless run verification\n          "}</div>
        </div>


        <div className={"p-6 rounded-lg bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)] shadow-xs flex flex-col justify-between"}>
          <div>
            <div className={"flex items-center justify-between mb-4"}>
              <span className={"text-xs font-mono-tech text-[var(--studio-ink)] font-bold"}>{"METRIC CATEGORY 06"}</span>
              <span className={"text-[11px] font-mono-tech text-[var(--studio-ink-muted)] bg-[var(--studio-paper-sunken)] px-2 py-0.5 rounded"}>{"COMPUTE"}</span>
            </div>
            <h3 className={"text-lg font-bold text-[var(--studio-ink)] mb-1"}>{"Processing Cost"}</h3>
            <p className={"text-xs text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              GPU hours expended per square kilometer of reconstructed industrial space.\n            "}</p>
            <div className={"p-4 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
              <div className={"text-xs font-mono-tech text-[var(--studio-ink-muted)] mb-1"}>{"Status"}</div>
              <div className={"text-sm font-semibold text-[var(--studio-ink)] flex items-center gap-2"}>
                <span className={"w-2 h-2 rounded-full bg-[var(--studio-sage)]"}></span>{"\n                Benchmark data\n              "}</div>
              <div className={"mt-3 text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n                Target: Linear scale across distributed nodes\n              "}</div>
            </div>
          </div>
          <div className={"mt-6 pt-4 border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_10%,transparent)] text-[11px] font-mono-tech text-[var(--studio-ink-muted)]"}>{"\n            Profiled on NVIDIA H100 SXM5 clusters\n          "}</div>
        </div>

      </div>

    </div>
  </section>




  <section className={"py-24 bg-[var(--studio-paper)] border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>

      <div className={"max-w-3xl mb-16"}>
        <div className={"text-xs font-mono-tech uppercase tracking-wider text-[var(--studio-ember-strong)] font-semibold mb-3"}>{"07 / Domain Applications"}</div>
        <h2 className={"text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--studio-ink)] mb-4"}>{"\n          Field-proven across autonomous domains.\n        "}</h2>
        <p className={"text-base text-[var(--studio-ink-muted)]"}>{"\n          Built for teams whose simulation needs demand physical fidelity and zero algorithmic hallucination.\n        "}</p>
      </div>

      <div className={"space-y-8"}>


        <div className={"p-8 lg:p-10 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-sm grid grid-cols-1 lg:grid-cols-12 gap-8 items-center"}>
          <div className={"lg:col-span-7"}>
            <div className={"inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[var(--studio-ember-soft)] text-[var(--studio-ember-strong)] font-mono-tech text-xs font-bold mb-4"}>{"\n              DOMAIN 01 // ADAS & L4 AV\n            "}</div>
            <h3 className={"text-2xl font-bold text-[var(--studio-ink)] mb-3"}>{"AUTONOMOUS DRIVING"}</h3>
            <p className={"text-base text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Convert complex road environments into simulation-ready scenes for closed-loop testing and safety validation. Reconstruct highway interchanges, signalized intersections, and construction corridors directly from fleet logging runs.\n            "}</p>
            <div className={"grid grid-cols-2 gap-4 text-xs font-mono-tech"}>
              <div className={"p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                <span className={"text-[var(--studio-ink-muted)] block"}>{"Trajectory Fidelity"}</span>
                <span className={"text-[var(--studio-ink)] font-semibold"}>{"ASAM OpenDRIVE & OpenSCENARIO"}</span>
              </div>
              <div className={"p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                <span className={"text-[var(--studio-ink-muted)] block"}>{"Adversarial Insertion"}</span>
                <span className={"text-[var(--studio-ink)] font-semibold"}>{"Ghost Cut-ins & Occluded Pedestrians"}</span>
              </div>
            </div>
          </div>
          <div className={"lg:col-span-5 bg-[var(--studio-viewport)] rounded-lg p-5 border border-[var(--studio-ink)] font-mono-tech text-xs text-[var(--studio-paper)]/80 flex flex-col justify-between h-56"}>
            <div className={"flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] pb-2 text-[11px]"}>
              <span className={"text-[var(--studio-ember)]"}>{"SCENE::HIGHWAY_ROUTE_101"}</span>
              <span className={"text-[var(--studio-sage)]"}>{"CALIBRATED"}</span>
            </div>
            <div className={"space-y-2 text-[11px]"}>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Segment Length:"}</span>
                <span>{"2.4 km multi-lane"}</span>
              </div>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Curvature Accuracy:"}</span>
                <span className={"text-[var(--studio-geometry)]"}>{"± 4.2 mm deviation"}</span>
              </div>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Physics Envelope:"}</span>
                <span className={"text-[var(--studio-ochre)]"}>{"Continuous Guardrail Collider"}</span>
              </div>
            </div>
            <div className={"pt-2 border-t border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[10px] text-[var(--studio-sage)]"}>{"\n              ✓ READY FOR CARLA RUNTIME\n            "}</div>
          </div>
        </div>


        <div className={"p-8 lg:p-10 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-sm grid grid-cols-1 lg:grid-cols-12 gap-8 items-center"}>
          <div className={"lg:col-span-7"}>
            <div className={"inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[var(--studio-geometry)]/15 text-[var(--studio-geometry)] font-mono-tech text-xs font-bold mb-4"}>{"\n              DOMAIN 02 // LOGISTICS & AMR\n            "}</div>
            <h3 className={"text-2xl font-bold text-[var(--studio-ink)] mb-3"}>{"ROBOTICS"}</h3>
            <p className={"text-base text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Reconstruct warehouse and industrial environments for robotic simulation. Build exact digital twins of fulfillment centers with racking structures, conveyor belts, and dynamic pallet drops to train navigation and manipulation policies.\n            "}</p>
            <div className={"grid grid-cols-2 gap-4 text-xs font-mono-tech"}>
              <div className={"p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                <span className={"text-[var(--studio-ink-muted)] block"}>{"Kinematic Envelopes"}</span>
                <span className={"text-[var(--studio-ink)] font-semibold"}>{"URDF Joints & Collision Hulls"}</span>
              </div>
              <div className={"p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                <span className={"text-[var(--studio-ink-muted)] block"}>{"Fleet Density"}</span>
                <span className={"text-[var(--studio-ink)] font-semibold"}>{"Multi-AGV Spatial Routing"}</span>
              </div>
            </div>
          </div>
          <div className={"lg:col-span-5 bg-[var(--studio-viewport)] rounded-lg p-5 border border-[var(--studio-ink)] font-mono-tech text-xs text-[var(--studio-paper)]/80 flex flex-col justify-between h-56"}>
            <div className={"flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] pb-2 text-[11px]"}>
              <span className={"text-[var(--studio-geometry)]"}>{"SCENE::FULFILLMENT_BAY_04"}</span>
              <span className={"text-[var(--studio-sage)]"}>{"VALIDATED"}</span>
            </div>
            <div className={"space-y-2 text-[11px]"}>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Floor Area:"}</span>
                <span>{"8,400 m² structured"}</span>
              </div>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Storage Racks:"}</span>
                <span className={"text-[var(--studio-ochre)]"}>{"48 convex colliders"}</span>
              </div>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Friction Coefficient:"}</span>
                <span>{"μ = 0.65 verified"}</span>
              </div>
            </div>
            <div className={"pt-2 border-t border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[10px] text-[var(--studio-sage)]"}>{"\n              ✓ READY FOR NVIDIA ISAAC SIM\n            "}</div>
          </div>
        </div>


        <div className={"p-8 lg:p-10 rounded-xl bg-[var(--studio-paper-raised)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_18%,transparent)] shadow-sm grid grid-cols-1 lg:grid-cols-12 gap-8 items-center"}>
          <div className={"lg:col-span-7"}>
            <div className={"inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[var(--studio-paper-sunken)] text-[var(--studio-ink)] font-mono-tech text-xs font-bold mb-4"}>{"\n              DOMAIN 03 // ACADEMIA & BENCHMARKING\n            "}</div>
            <h3 className={"text-2xl font-bold text-[var(--studio-ink)] mb-3"}>{"RESEARCH"}</h3>
            <p className={"text-base text-[var(--studio-ink-muted)] leading-relaxed mb-6"}>{"\n              Create reproducible 3D environments for experiments and evaluation. Package complex real-world edge cases with immutable checksums and metadata so research teams can share standardized benchmarks without variance.\n            "}</p>
            <div className={"grid grid-cols-2 gap-4 text-xs font-mono-tech"}>
              <div className={"p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                <span className={"text-[var(--studio-ink-muted)] block"}>{"Open Formats"}</span>
                <span className={"text-[var(--studio-ink)] font-semibold"}>{"USD, glTF 2.0, OBJ + MTL"}</span>
              </div>
              <div className={"p-3 rounded bg-[var(--studio-paper)] border border-[color-mix(in_srgb,var(--studio-ink-muted)_12%,transparent)]"}>
                <span className={"text-[var(--studio-ink-muted)] block"}>{"Provenance Audit"}</span>
                <span className={"text-[var(--studio-ink)] font-semibold"}>{"Deterministic Seed & Timestamp"}</span>
              </div>
            </div>
          </div>
          <div className={"lg:col-span-5 bg-[var(--studio-viewport)] rounded-lg p-5 border border-[var(--studio-ink)] font-mono-tech text-xs text-[var(--studio-paper)]/80 flex flex-col justify-between h-56"}>
            <div className={"flex items-center justify-between border-b border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] pb-2 text-[11px]"}>
              <span className={"text-[var(--studio-ember)]"}>{"BENCHMARK::EDGE_CASE_NIGHT_RAIN"}</span>
              <span className={"text-[var(--studio-sage)]"}>{"IMMUTABLE"}</span>
            </div>
            <div className={"space-y-2 text-[11px]"}>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Manifest Hash:"}</span>
                <span className={"font-mono-tech text-[10px]"}>{"sha256:7f8a9...b4c2"}</span>
              </div>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Camera Rigs:"}</span>
                <span className={"text-[var(--studio-geometry)]"}>{"8 synchronized streams"}</span>
              </div>
              <div className={"flex justify-between"}>
                <span className={"text-[var(--studio-ink-muted)]"}>{"Ground Truth:"}</span>
                <span>{"Sub-cm RTK-GNSS"}</span>
              </div>
            </div>
            <div className={"pt-2 border-t border-[color-mix(in_srgb,var(--studio-paper)_10%,transparent)] text-[10px] text-[var(--studio-sage)]"}>{"\n              ✓ READY FOR OPEN CITATION RELEASE\n            "}</div>
          </div>
        </div>

      </div>

    </div>
  </section>




  <section className={"py-24 bg-[var(--studio-viewport)] text-[var(--studio-paper-raised)] relative overflow-hidden"}>

    <div className={"absolute inset-0 bg-grid-dark opacity-40 pointer-events-none"}></div>

    <div className={"max-w-5xl mx-auto px-6 relative z-10 text-center"}>
      <div className={"inline-flex items-center gap-2 px-3 py-1 rounded bg-[var(--studio-ink)] border border-[color-mix(in_srgb,var(--studio-paper)_15%,transparent)] text-xs font-mono-tech text-[var(--studio-ember)] mb-8"}>
        <span className={"w-1.5 h-1.5 rounded-full bg-[var(--studio-ember)] animate-ping"}></span>
        <span>{"REAL2SIM STUDIO"}</span>
      </div>

      <h2 className={"text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-[var(--studio-paper-raised)] mb-6"}>{"\n        Build simulation scenes from reality.\n      "}</h2>

      <p className={"text-xl sm:text-2xl font-mono-tech text-[var(--studio-ember)] mb-10 tracking-wide"}>{"\n        Reconstruct. Inspect. Validate.\n      "}</p>

      <div className={"flex flex-wrap items-center justify-center gap-5"}>
        <Link href={STUDIO_ENTRY} className={"px-8 py-4 text-base font-semibold text-on-accent rounded-md bg-[var(--studio-ember-strong)] hover:bg-[var(--studio-ember)] transition-all shadow-md active:translate-y-px"}>{"\n          Open Real2Sim Studio\n        "}</Link>
        <a href={"#documentation"} className={"px-8 py-4 text-base font-semibold text-[var(--studio-paper-raised)] rounded-md bg-[var(--studio-ink)] hover:bg-[var(--studio-viewport-raised)] border border-[color-mix(in_srgb,var(--studio-paper)_15%,transparent)] transition-all"}>{"\n          View Documentation\n        "}</a>
      </div>


      <div className={"mt-12 text-xs font-mono-tech text-[var(--studio-ink-muted)] flex flex-wrap justify-center items-center gap-6"}>
        <span>{"No CC Required"}</span>
        <span>{"•"}</span>
        <span>{"Local ROS2 Ingestion"}</span>
        <span>{"•"}</span>
        <span>{"USD & URDF Direct Export"}</span>
        <span>{"•"}</span>
        <span>{"Zero Algorithmic Hallucination"}</span>
      </div>
    </div>
  </section>




  <footer id={"documentation"} className={"py-16 bg-[var(--studio-paper)] border-t border-[color-mix(in_srgb,var(--studio-ink-muted)_20%,transparent)]"}>
    <div className={"max-w-7xl mx-auto px-6"}>
      <div className={"flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pb-12 border-b border-[color-mix(in_srgb,var(--studio-ink-muted)_16%,transparent)]"}>


        <div>
          <div className={"flex items-center gap-3 mb-2"}>
            <div className={"w-6 h-6 rounded bg-[var(--studio-viewport)] flex items-center justify-center p-1"}>
              <svg viewBox={"0 0 24 24"} fill={"none"} className={"w-full h-full"} aria-hidden={"true"}>
                <path d={"M12 2L3 7L12 12L21 7L12 2Z"} stroke={"var(--studio-ember)"} strokeWidth={"2"} />
                <path d={"M3 17L12 22L21 17"} stroke={"var(--studio-geometry)"} strokeWidth={"1.8"} />
              </svg>
            </div>
            <span className={"font-bold text-[var(--studio-ink)] text-base tracking-tight"}>{"Real2Sim Studio"}</span>
          </div>
          <p className={"text-xs text-[var(--studio-ink-muted)] max-w-sm"}>{"\n            Reconstructing real-world road and warehouse environments into editable, simulation-ready 3D scenes.\n          "}</p>
        </div>


        <div className={"flex flex-wrap items-center gap-8 text-sm font-medium text-[var(--studio-ink-muted)]"}>
          <a href={"#product"} className={"hover:text-[var(--studio-ink)] transition-colors"}>{"Product"}</a>
          <a href={"#workflow"} className={"hover:text-[var(--studio-ink)] transition-colors"}>{"Workflow"}</a>
          <a href={"#technology"} className={"hover:text-[var(--studio-ink)] transition-colors"}>{"Technology"}</a>
          <a href={"#evaluation"} className={"hover:text-[var(--studio-ink)] transition-colors"}>{"Evaluation"}</a>
          <a href={"#documentation"} className={"hover:text-[var(--studio-ink)] transition-colors"}>{"Documentation"}</a>
          <a href={"https://github.com/AI20K-Build-Phase-Cohort-4/P-087"} target={"_blank"} rel={"noreferrer"} className={"hover:text-[var(--studio-ink)] transition-colors flex items-center gap-1.5 font-mono-tech text-xs"}>{"\n            GitHub\n            "}<svg className={"w-3.5 h-3.5"} fill={"none"} viewBox={"0 0 24 24"} stroke={"currentColor"} aria-hidden={"true"}>
              <path strokeLinecap={"round"} strokeLinejoin={"round"} strokeWidth={"2"} d={"M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"} />
            </svg>
          </a>
        </div>

      </div>


      <div className={"pt-8 flex flex-col sm:flex-row items-center justify-between text-xs font-mono-tech text-[var(--studio-ink-muted)] gap-4"}>
        <div>{"\n          © 2025 Real2Sim Studio. All rights reserved. Engineering Grade Spatial Systems.\n        "}</div>
        <div className={"flex items-center gap-6"}>
          <span className={"text-[var(--studio-sage)]"}>{"● ILLUSTRATIVE PREVIEW"}</span>
          <span aria-disabled="true" title="Not included in this design preview">{"Privacy Policy"}</span>
          <span aria-disabled="true" title="Not included in this design preview">{"Security Whitepaper"}</span>
        </div>
      </div>
    </div>
  </footer>


    </main>
  );
}
