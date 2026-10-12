"use client";

import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { displayName } from "@/lib/companies";

export interface MapPin {
  id: number;
  name: string;
  industry: string | null;
  sub_industry: string | null;
  lat: number;
  lon: number;
  mobile_count: number;
  best_fit: { solution: "odoo" | "frinzo" | "it"; label: string; fit_level: "medium" | "high"; points: number } | null;
}

const LEBANON: L.LatLngTuple = [33.85, 35.86];
const SHORT = { odoo: "Odoo", frinzo: "Frinzo", it: "IT" } as const;

/** Companies as circle pins coloured by best fit (high / medium / none), with a popup linking to the company.
 * Plain Leaflet (client only: the page imports it with ssr: false). OpenStreetMap tiles need a Referer. */
export default function CompaniesMap({ pins }: { pins: MapPin[] }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const router = useRouter();

  useEffect(() => {
    const m = L.map(box.current!, { preferCanvas: true }).setView(LEBANON, 8);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      referrerPolicy: "strict-origin-when-cross-origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    map.current = m;
    layer.current = L.layerGroup().addTo(m);
    return () => {
      // a zoom / pan animation still running would redraw the canvas after remove() (clearRect of undefined)
      m.stop();
      m.off();
      m.remove();
      map.current = layer.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    const group = layer.current;
    if (!m || !group) return;
    group.clearLayers();
    const css = getComputedStyle(document.documentElement);
    const colour = (token: string) => `rgb(${css.getPropertyValue(`--${token}`).trim()})`;
    const tone = { high: colour("success"), medium: colour("info"), none: colour("fg-subtle") };
    for (const p of pins) {
      const c = tone[p.best_fit?.fit_level ?? "none"];
      L.circleMarker([p.lat, p.lon], { radius: 6, color: "#fff", weight: 1, fillColor: c, fillOpacity: 0.9 })
        .bindPopup(() => popup(p, (href) => router.push(href)))
        .addTo(group);
    }
    if (pins.length) m.fitBounds(L.latLngBounds(pins.map((p) => [p.lat, p.lon])), { padding: [24, 24], maxZoom: 14, animate: false });
    else m.setView(LEBANON, 8, { animate: false });
  }, [pins, router]);

  return <div ref={box} className="h-[560px] w-full" role="region" aria-label="Companies map" />;
}

/** Built with textContent: company names come from public directories. */
function popup(p: MapPin, go: (href: string) => void): HTMLElement {
  const root = document.createElement("div");
  root.className = "space-y-0.5 text-[12.5px]";
  const line = (text: string, className: string) => {
    const el = document.createElement("div");
    el.className = className;
    el.textContent = text;
    root.append(el);
  };
  line(displayName(p.name), "font-medium text-fg");
  const industry = p.industry && p.industry !== "Other" ? p.industry : p.sub_industry;
  if (industry) line(industry, "text-fg-muted");
  line(p.mobile_count ? `📱 ${p.mobile_count} mobile${p.mobile_count === 1 ? "" : "s"}` : "No mobile yet", "text-fg-muted");
  if (p.best_fit) line(`${SHORT[p.best_fit.solution]} · ${p.best_fit.fit_level === "high" ? "High" : "Medium"}`, "text-fg");
  const a = document.createElement("a");
  a.href = `/companies/${p.id}`;
  a.className = "mt-1 inline-block font-medium text-accent hover:underline";
  a.textContent = "Open company →";
  a.style.color = "rgb(var(--accent))"; // beats .leaflet-container a
  a.onclick = (e) => {
    e.preventDefault();
    go(a.getAttribute("href")!);
  };
  root.append(a);
  return root;
}
