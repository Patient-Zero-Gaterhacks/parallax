import { useEffect, useRef, useState } from "react";
import { CITIES, LAND, WATER } from "./globeData";

// A spinning dotted globe with a simulated feed of attacks.
// Blue = Parallax blocked it. Red = it reached an AI assistant with no protection.
// None of this is real data; the page says so under the feed.

type City = [string, number, number];
type Attack = { t0: number; city: City; label: string; time: string; blocked: boolean };

const KINDS = [
  "white-on-white text in an email",
  "hidden text in a PDF invoice",
  "hidden text in a Word résumé",
  "invisible Unicode on a web page",
  "page shows AI different content",
  "poisoned MCP tool description",
  "hidden payee address in an email",
  "1-pixel text in a newsletter",
];

const D = Math.PI / 180;
const R = 270; // globe radius in the 600x600 drawing
const C = 300; // globe center
const TILT = 18 * D;
const SPEED = 9; // degrees per second
const sinT = Math.sin(TILT);
const cosT = Math.cos(TILT);

function inPolygon(poly: number[], x: number, y: number) {
  let inside = false;
  for (let i = 0, j = poly.length - 2; i < poly.length; i += 2) {
    const xi = poly[i], yi = poly[i + 1], xj = poly[j], yj = poly[j + 1];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    j = i;
  }
  return inside;
}

// One dot every 3 degrees wherever there's land. Worked out once when the page loads.
function buildLandDots() {
  const dots: [number, number, number][] = [];
  for (let lat = -88; lat <= 86; lat += 3) {
    const c = Math.cos(lat * D);
    for (let lon = -180; lon < 180; lon += 3 / Math.max(c, 0.12)) {
      let land = lat <= -70 || LAND.some((p) => inPolygon(p, lon, lat));
      if (land && WATER.some((w) => inPolygon(w, lon, lat))) land = false;
      if (land) dots.push([lon * D, Math.sin(lat * D), c]);
    }
  }
  return dots;
}
const LAND_DOTS = buildLandDots();

// How far a point faces us (1 = center of the globe, below 0 = behind it).
function facing(lonRad: number, sinLat: number, cosLat: number, spin: number) {
  return sinT * sinLat + cosT * cosLat * Math.cos(lonRad - spin);
}

