// PV Monitor roof card for Home Assistant (Doc 143).
//
// The layout comes from sensor.pv_monitor_anlage, which the PV Monitor add-on
// keeps up to date; the live values come straight from Home Assistant, so the
// card keeps showing power while the add-on is stopped. No library, no
// outside requests. Configuration: `type: custom:pv-monitor-roof-card`,
// optionally `entity:` for another layout sensor.

// the add-on registers this file with ?v=<add-on version>; no second copy of the number
const CARD_VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";
const CODES = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const POWER = { W: 1, kW: 1000, MW: 1e6 };

// One font file ships next to this script; @font-face must live in the document.
(() => {
  if (document.getElementById("pv-monitor-card-font")) return;
  const style = document.createElement("style");
  style.id = "pv-monitor-card-font";
  style.textContent = `@font-face { font-family: "PVM Space Grotesk"; src: url("${new URL("space-grotesk.woff2", import.meta.url)}") format("woff2"); font-weight: 300 700; font-display: swap; }`;
  document.head.appendChild(style);
})();

const THEMES = {
  dark: { text: "#EEF1F7", muted: "#9AA6C2", accent: "#F5B342", roof: "#1B2440", ridge: "#3A4870", cell: "#0B1020", pill: "#0B1020", lo: [52, 46, 40], hi: [245, 179, 66], none: "#2A3350" },
  light: { text: "#141A2E", muted: "#5A6683", accent: "#9A6200", roof: "#E6E9F1", ridge: "#B9C2D6", cell: "#FFFFFF", pill: "#FFFFFF", lo: [232, 226, 214], hi: [242, 169, 59], none: "#D5DAE5" },
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (w) => (w == null ? "–" : Math.abs(w) >= 1000 ? `${(w / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} kW` : `${Math.round(w).toLocaleString("de-DE")} W`);
const mix = (a, b, t) => `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
const niceTop = (v) => [100, 200, 300, 500, 800, 1000, 1200].find((s) => s >= v) || Math.ceil(v / 500) * 500;

class PvMonitorRoofCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.pv_monitor_anlage", ...(config || {}) };
    this._key = null;
  }

  static getStubConfig() {
    return { entity: "sensor.pv_monitor_anlage" };
  }

  getCardSize() {
    return 6;
  }

  set hass(hass) {
    this._hass = hass;
    const layout = hass.states[this._config.entity];
    const strings = layout?.attributes?.strings || [];
    // redraw only when something on the card changes
    const key = JSON.stringify([layout?.state, layout?.attributes?.panel, hass.themes?.darkMode, strings.map((s) => hass.states[s.power_entity]?.state)]);
    if (key === this._key) return;
    this._key = key;
    this._render(layout);
  }

  _power(entityId) {
    const st = entityId && this._hass.states[entityId];
    if (!st) return null;
    const v = Number.parseFloat(st.state);
    if (!Number.isFinite(v)) return null;
    return v * (POWER[st.attributes?.unit_of_measurement] ?? 1);
  }

  _render(layout) {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const t = this._hass.themes?.darkMode ? THEMES.dark : THEMES.light;
    const a = layout?.attributes;
    if (!layout || !a?.areas?.length || layout.state === "unavailable") {
      this.shadowRoot.innerHTML = `${this._style(t)}<ha-card><div class="wrap"><div class="head"><div><span class="k">PV-Anlage</span></div></div>
        <p class="hint">Anordnung nicht verfügbar. Der PV Monitor setzt sie beim Start und spätestens eine Minute nach einem Neustart von Home Assistant.</p></div></ha-card>`;
      return;
    }
    const strings = a.strings.map((s) => {
      const w = this._power(s.power_entity);
      return { ...s, w, spec: w != null && s.kwp ? w / s.kwp : null };
    });
    const known = strings.filter((s) => s.w != null);
    const total = known.length ? known.reduce((n, s) => n + s.w, 0) : null;
    const top = niceTop(Math.max(1, ...strings.map((s) => s.spec || 0)));
    const fill = (s) => (s.spec == null ? t.none : mix(t.lo, t.hi, 0.2 + 0.8 * Math.min(1, s.spec / top)));

    // areas side by side on one base line, as in the add-on's "Anlage" page
    const gap = 26, W = 516;
    const cols = a.areas.reduce((n, ar) => n + ar.cols, 0);
    const maxRows = Math.max(...a.areas.map((ar) => ar.rows));
    const c = Math.max(8, Math.min(34, (W - 8 - gap * (a.areas.length - 1)) / cols, 280 / maxRows));
    let x = (W - (cols * c + gap * (a.areas.length - 1))) / 2;
    const y0 = 22, H = y0 + maxRows * c + 34;
    let svg = "";
    const labels = [];
    for (const ar of a.areas) {
      const w = ar.cols * c, top_ = y0 + (maxRows - ar.rows) * c;
      svg += `<rect x="${(x - 5).toFixed(1)}" y="${(top_ - 5).toFixed(1)}" width="${(w + 10).toFixed(1)}" height="${(ar.rows * c + 10).toFixed(1)}" rx="8" fill="${t.roof}"></rect>`;
      svg += `<text x="${(x + w / 2).toFixed(1)}" y="${(top_ - 10).toFixed(1)}" fill="${t.muted}" font-size="12" text-anchor="middle">${esc(ar.name)}${ar.azimuth != null ? ` · ${Math.round(ar.azimuth)}°` : ""}</text>`;
      const centers = {};
      [...ar.cells].forEach((code, i) => {
        if (code === ".") return;
        const s = strings[CODES.indexOf(code)];
        if (!s) return;
        const cx = x + (i % ar.cols) * c, cy = top_ + Math.floor(i / ar.cols) * c;
        svg += `<rect x="${(cx + 1).toFixed(1)}" y="${(cy + 1).toFixed(1)}" width="${(c - 2).toFixed(1)}" height="${(c - 2).toFixed(1)}" rx="2" fill="${fill(s)}" stroke="${t.cell}" stroke-width="1"><title>${esc(s.name)}: ${fmt(s.w)}</title></rect>`;
        const m = (centers[s.id] = centers[s.id] || { x: 0, y: 0, n: 0, s });
        m.x += cx + c / 2; m.y += cy + c / 2; m.n += 1;
      });
      const small = [];
      for (const m of Object.values(centers)) {
        if (m.n >= 6) labels.push({ x: m.x / m.n, y: m.y / m.n, s: m.s, sub: `${ar.name} · ${m.s.name}` });
        else small.push(`${m.s.name} ${fmt(m.s.w)}`);
      }
      // strings of a few modules get their value below the area instead of a plaque
      if (small.length) svg += `<text x="${(x + w / 2).toFixed(1)}" y="${(top_ + ar.rows * c + 22).toFixed(1)}" fill="${t.text}" font-size="12" font-weight="600" text-anchor="middle" class="num">${esc(small.join(" · "))}</text>`;
      x += w + gap;
    }
    // value plaques on top of the modules, one per string
    for (const l of labels) {
      const pw = 112;
      svg += `<rect x="${(l.x - pw / 2).toFixed(1)}" y="${(l.y - 22).toFixed(1)}" width="${pw}" height="44" rx="12" fill="${t.pill}" fill-opacity="0.94"></rect>`;
      svg += `<text x="${l.x.toFixed(1)}" y="${(l.y + 1).toFixed(1)}" fill="${t.text}" font-size="17" font-weight="700" text-anchor="middle" class="num">${fmt(l.s.w)}</text>`;
      svg += `<text x="${l.x.toFixed(1)}" y="${(l.y + 16).toFixed(1)}" fill="${t.muted}" font-size="11" text-anchor="middle">${esc(l.sub)}</text>`;
    }
    const aria = `Dach von oben: ${strings.map((s) => `${s.name} ${fmt(s.w)}`).join(", ")}`;
    const panel = a.panel;
    this.shadowRoot.innerHTML = `${this._style(t)}<ha-card><div class="wrap">
      <div class="head"><div><span class="k">PV-Anlage · jetzt</span><span class="total num">${fmt(total)}</span></div>
        ${panel ? `<button type="button" class="open">PV Monitor öffnen</button>` : ""}</div>
      <svg viewBox="0 0 ${W} ${H.toFixed(0)}" role="img" aria-label="${esc(aria)}">${svg}</svg>
      <div class="foot"><span class="scale"><span>0</span><i style="background:linear-gradient(90deg, ${mix(t.lo, t.hi, 0.2)}, ${mix(t.lo, t.hi, 1)})"></i><span>${top.toLocaleString("de-DE")} W/kWp</span></span>
        <span>Farbe je String nach Leistung pro kWp</span></div></div></ha-card>`;
    const open = this.shadowRoot.querySelector(".open");
    if (open) open.addEventListener("click", () => {
      history.pushState(null, "", panel);
      window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
    });
  }

  _style(t) {
    return `<style>
      .wrap { padding: 20px; display: flex; flex-direction: column; gap: 12px; color: ${t.text}; font-family: var(--paper-font-body1_-_font-family, Inter, system-ui, sans-serif); }
      .head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
      .head > div { display: flex; flex-direction: column; gap: 2px; }
      .k { font-size: 14px; font-weight: 500; color: ${t.muted}; }
      .num { font-family: "PVM Space Grotesk", var(--paper-font-body1_-_font-family, sans-serif); font-variant-numeric: tabular-nums; }
      .total { font-size: 44px; font-weight: 700; line-height: 1; color: ${t.accent}; }
      .open { min-height: 44px; padding: 0 14px; border-radius: 12px; border: 1px solid var(--divider-color, ${t.ridge}); background: none; color: ${t.text}; font-family: inherit; font-size: 14px; font-weight: 500; cursor: pointer; }
      svg { width: 100%; height: auto; display: block; }
      svg text { font-family: var(--paper-font-body1_-_font-family, Inter, system-ui, sans-serif); }
      .foot { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 12px; color: ${t.muted}; }
      .scale { display: flex; align-items: center; gap: 8px; }
      .scale i { width: 140px; height: 8px; border-radius: 999px; display: inline-block; }
      .hint { margin: 0; color: ${t.muted}; }
    </style>`;
  }
}

if (!customElements.get("pv-monitor-roof-card")) customElements.define("pv-monitor-roof-card", PvMonitorRoofCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "pv-monitor-roof-card")) {
  window.customCards.push({ type: "pv-monitor-roof-card", name: "PV Monitor Dach", description: "Module an ihrem Platz, gefärbt nach Leistung je String (aus dem PV Monitor)", preview: false });
}
console.info(`%c PV-MONITOR-ROOF-CARD %c ${CARD_VERSION} `, "background:#F5B342;color:#0B1020;font-weight:700", "");
