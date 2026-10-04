"use client";

import { Mesh, Program, Renderer, Triangle } from "ogl";
import { useEffect, useRef } from "react";

import type { Theme } from "@/lib/prefs";

/** The slow light field behind the app. Derived from react-bits' Plasma
 * (github.com/DavidHDev/react-bits, MIT) — the raymarch stays as published; the
 * mouse-follow and direction variants are dropped. Renders at 55% resolution,
 * pauses when offscreen or on a hidden tab, and paints a single still frame
 * under prefers-reduced-motion. */

const TINT: Record<Theme, { color: [number, number, number]; opacity: number }> = {
  // the interaction accent, per theme, at the strength measured to keep body
  // contrast within 5% of the on-surface baseline once the sheet is over it
  light: { color: [45 / 255, 74 / 255, 194 / 255], opacity: 0.24 },
  dark: { color: [141 / 255, 165 / 255, 255 / 255], opacity: 0.42 },
};

const RENDER_SCALE = 0.55;
const MAX_DPR = 1.5;
const TARGET_FPS = 60;
const ITERATIONS = 60;

const vertex = `#version 300 es
precision highp float;
in vec2 position;
in vec2 uv;
out vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const fragment = `#version 300 es
precision highp float;
uniform vec2 iResolution;
uniform float iTime;
uniform vec3 uCustomColor;
uniform float uSpeed;
uniform float uScale;
uniform float uOpacity;
uniform float uQuality;
uniform float uStepScale;
out vec4 fragColor;

void mainImage(out vec4 o, vec2 C) {
  vec2 center = iResolution.xy * 0.5;
  C = (C - center) / uScale + center;

  float i, d, z, T = iTime * uSpeed;
  vec3 O, p, S;

  for (vec2 r = iResolution.xy, Q; ++i < 60.0; O += o.w/d*o.xyz) {
    p = z*normalize(vec3(C-.5*r,r.y));
    p.z -= 4.;
    S = p;
    d = p.y-T;

    p.x += .4*(1.+p.y)*sin(d + p.x*0.1)*cos(.34*d + p.x*0.05);
    Q = p.xz *= mat2(cos(p.y+vec4(0,11,33,0)-T));
    z += d = (abs(sqrt(length(Q*Q)) - .25*(5.+S.y))/3.+8e-4) * uStepScale;
    o = 1.+sin(S.y+p.z*.5+S.z-length(S-p)+vec4(2,1,0,8));
    if (i >= uQuality) break;
  }

  o.xyz = tanh(O/1e4);
}

bool finite1(float x){ return !(isnan(x) || isinf(x)); }
vec3 sanitize(vec3 c){
  return vec3(
    finite1(c.r) ? c.r : 0.0,
    finite1(c.g) ? c.g : 0.0,
    finite1(c.b) ? c.b : 0.0
  );
}

void main() {
  vec4 o = vec4(0.0);
  mainImage(o, gl_FragCoord.xy);
  vec3 rgb = sanitize(o.rgb);
  float intensity = (rgb.r + rgb.g + rgb.b) / 3.0;
  fragColor = vec4(intensity * uCustomColor, length(rgb) * uOpacity);
}
`;

export function PlasmaField({ theme }: { theme: Theme }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    // jsdom and WebGL-less browsers: no field, no error
    const probe = document.createElement("canvas");
    if (typeof probe.getContext !== "function" || !probe.getContext("webgl2")) return;

    const stillOnly =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let renderer: Renderer;
    try {
      renderer = new Renderer({
        webgl: 2,
        alpha: true,
        antialias: false,
        dpr: Math.min(window.devicePixelRatio || 1, MAX_DPR),
      });
    } catch {
      return;
    }
    const gl = renderer.gl;
    const canvas = gl.canvas as HTMLCanvasElement;
    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    container.appendChild(canvas);

    const tint = TINT[theme];
    const program = new Program(gl, {
      vertex,
      fragment,
      uniforms: {
        iTime: { value: 0 },
        iResolution: { value: new Float32Array([1, 1]) },
        uCustomColor: { value: new Float32Array(tint.color) },
        uSpeed: { value: 0.24 },
        uScale: { value: 1.3 },
        uOpacity: { value: tint.opacity },
        uQuality: { value: ITERATIONS },
        uStepScale: { value: 1 },
      },
    });
    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

    let resizePending = false;
    const setSize = () => {
      const rect = container.getBoundingClientRect();
      renderer.setSize(
        Math.max(1, Math.floor(rect.width * RENDER_SCALE)),
        Math.max(1, Math.floor(rect.height * RENDER_SCALE)),
      );
      // setSize also writes the scaled-down buffer size to the CSS box — put it
      // back to 100% so the small buffer stretches over the viewport
      canvas.style.width = "100%";
      canvas.style.height = "100%";
      const res = program.uniforms.iResolution.value as Float32Array;
      res[0] = gl.drawingBufferWidth;
      res[1] = gl.drawingBufferHeight;
    };
    const ro = new ResizeObserver(() => {
      if (resizePending) return;
      resizePending = true;
      requestAnimationFrame(() => {
        resizePending = false;
        setSize();
      });
    });
    ro.observe(container);
    setSize();

    let raf = 0;
    let contextLost = false;
    let onScreen = true;
    let tabVisible = document.visibilityState !== "hidden";
    const t0 = performance.now();
    const frameInterval = 1000 / TARGET_FPS;
    let lastFrame = 0;

    const loop = (t: number) => {
      if (contextLost || !onScreen || !tabVisible) return;
      if (t - lastFrame < frameInterval) {
        raf = requestAnimationFrame(loop);
        return;
      }
      lastFrame = t;
      program.uniforms.iTime.value = (t - t0) * 0.001;
      renderer.render({ scene: mesh });
      raf = requestAnimationFrame(loop);
    };
    const restart = () => {
      if (contextLost || !onScreen || !tabVisible || stillOnly) return;
      cancelAnimationFrame(raf);
      lastFrame = 0;
      raf = requestAnimationFrame(loop);
    };

    const onContextLost = (e: Event) => {
      e.preventDefault();
      contextLost = true;
      cancelAnimationFrame(raf);
    };
    const onContextRestored = () => {
      contextLost = false;
      restart();
    };
    canvas.addEventListener("webglcontextlost", onContextLost);
    canvas.addEventListener("webglcontextrestored", onContextRestored);

    const io = new IntersectionObserver(
      ([entry]) => {
        onScreen = entry.isIntersecting;
        onScreen ? restart() : cancelAnimationFrame(raf);
      },
      { threshold: 0 },
    );
    io.observe(container);

    const onVisibility = () => {
      tabVisible = document.visibilityState !== "hidden";
      tabVisible ? restart() : cancelAnimationFrame(raf);
    };
    document.addEventListener("visibilitychange", onVisibility);

    if (stillOnly) renderer.render({ scene: mesh });
    else raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.removeEventListener("webglcontextlost", onContextLost);
      canvas.removeEventListener("webglcontextrestored", onContextRestored);
      canvas.remove();
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [theme]);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
    />
  );
}