export default function ThreatMap() {
  const [, redraw] = useState(0);
  const world = useRef({ lon: -40, now: 0, attacks: [] as Attack[], feed: [] as Attack[] });

  useEffect(() => {
    const w = world.current;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function addAttack(t0: number) {
      const spin = w.lon * D;
      const visible = CITIES.filter(
        (c) => facing(c[1] * D, Math.sin(c[2] * D), Math.cos(c[2] * D), spin) > 0.25,
      );
      const pool = visible.length ? visible : CITIES;
      const attack: Attack = {
        t0,
        city: pool[Math.floor(Math.random() * pool.length)],
        label: KINDS[Math.floor(Math.random() * KINDS.length)],
        time: new Date().toISOString().slice(11, 19),
        blocked: Math.random() < 0.7,
      };
      w.attacks.push(attack);
      w.feed = [attack, ...w.feed].slice(0, 5);
    }

    // Start with a few attacks so the globe isn't empty on first paint.
    const start = performance.now();
    w.attacks = [];
    w.feed = [];
    w.now = start;
    addAttack(start - 3200);
    addAttack(start - 1800);
    addAttack(start - 600);
    let next = start + 600;
    let last = start;

    function step(now: number) {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      w.now = now;
      if (!reduced) w.lon = ((w.lon + SPEED * dt + 180) % 360) - 180;
      if (now >= next) {
        addAttack(now);
        next = now + 700 + Math.random() * 900;
      }
      w.attacks = w.attacks.filter((a) => now - a.t0 < 9000);
      redraw((n) => n + 1);
    }

    let frame = 0;
    let timer = 0;
    if (reduced) {
      timer = window.setInterval(() => step(performance.now()), 3000);
    } else {
      const loop = (now: number) => {
        step(now);
        frame = requestAnimationFrame(loop);
      };
      frame = requestAnimationFrame(loop);
    }
    return () => {
      cancelAnimationFrame(frame);
      clearInterval(timer);
    };
  }, []);

  // Project every land dot onto the circle. Dots behind the globe are drawn faintly.
  const w = world.current;
  const spin = w.lon * D;
  let near = "";
  let edge = "";
  let back = "";
  for (const [lon, sinLat, cosLat] of LAND_DOTS) {
    const dl = lon - spin;
    const z = facing(lon, sinLat, cosLat, spin);
    const x = C + R * cosLat * Math.sin(dl);
    const y = C - R * (cosT * sinLat - sinT * cosLat * Math.cos(dl));
    const dot = `M${x.toFixed(1)} ${y.toFixed(1)}h.01`;
    if (z > 0.3) near += dot;
    else if (z > 0) edge += dot;
    else back += dot;
  }

  const pings = w.attacks.flatMap((a) => {
    const sinLat = Math.sin(a.city[2] * D);
    const cosLat = Math.cos(a.city[2] * D);
    const z = facing(a.city[1] * D, sinLat, cosLat, spin);
    if (z <= 0.05) return [];
    const dl = a.city[1] * D - spin;
    const x = C + R * cosLat * Math.sin(dl);
    const y = C - R * (cosT * sinLat - sinT * cosLat * Math.cos(dl));
    const age = (w.now - a.t0) / 1000;
    const ring = Math.min(1, age / 2.4);
    const fade = Math.min(1, z * 4);
    const core = age < 5 ? 1 : Math.max(0, 1 - (age - 5) / 4);
    return [{ key: a.t0, x, y, ring, fade, core, blocked: a.blocked }];
  });

  return (
    <div className="flex min-w-0 flex-[1_1_440px] flex-col items-center gap-5">
      <div className="relative aspect-square w-full max-w-[560px]">
        <svg
          viewBox="0 0 600 600"
          role="img"
          aria-label="A spinning globe. Blue pulses are attacks Parallax blocked; red pulses reached an unprotected AI assistant."
          className="absolute inset-0 size-full"
        >
          <circle cx="300" cy="300" r="270" fill="#060606" stroke="#2e2e2e" />
          <circle cx="300" cy="300" r="289" fill="none" stroke="#242424" strokeDasharray="2 7" />
          <path d={back} fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity="0.1" />
          <path d={edge} fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity="0.35" />
          <path d={near} fill="none" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" opacity="0.9" />
        </svg>

        {/* Pulses. Their position and size change every frame, so they use inline styles. */}
        <div className="pointer-events-none absolute inset-0">
          {pings.map((p) => (
            <div key={p.key} className="absolute size-0" style={{ left: `${p.x / 6}%`, top: `${p.y / 6}%` }}>
              <div
                className={`absolute -mt-[22px] -ml-[22px] size-11 rounded-full border ${
                  p.blocked ? "border-safe" : "border-infected"
                }`}
                style={{ opacity: (1 - p.ring) * 0.8 * p.fade, transform: `scale(${0.2 + p.ring * 2.2})` }}
              />
              <div
                className={`absolute -mt-[5px] -ml-[5px] size-2.5 rounded-full ${p.blocked ? "bg-safe" : "bg-infected"}`}
                style={{ opacity: p.core * p.fade }}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-x-6 gap-y-2 font-mono text-xs text-neutral-400">
        <span className="inline-flex items-center gap-2">
          <span className="size-2 rounded-full bg-safe" /> Blocked by Parallax
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="size-2 rounded-full bg-infected" /> Reached an unprotected AI
        </span>
      </div>

      <div className="w-full max-w-[560px] overflow-hidden rounded-lg border border-neutral-800">
        <div className="flex flex-wrap justify-between gap-3 border-b border-neutral-800 px-3.5 py-2.5 font-mono text-[11px] tracking-[0.08em] text-neutral-500">
          <span>LIVE FEED</span>
          <span>SIMULATED DATA</span>
        </div>
        <div className="min-h-[170px] px-3.5 pt-1.5 pb-2.5">
          {w.feed.map((a, i) => (
            <div
              key={a.t0}
              className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1 py-[7px] font-mono text-xs"
              style={{ opacity: 1 - i * 0.17 }}
            >
              <span className="text-neutral-500">{a.time}</span>
              <span className="tracking-[0.04em]">{a.city[0]}</span>
              <span className="min-w-0 flex-[1_1_160px] text-neutral-400">{a.label}</span>
              <span
                className={`rounded-[3px] px-1.5 py-px text-[10px] tracking-[0.08em] text-white ${
                  a.blocked ? "bg-safe" : "bg-infected"
                }`}
              >
                {a.blocked ? "BLOCKED" : "INFECTED"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
