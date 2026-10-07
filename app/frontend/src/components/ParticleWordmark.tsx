import { useEffect, useRef, useState } from "react";

/**
 * The header's wordmark, drawn as a field of particles that fly in and gather
 * into the letters — adapted from React Bits' Particle Text
 * (https://reactbits.dev/text-animations/particle-text, MIT + Commons Clause).
 *
 * What changed from the original, and why:
 *
 * - **It keeps the text's own layout.** The original is a 240px-tall block that
 *   centres its text in whatever box it is given; a wordmark has to take exactly
 *   the room the word takes. So the real `<span>` stays in the flow — it sizes
 *   the box, carries the font, and is what a screen reader and the tests read —
 *   and the canvas is laid over it with a bleed on every side, so particles have
 *   somewhere to arrive from without the header's row growing.
 * - **It samples at device resolution.** At 24px, the original's 4-CSS-pixel
 *   grid leaves a word nobody can read; one particle per device pixel pair keeps
 *   the letterforms.
 * - **One gradient, not a per-particle colour mix.** The particles are painted
 *   with the same flame gradient `.brand-text` uses, read from the CSS tokens, so
 *   the two can never drift apart.
 * - **It degrades to the plain wordmark.** Reduced motion, no canvas, no
 *   `ResizeObserver` (jsdom): the span simply keeps its `.brand-text` gradient
 *   and nothing is drawn. The span only goes transparent once the canvas has
 *   particles to show.
 * - **The loop stops when there is nothing to animate** — after the gather, with
 *   no pointer over it, the idle drift runs at a low frame rate rather than 60 fps
 *   forever in a header that is always on screen.
 */

const BLEED_X = 20;
const BLEED_Y = 14;
const SCATTER = 46;
const GATHER_MS = 1400;
const STAGGER_MS = 380;
const REPEL = 9;
const REPEL_RADIUS = 34;
const IDLE_DRIFT = 0.35;
const IDLE_FRAME_MS = 1000 / 24;

type Particle = {
  x: number;
  y: number;
  startX: number;
  startY: number;
  targetX: number;
  targetY: number;
  seed: number;
  depth: number;
  delay: number;
};

const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), max);
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

