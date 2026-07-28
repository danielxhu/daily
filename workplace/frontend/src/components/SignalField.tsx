"use client";

import { useEffect, useRef } from "react";

import { useT } from "@/lib/i18n";

/** Today's items as a field of light: one point per item, x = when it was
 * published, y banded by source. It is the masthead's visual moment and a
 * reading of the data at once — it says how much arrived, when, and from how
 * many sources, and deliberately says nothing about importance.
 *
 * Hand-written WebGL, no dependency. Paused when off-screen or on a hidden tab,
 * static under `prefers-reduced-motion`, and simply absent where WebGL is not
 * available — the page never depends on it. */

const VERT = `
attribute vec2 a_pos;
attribute float a_seed;
uniform float u_time;
uniform vec2 u_pointer;
uniform float u_motion;
uniform float u_dpr;
varying float v_alpha;
void main() {
  vec2 p = a_pos;
  p.y += sin(u_time * 0.55 + a_seed * 6.283) * 0.02 * u_motion;
  p.x += cos(u_time * 0.31 + a_seed * 12.566) * 0.004 * u_motion;
  vec2 d = p - u_pointer;
  float near = smoothstep(0.20, 0.0, length(d * vec2(1.0, 0.42)));
  if (u_pointer.x > -0.5) p += normalize(d + vec2(0.0001)) * near * 0.06;
  vec2 clip = vec2(p.x * 2.0 - 1.0, 1.0 - p.y * 2.0);
  gl_Position = vec4(clip, 0.0, 1.0);
  gl_PointSize = mix(7.0, 20.0, a_seed) * u_dpr * (1.0 + near * 0.9);
  v_alpha = mix(0.45, 1.0, a_seed);
}`;

const FRAG = `
precision mediump float;
uniform vec3 u_color;
varying float v_alpha;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  float a = pow(smoothstep(1.0, 0.0, d), 2.4);
  gl_FragColor = vec4(u_color, a * v_alpha);
}`;

export interface SignalPoint {
  /** epoch ms of the item's publish (or discovery) time */
  at: number;
  /** stable per-source key, so one source forms one band */
  source: string;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10000) / 10000;
}

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader | null {
  const sh = gl.createShader(type);
  if (!sh) return null;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  return gl.getShaderParameter(sh, gl.COMPILE_STATUS) ? sh : null;
}

function cssColor(name: string): [number, number, number] {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const parts = raw.split(/[\s,]+/).map(Number);
  return parts.length >= 3 && parts.every((n) => !Number.isNaN(n))
    ? [parts[0] / 255, parts[1] / 255, parts[2] / 255]
    : [0.5, 0.5, 0.5];
}

export function SignalField({ points }: { points: SignalPoint[] }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const t = useT();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;
    const ctx = canvas.getContext("webgl", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
    });
    if (!ctx) return;
    const gl = ctx;

    const program = gl.createProgram();
    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    if (!program || !vs || !fs) return;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    gl.useProgram(program);

    // One column per DAY present, evenly spaced. Raw time would crush the field
    // into one edge whenever the window is lopsided (a month of history plus a
    // busy today); day columns keep it readable AND say which days were busy.
    const dayOf = (ms: number) => new Date(ms).toISOString().slice(0, 10);
    const days = [...new Set(points.map((p) => dayOf(p.at)))].sort();
    const col = new Map(days.map((d, i) => [d, (i + 0.5) / days.length]));
    const data = new Float32Array(points.length * 3);
    points.forEach((p, i) => {
      const jx = (hash(`x${p.source}${i}`) - 0.5) * (0.78 / days.length);
      const band = hash(p.source);
      data[i * 3] = Math.min(0.98, Math.max(0.02, (col.get(dayOf(p.at)) ?? 0.5) + jx));
      data[i * 3 + 1] = 0.14 + band * 0.72 + (hash(`y${p.source}${i}`) - 0.5) * 0.12;
      data[i * 3 + 2] = hash(`${p.at}${p.source}`);
    });
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const stride = 3 * 4;
    const aPos = gl.getAttribLocation(program, "a_pos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, stride, 0);
    const aSeed = gl.getAttribLocation(program, "a_seed");
    gl.enableVertexAttribArray(aSeed);
    gl.vertexAttribPointer(aSeed, 1, gl.FLOAT, false, stride, 2 * 4);

    const uTime = gl.getUniformLocation(program, "u_time");
    const uPointer = gl.getUniformLocation(program, "u_pointer");
    const uColor = gl.getUniformLocation(program, "u_color");
    const uMotion = gl.getUniformLocation(program, "u_motion");
    const uDpr = gl.getUniformLocation(program, "u_dpr");

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    gl.enable(gl.BLEND);
    const pointer = { x: -1, y: -1 };
    let dpr = 1;

    function theme(): void {
      const dark = document.documentElement.dataset.theme === "dark";
      // dark: additive light. light: ink laid over paper.
      gl.blendFunc(gl.SRC_ALPHA, dark ? gl.ONE : gl.ONE_MINUS_SRC_ALPHA);
      gl.uniform3fv(uColor, cssColor(dark ? "--accent" : "--ink"));
    }

    function resize(): void {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas!.clientWidth;
      const h = canvas!.clientHeight;
      canvas!.width = Math.max(1, Math.round(w * dpr));
      canvas!.height = Math.max(1, Math.round(h * dpr));
      gl.viewport(0, 0, canvas!.width, canvas!.height);
      gl.uniform1f(uDpr, dpr);
    }

    function frame(ms: number): void {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(uTime, reduced ? 0 : ms / 1000);
      gl.uniform1f(uMotion, reduced ? 0 : 1);
      gl.uniform2f(uPointer, pointer.x, pointer.y);
      gl.drawArrays(gl.POINTS, 0, points.length);
    }

    let raf = 0;
    let running = false;
    function loop(ms: number): void {
      frame(ms);
      raf = requestAnimationFrame(loop);
    }
    function start(): void {
      if (running || reduced) return;
      running = true;
      raf = requestAnimationFrame(loop);
    }
    function stop(): void {
      running = false;
      cancelAnimationFrame(raf);
    }

    resize();
    theme();
    frame(0);

    // rAF-throttled pointer, and only while the field is actually on screen
    let queued = false;
    function onMove(e: PointerEvent): void {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        const r = canvas!.getBoundingClientRect();
        pointer.x = (e.clientX - r.left) / r.width;
        pointer.y = (e.clientY - r.top) / r.height;
        queued = false;
        if (reduced) frame(0);
      });
    }
    function onLeave(): void {
      pointer.x = -1;
      pointer.y = -1;
      if (reduced) frame(0);
    }
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", onLeave);

    const io = new IntersectionObserver(([entry]) => (entry.isIntersecting ? start() : stop()), {
      threshold: 0,
    });
    io.observe(canvas);
    const onVisibility = (): void => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);
    const ro = new ResizeObserver(() => {
      resize();
      frame(0);
    });
    ro.observe(canvas);
    const themeObserver = new MutationObserver(() => {
      theme();
      frame(0);
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      stop();
      io.disconnect();
      ro.disconnect();
      themeObserver.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
      gl.deleteBuffer(buf);
      gl.deleteProgram(program);
    };
  }, [points]);

  if (points.length === 0) return null;
  return (
    <figure className="mb-7 mt-1">
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="block h-[108px] w-full sm:h-[152px]"
      />
      <figcaption className="mono mt-1.5 text-[10px] uppercase tracking-[0.14em] text-faint">
        {t("today.field.caption", { count: points.length })}
      </figcaption>
    </figure>
  );
}
