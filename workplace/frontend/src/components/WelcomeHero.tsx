"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useLocale, useT } from "@/lib/i18n";

/** The welcome page (/welcome): one continuous scroll through three movements —
 * what daily is, how it works, and where its honest boundaries lie. First visit
 * lands here; the header Guide entry returns here. Rendered bare (AppFrame drops
 * the app chrome for this route) so the composition owns the whole viewport.
 *
 * Motion: Lenis drives the page scroll (lerp), GSAP ScrollTrigger reads it. The
 * guide section pins while its three steps swap; boundary rows stagger in once.
 * Everything is visible without JS or under prefers-reduced-motion — the
 * animations only ever start FROM a hidden state at their trigger moment. */

const ONBOARD_KEY = "daily.onboarded";

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Slow contour lines behind all three sections — one continuous field, so the
 * sections read as movements of a single page rather than three pages. Plain 2D
 * canvas; drifts with time and scroll, follows the theme's tokens. */
function drawContours(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  time: number,
  scroll: number,
  rgb: string,
): void {
  ctx.clearRect(0, 0, w, h);
  ctx.lineWidth = 0.7;
  const lines = 16;
  for (let l = 0; l < lines; l += 1) {
    const ph = l / lines;
    ctx.beginPath();
    for (let x = 0; x <= w; x += 10) {
      const u = x / 640;
      const y =
        ph * h * 1.15 -
        scroll * 0.25 +
        Math.sin(u * 1.6 + ph * 6 + time * 0.05) * 46 +
        Math.sin(u * 3.1 + ph * 11 - time * 0.03) * 18;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    const a = 0.04 + 0.05 * Math.sin(ph * Math.PI);
    ctx.strokeStyle = `rgba(${rgb}, ${a.toFixed(3)})`;
    ctx.stroke();
  }
}

export function WelcomeHero() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const heroRef = useRef<HTMLDivElement | null>(null);
  const guideRef = useRef<HTMLElement | null>(null);
  const limitsRef = useRef<HTMLElement | null>(null);
  const [step, setStep] = useState(0);

  function enter(): void {
    try {
      window.localStorage.setItem(ONBOARD_KEY, "1");
    } catch {
      // storage unavailable — entering still works, the gate just repeats
    }
    router.push("/");
  }

  // background contours: theme-aware, time + scroll driven, one draw when
  // motion is reduced
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduced = reducedMotion();
    let rgb = "141 165 255";
    let raf = 0;

    function readTheme(): void {
      const dark = document.documentElement.dataset.theme === "dark";
      const raw = getComputedStyle(document.documentElement)
        .getPropertyValue(dark ? "--accent" : "--ink")
        .trim();
      rgb = raw.split(/\s+/).slice(0, 3).join(", ");
    }
    function resize(): void {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas!.width = Math.round(canvas!.clientWidth * dpr);
      canvas!.height = Math.round(canvas!.clientHeight * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    function frame(ms: number): void {
      drawContours(
        ctx!,
        canvas!.clientWidth,
        canvas!.clientHeight,
        reduced ? 0 : ms / 1000,
        window.scrollY,
        rgb,
      );
      if (!reduced) raf = requestAnimationFrame(frame);
    }

    readTheme();
    resize();
    raf = requestAnimationFrame(frame);
    const ro = new ResizeObserver(() => {
      resize();
      if (reduced) frame(0);
    });
    ro.observe(canvas);
    const mo = new MutationObserver(() => {
      readTheme();
      if (reduced) frame(0);
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mo.disconnect();
    };
  }, []);

  // scroll choreography: Lenis smooths the page scroll, ScrollTrigger reads it
  useEffect(() => {
    const reduced = reducedMotion();
    let cleanup: (() => void) | undefined;
    let cancelled = false;

    void (async () => {
      const [{ default: gsap }, { ScrollTrigger }, { default: Lenis }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
        import("lenis"),
      ]);
      if (cancelled) return;
      gsap.registerPlugin(ScrollTrigger);

      let lenis: InstanceType<typeof Lenis> | null = null;
      let tick: ((time: number) => void) | undefined;
      if (!reduced) {
        lenis = new Lenis({ lerp: 0.11 });
        lenis.on("scroll", ScrollTrigger.update);
        tick = (time: number) => lenis!.raf(time * 1000);
        gsap.ticker.add(tick);
        gsap.ticker.lagSmoothing(0);
      }

      // hero entrance — a `from` tween: markup is visible by default, the
      // animation only introduces it
      const intro = reduced
        ? null
        : gsap.from(heroRef.current!.children, {
            autoAlpha: 0,
            y: 28,
            duration: 0.9,
            ease: "power3.out",
            stagger: 0.11,
            delay: 0.15,
          });

      // guide: the section is tall; the inner stage is CSS-sticky. Scroll
      // progress picks the active step (stepped state + CSS transitions, so a
      // missed frame can never strand a half-state).
      const guideTrigger = ScrollTrigger.create({
        trigger: guideRef.current!,
        start: "top top",
        end: "bottom bottom",
        onUpdate: (self) => setStep(self.progress < 1 / 3 ? 0 : self.progress < 2 / 3 ? 1 : 2),
      });

      // boundaries: rows rise once as they enter; visible-by-default markup
      const rows = Array.from(limitsRef.current!.querySelectorAll<HTMLElement>("[data-lim]"));
      const rowTriggers = reduced
        ? []
        : rows.map((row, i) =>
            ScrollTrigger.create({
              trigger: row,
              start: "top 92%",
              once: true,
              onEnter: () =>
                gsap.from(row, {
                  autoAlpha: 0,
                  y: 26,
                  duration: 0.7,
                  ease: "power3.out",
                  delay: (i % 4) * 0.06,
                }),
            }),
          );

      cleanup = () => {
        intro?.kill();
        guideTrigger.kill();
        rowTriggers.forEach((tr) => tr.kill());
        if (tick) gsap.ticker.remove(tick);
        lenis?.destroy();
      };
    })();

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, []);

  function scrollToGuide(): void {
    guideRef.current?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" });
  }

  const steps = [
    { title: t("hero.s2.s1.title"), body: t("hero.s2.s1.body") },
    { title: t("hero.s2.s2.title"), body: t("hero.s2.s2.body") },
    { title: t("hero.s2.s3.title"), body: t("hero.s2.s3.body") },
  ] as const;

  const limits = [
    { title: t("hero.s3.l1.title"), body: t("hero.s3.l1.body") },
    { title: t("hero.s3.l2.title"), body: t("hero.s3.l2.body") },
    { title: t("hero.s3.l3.title"), body: t("hero.s3.l3.body") },
    { title: t("hero.s3.l4.title"), body: t("hero.s3.l4.body") },
  ] as const;

  return (
    <div className="relative">
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 h-full w-full"
      />
      <div className="relative mx-auto max-w-5xl px-6 sm:px-10">
          {/* ---- movement 1 · what daily is ---- */}
          <section className="flex min-h-[100svh] flex-col">
            <div className="flex h-20 items-center justify-between">
              <span className="serif text-2xl font-semibold text-ink">daily</span>
              <span className="flex items-center gap-5 text-sm text-faint">
                <button
                  type="button"
                  onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
                  aria-label={t("lang.aria")}
                  className="mono text-xs tracking-wide transition-colors hover:text-ink"
                >
                  <b className={locale === "en" ? "text-ink" : ""}>EN</b>
                  {" / "}
                  <b className={locale === "zh" ? "text-ink" : ""}>中</b>
                </button>
                <a
                  href="https://github.com/danielxhu/daily"
                  target="_blank"
                  rel="noreferrer"
                  className="transition-colors hover:text-ink"
                >
                  {t("hero.github")}
                </a>
                <button
                  type="button"
                  onClick={enter}
                  className="text-muted transition-colors hover:text-ink"
                >
                  {t("hero.cta")} →
                </button>
              </span>
            </div>
            <div ref={heroRef} className="flex max-w-3xl flex-1 flex-col justify-center">
              <p className="mono text-xs tracking-[0.22em] text-accent">{t("hero.kicker")}</p>
              <h1 className="serif mt-6 text-[clamp(2.6rem,7vw,4.6rem)] font-semibold leading-[1.12] tracking-[-0.015em] text-ink">
                {t("hero.h1a")}
                <br />
                {t("hero.h1b.pre")}
                <span className="text-accent">{t("hero.h1b.accent")}</span>
                {t("hero.h1b.post")}
              </h1>
              <p className="mt-6 max-w-xl text-[17px] leading-[1.75] text-muted">{t("hero.sub")}</p>
              <div className="mt-10 flex items-center gap-4">
                <button type="button" onClick={enter} className="btn-primary px-7 py-3.5 text-[15px]">
                  {t("hero.cta")}
                </button>
                <button
                  type="button"
                  onClick={scrollToGuide}
                  className="px-2 py-3 text-sm text-muted transition-colors hover:text-ink"
                >
                  {t("hero.how")}
                </button>
              </div>
            </div>
            <div className="mono flex h-20 items-center gap-3 text-[11px] tracking-[0.18em] text-faint">
              <span
                aria-hidden="true"
                className="h-9 w-px animate-pulse bg-gradient-to-b from-accent to-transparent motion-reduce:animate-none"
              />
              {t("hero.scroll")}
            </div>
          </section>

          {/* ---- movement 2 · the guide (pinned; steps swap with scroll) ---- */}
          <section ref={guideRef} aria-label={t("hero.s2.kicker")} className="md:h-[260vh]">
            <div className="py-16 md:sticky md:top-0 md:flex md:h-screen md:flex-col md:justify-center md:py-0">
              <p className="mono text-xs tracking-[0.22em] text-faint">{t("hero.s2.kicker")}</p>
              <h2 className="serif mt-4 max-w-md text-[clamp(1.9rem,4vw,2.6rem)] font-semibold leading-[1.2] text-ink">
                {t("hero.s2.title")}
              </h2>
              {/* the one prerequisite: nothing summarizes until a model key exists */}
              <p className="mt-5 max-w-xl rounded-lg border border-line bg-panel px-4 py-3 text-[13.5px] leading-[1.7] text-muted">
                <span className="font-semibold text-ink">{t("hero.s2.key.label")}</span>{" "}
                {t("hero.s2.key.body")}
              </p>
              <div className="mt-8 gap-16 md:grid md:grid-cols-[minmax(0,380px)_1fr]">
                <ol className="m-0 list-none p-0">
                  {steps.map((item, i) => (
                    <li
                      key={item.title}
                      className={`border-t border-line py-5 transition-colors duration-500 ${
                        step === i ? "text-ink" : "text-faint"
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => setStep(i)}
                        className="flex w-full gap-4 text-left"
                      >
                        <span
                          className={`mono pt-1 text-xs ${step === i ? "text-accent" : ""}`}
                        >
                          0{i + 1}
                        </span>
                        <span>
                          <span className="block text-[16px] font-semibold">{item.title}</span>
                          <span
                            className={`mt-1.5 block max-w-xs text-[13.5px] leading-[1.7] ${
                              step === i ? "text-muted" : ""
                            }`}
                          >
                            {item.body}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
                <div className="relative mt-10 min-h-[300px] md:mt-0">
                  {/* three stage shots, crossfaded by the active step */}
                  <GuideShot active={step === 0}>
                    <p className="mono text-[11px] tracking-wide text-faint">
                      {t("hero.shot1.label")}
                    </p>
                    <p className="mt-2 truncate rounded-md border border-line bg-panel px-3 py-2.5 text-sm text-ink">
                      {t("hero.shot1.value")}
                    </p>
                    <p className="mt-3 inline-block rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface">
                      {t("hero.shot1.button")}
                    </p>
                    <p className="mt-3 text-xs leading-relaxed text-faint">{t("hero.shot1.hint")}</p>
                  </GuideShot>
                  <GuideShot active={step === 1}>
                    <p className="flex items-center gap-2.5 text-[11px] text-faint">
                      <span className="font-medium text-muted">{t("hero.shot2.source")}</span>
                      <span className="rounded border border-line px-1.5 py-px text-[10px]">T2</span>
                      <span>16:00</span>
                    </p>
                    <p className="serif mt-2.5 text-[22px] font-semibold leading-[1.3] text-ink">
                      {t("hero.shot2.title")}
                    </p>
                    <p className="mt-3 text-[13px] leading-[1.75] text-muted">
                      <span className="badge mr-1.5 bg-panel text-faint">{t("digest.ai.label")}</span>
                      {t("hero.shot2.ai")}
                    </p>
                    <p className="mt-3.5 flex gap-2 text-[11px] text-faint">
                      <span className="rounded bg-panel px-2 py-0.5">{t("hero.shot2.tag1")}</span>
                      <span className="rounded bg-panel px-2 py-0.5">{t("hero.shot2.tag2")}</span>
                      <span className="text-accent">{t("hero.shot2.original")}</span>
                    </p>
                  </GuideShot>
                  <GuideShot active={step === 2}>
                    <p className="ml-auto w-fit max-w-[85%] rounded-lg bg-accent-soft px-3.5 py-2 text-sm text-ink">
                      {t("hero.shot3.q")}
                    </p>
                    <p className="mt-3 max-w-[92%] rounded-lg border border-line bg-panel px-3.5 py-2.5 text-[13px] leading-[1.7] text-muted">
                      {t("hero.shot3.a")}
                    </p>
                    <p className="mt-2.5 text-[11px] text-accent">{t("hero.shot3.cite")}</p>
                  </GuideShot>
                </div>
              </div>
            </div>
          </section>

          {/* ---- movement 3 · honest boundaries ---- */}
          {/* the boundaries are a compact footnote to the guide, not a third act:
              they must be read, but they should not outweigh what daily does */}
          <section ref={limitsRef} aria-label={t("hero.s3.kicker")} className="py-14 md:py-20">
            <p className="mono text-xs tracking-[0.22em] text-faint">{t("hero.s3.kicker")}</p>
            <h2 className="serif mt-3 max-w-2xl text-[clamp(1.4rem,2.6vw,1.75rem)] font-semibold leading-[1.25] text-ink">
              {t("hero.s3.title")}
            </h2>
            <p className="mt-3 max-w-xl text-[13.5px] leading-[1.7] text-muted">
              {t("hero.s3.lead")}
            </p>
            <ul className="m-0 mt-8 list-none p-0">
              {limits.map((item, i) => (
                <li
                  key={item.title}
                  data-lim
                  className="grid items-baseline gap-x-5 gap-y-0.5 border-t border-line py-3.5 md:grid-cols-[40px_240px_1fr]"
                >
                  <span className="mono text-[11px] text-accent">0{i + 1}</span>
                  <span className="text-[14px] font-semibold text-ink">{item.title}</span>
                  <span className="text-[13px] leading-[1.7] text-muted">{item.body}</span>
                </li>
              ))}
            </ul>
            <div className="mt-14 text-center">
              <p className="serif text-[clamp(1.25rem,2.4vw,1.6rem)] font-semibold text-ink">
                {t("hero.final")}
              </p>
              <button
                type="button"
                onClick={enter}
                className="btn-primary mt-6 px-7 py-3.5 text-[15px]"
              >
                {t("hero.cta")}
              </button>
            </div>
            <div className="mono mt-14 flex flex-wrap justify-between gap-2 border-t border-line pt-5 text-[11px] tracking-[0.14em] text-faint">
              <span>{t("hero.foot.left")}</span>
              <span>{t("hero.foot.right")}</span>
            </div>
        </section>
      </div>
    </div>
  );
}

/** One stage panel; the active one is present, the others sit faded + shifted
 * beneath it (CSS transitions carry the crossfade, so state can never strand
 * an invisible panel). */
function GuideShot({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <div
      aria-hidden={!active}
      className={`transition-all duration-500 md:absolute md:inset-x-0 md:top-1/2 md:mx-auto md:max-w-[520px] md:-translate-y-1/2 ${
        active
          ? "relative opacity-100 md:translate-y-[-50%]"
          : "absolute inset-x-0 top-0 opacity-0 md:translate-y-[-44%] pointer-events-none"
      }`}
    >
      <div className="rounded-xl border border-line bg-card p-6 shadow-[var(--lift)]">{children}</div>
    </div>
  );
}