export default function ParticleWordmark({ text, className = "" }: { text: string; className?: string }) {
  const textRef = useRef<HTMLSpanElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const span = textRef.current;
    const canvas = canvasRef.current;
    if (!span || !canvas || typeof ResizeObserver === "undefined") return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motion.matches) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let particles: Particle[] = [];
    let frame: number | null = null;
    let build = 0;
    let gatherStart = 0;
    let gathering = false;
    let lastPaint = 0;
    let width = 0;
    let height = 0;
    let dot = 1;
    let fill: CanvasGradient | string = "#ff7854";
    const pointer = { active: false, x: 0, y: 0, sx: 0, sy: 0 };

    const scatterAll = () => {
      for (const p of particles) {
        const angle = p.seed * Math.PI * 2;
        const distance = SCATTER * (0.35 + p.depth * 0.75);
        p.x = p.targetX + Math.cos(angle) * distance;
        p.y = p.targetY + Math.sin(angle) * distance * 0.6;
        p.startX = p.x;
        p.startY = p.y;
      }
      gatherStart = performance.now();
      gathering = true;
    };

    const render = (now: number) => {
      frame = window.requestAnimationFrame(render);
      // Once the word has formed and nothing is touching it, the drift is the
      // only motion left — it does not need 60 frames a second.
      if (!gathering && !pointer.active && now - lastPaint < IDLE_FRAME_MS) return;
      lastPaint = now;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = fill;
      pointer.sx += (pointer.x - pointer.sx) * 0.18;
      pointer.sy += (pointer.y - pointer.sy) * 0.18;

      let complete = true;
      const t = now * 0.001;
      for (const p of particles) {
        let bx = p.targetX;
        let by = p.targetY;
        let progress = 1;
        if (gathering) {
          progress = clamp((now - gatherStart - p.delay) / GATHER_MS, 0, 1);
          const e = easeOutCubic(progress);
          bx = p.startX + (p.targetX - p.startX) * e;
          by = p.startY + (p.targetY - p.startY) * e;
          if (progress < 1) complete = false;
        } else {
          bx += Math.sin(t * 0.9 + p.seed * 10) * IDLE_DRIFT * p.depth;
          by += Math.cos(t * 0.75 + p.depth * 10) * IDLE_DRIFT * p.depth;
        }
        if (pointer.active) {
          const dx = bx - pointer.sx;
          const dy = by - pointer.sy;
          const d = Math.hypot(dx, dy);
          if (d > 0 && d < REPEL_RADIUS) {
            const force = Math.pow(1 - d / REPEL_RADIUS, 2) * REPEL;
            bx += (dx / d) * force;
            by += (dy / d) * force;
          }
        }
        p.x += (bx - p.x) * 0.22;
        p.y += (by - p.y) * 0.22;
        ctx.globalAlpha = 0.35 + progress * 0.65;
        ctx.fillRect(p.x - dot / 2, p.y - dot / 2, dot, dot);
      }
      ctx.globalAlpha = 1;
      if (gathering && complete) gathering = false;
    };

    const sample = async () => {
      const current = ++build;
      // Layout sizes rather than getBoundingClientRect: a transform on an
      // ancestor scales the canvas along with the text, so it must not be
      // counted twice.
      const box = { width: span.offsetWidth, height: span.offsetHeight };
      if (box.width <= 0 || box.height <= 0) return;
      width = Math.ceil(box.width) + BLEED_X * 2;
      height = Math.ceil(box.height) + BLEED_Y * 2;
      const dpr = Math.min(window.devicePixelRatio || 1, 3);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const css = getComputedStyle(span);
      const font = `${css.fontWeight} ${css.fontSize} ${css.fontFamily}`;
      try {
        await document.fonts?.load(font);
        await document.fonts?.ready;
      } catch {
        // A font that will not load still draws in its fallback.
      }
      if (current !== build) return;

      // Draw the word once, off screen, at device resolution, exactly where the
      // span puts it — then every opaque cell of a grid becomes a particle.
      const off = document.createElement("canvas");
      off.width = canvas.width;
      off.height = canvas.height;
      const o = off.getContext("2d", { willReadFrequently: true });
      if (!o) return;
      o.setTransform(dpr, 0, 0, dpr, 0, 0);
      o.font = font;
      if ("letterSpacing" in o) o.letterSpacing = css.letterSpacing === "normal" ? "0px" : css.letterSpacing;
      // The baseline is read off the layout rather than guessed from the font
      // metrics: a zero-height inline-block sits exactly on it.
      const probe = document.createElement("span");
      probe.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline";
      span.appendChild(probe);
      const baseline = probe.offsetTop - span.offsetTop;
      probe.remove();
      o.textBaseline = "alphabetic";
      o.fillStyle = "#fff";
      o.fillText(text, BLEED_X, BLEED_Y + baseline);

      const pixels = o.getImageData(0, 0, off.width, off.height).data;
      const step = Math.max(1, Math.round(dpr * 0.9));
      dot = (step / dpr) * 1.15;
      const targets: { x: number; y: number }[] = [];
      for (let y = 0; y < off.height; y += step) {
        for (let x = 0; x < off.width; x += step) {
          if (pixels[(y * off.width + x) * 4 + 3] > 110) targets.push({ x: x / dpr, y: y / dpr });
        }
      }

      const root = getComputedStyle(document.documentElement);
      const from = root.getPropertyValue("--color-flame-from").trim() || "#ff7854";
      const to = root.getPropertyValue("--color-flame-to").trim() || "#fd267d";
      const g = ctx.createLinearGradient(BLEED_X, BLEED_Y, BLEED_X + box.width, BLEED_Y + box.height);
      g.addColorStop(0, from);
      g.addColorStop(1, to);
      fill = g;

      particles = targets.map((target, i) => {
        const seed = ((i * 9301 + 49297) % 233280) / 233280;
        const depth = 0.45 + (((i * 233 + 97) % 1000) / 1000) * 0.9;
        return { ...target, startX: 0, startY: 0, targetX: target.x, targetY: target.y, seed, depth, delay: seed * STAGGER_MS };
      });
      scatterAll();
      setLive(particles.length > 0);
      if (frame === null) frame = window.requestAnimationFrame(render);
    };

    const onMove = (event: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      pointer.x = event.clientX - r.left;
      pointer.y = event.clientY - r.top;
      if (!pointer.active) {
        pointer.sx = pointer.x;
        pointer.sy = pointer.y;
      }
      pointer.active = true;
    };
    const onLeave = () => {
      pointer.active = false;
    };
    // A tap on a phone has no hover, so a tap is what replays the gather.
    const onClick = () => scatterAll();
    const onMotion = () => {
      if (motion.matches) {
        if (frame !== null) window.cancelAnimationFrame(frame);
        frame = null;
        ctx.clearRect(0, 0, width, height);
        setLive(false);
      } else void sample();
    };

    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("click", onClick);
    motion.addEventListener("change", onMotion);
    const observer = new ResizeObserver(() => void sample());
    observer.observe(span);

    return () => {
      build += 1;
      observer.disconnect();
      motion.removeEventListener("change", onMotion);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("click", onClick);
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [text]);

  return (
    <span className="relative inline-block">
      <span ref={textRef} className={`block ${className} ${live ? "text-transparent" : "brand-text"}`}>
        {text}
      </span>
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="absolute"
        style={{ left: -BLEED_X, top: -BLEED_Y, width: `calc(100% + ${BLEED_X * 2}px)`, height: `calc(100% + ${BLEED_Y * 2}px)` }}
      />
    </span>
  );
}
