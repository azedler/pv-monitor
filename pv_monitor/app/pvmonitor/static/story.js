"use strict";

// The three overview pages of the redesign (Doc 142): Jahr, Monate, Speicher,
// and the theme switch. Every figure carries the time range it belongs to.
// Uses state, $, esc, nf, num, eur, pct from app.js.

const Story = (() => {
  const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
  const SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
  let yearKey = "last12";
  let trendRange = 0; // months shown on the Monate page, 0 = all
  let storageKey = "since";

  const mIdx = (m) => Number(m.slice(5, 7)) - 1;
  const monthName = (m) => `${MONTHS[mIdx(m)]} ${m.slice(0, 4)}`;
  const monthShort = (m) => `${SHORT[mIdx(m)]} ${m.slice(0, 4)}`;
  const lastDay = (m) => new Date(Number(m.slice(0, 4)), mIdx(m) + 1, 0).getDate();
  /** "1. November 2025 – 31. Oktober 2026" */
  const spanDates = (first, last) => `1. ${monthName(first)} – ${lastDay(last)}. ${monthName(last)}`;
  const spanShort = (first, last) => (first === last ? monthShort(first) : `${monthShort(first)} – ${monthShort(last)}`);
  const kwh = (v) => num(v) + " kWh";
  const pct0 = (v) => (v == null ? "–" : nf(0).format(v * 100) + " %");
  const calIcon = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"></rect><line x1="1.5" y1="6" x2="14.5" y2="6" stroke="currentColor" stroke-width="1.5"></line></svg>';

  const real = () => state.months.filter((m) => !m.baseline);
  const eegMonth = () => (state.settings.eeg_date ? state.settings.eeg_date.slice(0, 7) : null);

  function seg(items, current, attr) {
    return `<div class="seg" role="group" aria-label="Zeitraum">${items
      .map(([key, label]) => `<button type="button" ${attr}="${esc(key)}" aria-pressed="${String(key) === String(current)}">${esc(label)}</button>`)
      .join("")}</div>`;
  }

  function head(title, plaque, covers, picker, store) {
    return `<div class="pagehead"><div class="lead"><h1>${esc(title)}</h1>
      <div class="plaque-row"><span class="plaque${store ? " store" : ""}">${calIcon}${esc(plaque)}</span>${covers ? `<span class="covers">${esc(covers)}</span>` : ""}</div></div>${picker}</div>`;
  }

  function empty(el, text) {
    el.innerHTML = `<div class="pagehead"><div class="lead"><h1>PV Monitor</h1></div></div><div class="hint">${text}</div>`;
  }

  // ------------------------------------------------------------------ Jahr

  function sunSvg(slots, opts) {
    const cx = 340, cy = 340, base = 170, outMax = 300, inMin = 80, gap = 4;
    const gMax = Math.max(1, ...slots.map((s) => s.gen || 0));
    const bMax = Math.max(1, ...slots.map((s) => s.grid || 0));
    const rad = (d) => (d * Math.PI) / 180;
    const pt = (r, a) => `${(cx + r * Math.sin(rad(a))).toFixed(1)} ${(cy - r * Math.cos(rad(a))).toFixed(1)}`;
    const sector = (rIn, rOut, a0, a1) =>
      `M${pt(rIn, a0)} L${pt(rOut, a0)} A${rOut.toFixed(1)} ${rOut.toFixed(1)} 0 0 1 ${pt(rOut, a1)} L${pt(rIn, a1)} A${rIn.toFixed(1)} ${rIn.toFixed(1)} 0 0 0 ${pt(rIn, a0)} Z`;
    const span = outMax - base - gap;
    const step = gMax > 2400 ? 1000 : gMax > 1200 ? 500 : gMax > 400 ? 200 : 100;
    let svg = "";
    for (let v = step; v < gMax; v += step) {
      const r = base + gap + (span * v) / gMax;
      svg += `<circle cx="${cx}" cy="${cy}" r="${r.toFixed(1)}" fill="none" stroke="var(--line)" stroke-width="1" stroke-dasharray="3 5"></circle>`;
      svg += `<text x="346" y="${(cy - r - 4).toFixed(1)}" fill="var(--faint)" font-size="11">${nf(0).format(v)}</text>`;
    }
    svg += `<circle cx="${cx}" cy="${cy}" r="${base}" fill="none" stroke="var(--feed)" stroke-width="1.5"></circle>`;
    slots.forEach((s, i) => {
      const a0 = i * 30 + 3, a1 = i * 30 + 27;
      if (s.gen != null) {
        const len = Math.max(3, (span * s.gen) / gMax);
        svg += `<path d="${sector(base + gap, base + gap + len, a0, a1)}" style="fill:var(--sun)" fill-opacity="${(0.55 + (0.45 * s.gen) / gMax).toFixed(2)}"><title>${esc(s.title)}: ${kwh(s.gen)} erzeugt</title></path>`;
      }
      if (s.grid != null) {
        const len = Math.max(3, ((base - gap - inMin) * s.grid) / bMax);
        svg += `<path d="${sector(base - gap - len, base - gap, a0, a1)}" style="fill:var(--grid)" fill-opacity="0.88"><title>${esc(s.title)}: ${kwh(s.grid)} aus dem Netz</title></path>`;
      }
      const a = rad(i * 30 + 15), r = 322;
      svg += `<text x="${(cx + r * Math.sin(a)).toFixed(1)}" y="${(cy - r * Math.cos(a)).toFixed(1)}" fill="${s.gen == null ? "var(--faint)" : "var(--text2)"}" font-size="15" font-weight="500" text-anchor="middle" dominant-baseline="middle">${esc(s.label)}</text>`;
    });
    svg += `<text x="${cx}" y="333" fill="var(--text)" font-size="36" font-weight="700" text-anchor="middle" class="num">${nf(0).format(opts.total)}</text>`;
    svg += `<text x="${cx}" y="360" fill="var(--muted)" font-size="14" text-anchor="middle">kWh erzeugt</text>`;
    return `<svg viewBox="0 0 680 680" role="img" aria-label="${esc(opts.aria)}" style="width:100%;max-width:640px;height:auto;display:block;margin:0 auto">${svg}</svg>`;
  }

  function sunSlots(p, rows) {
    if (p.key === "last12") {
      return rows.map((r) => ({ label: SHORT[mIdx(r.month)], title: monthName(r.month), gen: r.pv_yield, grid: r.grid_kwh + r.heat_kwh }));
    }
    if (p.key === "all") {
      // average per calendar month, so a three-year history still fits one circle
      return SHORT.map((label, i) => {
        const same = rows.filter((r) => mIdx(r.month) === i);
        if (!same.length) return { label, title: label, gen: null, grid: null };
        const avg = (f) => same.reduce((n, r) => n + f(r), 0) / same.length;
        return { label, title: `${MONTHS[i]}, Durchschnitt aus ${same.length} Jahr${same.length > 1 ? "en" : ""}`, gen: avg((r) => r.pv_yield), grid: avg((r) => r.grid_kwh + r.heat_kwh) };
      });
    }
    return SHORT.map((label, i) => {
      const r = rows.find((x) => mIdx(x.month) === i);
      return r ? { label, title: monthName(r.month), gen: r.pv_yield, grid: r.grid_kwh + r.heat_kwh } : { label, title: label, gen: null, grid: null };
    });
  }

  function renderYear() {
    const el = $("#year");
    const ps = state.periods || [];
    if (!ps.length) return empty(el, "Noch keine Monatswerte. Unter <b>Erfassung</b> trägst du den ersten Monat ein.");
    const p = ps.find((x) => x.key === yearKey) || ps[0];
    yearKey = p.key;
    const rows = real().filter((r) => r.month >= p.first && r.month <= p.last);
    const slots = sunSlots(p, rows);
    const dates = spanDates(p.first, p.last);
    const short = spanShort(p.first, p.last);
    const kwp = state.settings.plant_kwp ? ` · ${nf(2).format(state.settings.plant_kwp)} kWp` : "";
    const peak = rows.reduce((a, r) => (r.pv_yield > a.pv_yield ? r : a), rows[0]);
    const low = rows.reduce((a, r) => (r.pv_yield < a.pv_yield ? r : a), rows[0]);
    const sub =
      p.key === "all"
        ? `Durchschnitt je Kalendermonat, im Uhrzeigersinn ab Januar oben`
        : `ein Segment je Monat, im Uhrzeigersinn ab ${MONTHS[p.key === "last12" ? mIdx(p.first) : 0]} oben`;
    const kpiLabel = p.label;
    const lowGrid = low.grid_kwh + low.heat_kwh;
    const caption = `Spitze im ${monthName(peak.month)} mit ${kwh(peak.pv_yield)} · ${monthName(low.month)} nur ${kwh(low.pv_yield)}, dafür ${kwh(lowGrid)} aus dem Netz`;
    const w = p.went, c = p.came;
    el.innerHTML = `
      ${head("Dein Solarjahr", dates, `Alle Zahlen dieser Seite gelten für diesen Zeitraum (${p.months} Monate)${kwp}`, seg(ps.map((x) => [x.key, x.label]), yearKey, "data-year"))}
      <div class="row">
        <section class="panel wide">
          <div class="head"><div><h2>${p.key === "all" ? "Die Jahre als Sonne" : "Das Jahr als Sonne"}</h2><span class="sub">${esc(sub)} · ${esc(short)}</span></div>
            <div class="legend-inline"><span><i style="background:var(--sun)"></i>Erzeugung (nach außen)</span><span><i style="background:var(--grid)"></i>Netzbezug (nach innen)</span></div></div>
          ${sunSvg(slots, { total: p.pv_yield, aria: `Kreisdiagramm ${short}: Erzeugung je Monat nach außen, Netzbezug nach innen. ${caption}.` })}
          <p class="sub" style="text-align:center;margin:0">${esc(caption)}</p>
        </section>
        <div class="side">
          <section class="kpi"><span class="k">Autarkie · ${esc(kpiLabel)}</span><span class="big" style="color:var(--sun-ink)">${pct0(p.autarky)}</span>
            <div class="bar"><i style="width:${((p.autarky || 0) * 100).toFixed(1)}%;background:var(--sun)"></i></div><span class="t">deines Verbrauchs kam vom eigenen Dach</span></section>
          <section class="kpi"><span class="k">Eigenverbrauch · ${esc(kpiLabel)}</span><span class="big">${pct0(p.own_consumption_quota)}</span>
            <div class="bar"><i style="width:${((p.own_consumption_quota || 0) * 100).toFixed(1)}%;background:var(--text)"></i></div><span class="t">des Solarstroms selbst genutzt, der Rest eingespeist</span></section>
          <section class="kpi money"><span class="k">Wert · ${esc(kpiLabel)}</span><span class="big">${eur(p.revenue, 0)}</span>
            <span class="t">${eur(p.saving, 0)} gesparter Netzbezug + ${eur(p.feed_revenue, 0)} Einspeisung</span></section>
        </div>
      </div>
      <section class="panel split">
        <div style="display:flex;flex-direction:column;gap:14px"><h2>Wohin ging der Solarstrom? <span class="when">${esc(short)}</span></h2>
          <div class="stack" role="img" aria-label="Direkt ${pct0(w.direct)}, Speicher ${pct0(w.battery)}, eingespeist ${pct0(w.feed)}">
            <div style="width:${(w.direct || 0) * 100}%;background:var(--sun)"></div><div style="width:${(w.battery || 0) * 100}%;background:var(--store)"></div><div style="width:${(w.feed || 0) * 100}%;background:var(--feed)"></div></div>
          <div class="stack-legend"><span><b style="color:var(--sun-ink)">${pct0(w.direct)}</b> direkt verbraucht · ${kwh(p.direct)}</span><span><b style="color:var(--store-ink)">${pct0(w.battery)}</b> in den Speicher · ${kwh(p.battery_charged)}</span><span><b style="color:var(--feed-ink)">${pct0(w.feed)}</b> eingespeist · ${kwh(p.feed_kwh)}</span></div></div>
        <div style="display:flex;flex-direction:column;gap:14px"><h2>Woher kam dein Strom? <span class="when">${esc(short)}</span></h2>
          <div class="stack" role="img" aria-label="Dach ${pct0(c.direct)}, Speicher ${pct0(c.battery)}, Netz ${pct0(c.grid)}">
            <div style="width:${(c.direct || 0) * 100}%;background:var(--sun)"></div><div style="width:${(c.battery || 0) * 100}%;background:var(--store)"></div><div style="width:${(c.grid || 0) * 100}%;background:var(--grid)"></div></div>
          <div class="stack-legend"><span><b style="color:var(--sun-ink)">${pct0(c.direct)}</b> direkt vom Dach</span><span><b style="color:var(--store-ink)">${pct0(c.battery)}</b> aus dem Speicher · ${kwh(p.battery_discharged)}</span><span><b style="color:var(--grid-ink)">${pct0(c.grid)}</b> aus dem Netz · ${kwh(p.grid_kwh)}</span></div></div>
      </section>
      <p class="source">Quelle: Monatswerte im PV Monitor, je Abrechnungsmonat (Zählerstände, PV-Ertrag, Speicher). Wert = selbst genutzter Solarstrom zum damals gültigen Arbeitspreis plus Einspeisevergütung, wie unter Wirtschaft.</p>`;
    el.querySelectorAll("[data-year]").forEach((b) => b.addEventListener("click", () => { yearKey = b.dataset.year; renderYear(); }));
  }

  // ------------------------------------------------------------------ Monate

  function mirrorSvg(rows) {
    const n = rows.length, left = 60, width = 1230, step = width / n, axis = 280, upMax = 230, downMax = 170;
    const bw = Math.max(6, Math.min(32, step * 0.62));
    const gMax = Math.max(1, ...rows.map((r) => r.pv_yield));
    const bMax = Math.max(1, ...rows.map((r) => r.grid_kwh + r.heat_kwh));
    const eeg = eegMonth();
    let svg = "";
    const pre = eeg ? rows.filter((r) => r.month < eeg).length : 0;
    if (pre) svg += `<rect x="${left}" y="30" width="${(pre * step).toFixed(1)}" height="478" rx="10" style="fill:var(--band)"></rect><text x="${(left + 8).toFixed(1)}" y="46" fill="var(--muted)" font-size="12">vor Inbetriebnahme</text>`;
    const gStep = gMax > 2400 ? 1000 : gMax > 1200 ? 500 : 200;
    for (let v = gStep; v < gMax; v += gStep) {
      const y = axis - (upMax * v) / gMax;
      svg += `<line x1="${left}" x2="1290" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--line)" stroke-dasharray="3 5"></line><text x="52" y="${(y + 4).toFixed(1)}" fill="var(--faint)" font-size="12" text-anchor="end">${nf(0).format(v)}</text>`;
    }
    const bStep = bMax > 1200 ? 1000 : bMax > 600 ? 500 : 200;
    for (let v = bStep; v < bMax; v += bStep) {
      const y = 284 + (downMax * v) / bMax;
      svg += `<line x1="${left}" x2="1290" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--line)" stroke-dasharray="3 5"></line><text x="52" y="${(y + 4).toFixed(1)}" fill="var(--faint)" font-size="12" text-anchor="end">${nf(0).format(v)}</text>`;
    }
    rows.forEach((r, i) => {
      const x = left + i * step + (step - bw) / 2, cx = x + bw / 2;
      const grid = r.grid_kwh + r.heat_kwh;
      const gh = Math.max(2, (upMax * r.pv_yield) / gMax), bh = Math.max(2, (downMax * grid) / bMax);
      if (i && mIdx(r.month) === 0) svg += `<line x1="${(left + i * step).toFixed(1)}" x2="${(left + i * step).toFixed(1)}" y1="40" y2="505" stroke="var(--feed)"></line>`;
      svg += `<g><title>${esc(monthName(r.month))}: ${kwh(r.pv_yield)} erzeugt, ${kwh(grid)} aus dem Netz</title>`;
      svg += `<rect x="${x.toFixed(1)}" y="${(axis - gh).toFixed(1)}" width="${bw.toFixed(1)}" height="${gh.toFixed(1)}" rx="${Math.min(5, bw / 3).toFixed(1)}" style="fill:var(--sun)" fill-opacity="${(0.55 + (0.45 * r.pv_yield) / gMax).toFixed(2)}"></rect>`;
      svg += `<rect x="${x.toFixed(1)}" y="284" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="${Math.min(5, bw / 3).toFixed(1)}" style="fill:var(--grid)" fill-opacity="0.88"></rect></g>`;
      if (n <= 26 || i % 2 === 0) svg += `<text x="${cx.toFixed(1)}" y="478" fill="var(--text2)" font-size="13" text-anchor="middle">${SHORT[mIdx(r.month)]}</text>`;
      if (i === 0 || mIdx(r.month) === 0) svg += `<text x="${(left + i * step + 6).toFixed(1)}" y="504" fill="var(--muted)" font-size="13" font-weight="600">${r.month.slice(0, 4)}</text>`;
    });
    svg += `<line x1="${left}" x2="1290" y1="282" y2="282" stroke="var(--muted)"></line>`;
    const pi = rows.findIndex((r) => r.pv_yield === gMax);
    svg += `<text x="${(left + pi * step + step / 2).toFixed(1)}" y="${(axis - upMax - 8).toFixed(1)}" fill="var(--sun-ink)" font-size="13" font-weight="600" text-anchor="middle">${nf(0).format(gMax)}</text>`;
    return `<svg viewBox="0 0 1300 520" role="img" aria-label="Balken je Monat: Erzeugung nach oben, Netzbezug nach unten">${svg}</svg>`;
  }

  function bandSvg(rows) {
    const n = rows.length, left = 60, step = 1230 / n, size = Math.max(14, Math.min(48, step - 4));
    const eeg = eegMonth();
    let svg = "";
    rows.forEach((r, i) => {
      const a = r.autarky == null ? 0 : Math.max(0, Math.min(1, r.autarky));
      const t = Math.pow(a, 1.3);
      const x = left + i * step + (step - size) / 2;
      const pre = eeg && r.month < eeg;
      svg += `<g><title>${esc(monthName(r.month))}: Autarkie ${pct0(r.autarky)}${pre ? " (vor Inbetriebnahme)" : ""}</title><rect x="${x.toFixed(1)}" y="4" width="${size.toFixed(1)}" height="48" rx="10" style="fill:color-mix(in oklab, var(--sun) ${Math.round(t * 100)}%, var(--track))"${pre ? ' stroke="var(--muted)" stroke-dasharray="2 3"' : ""}></rect>`;
      if (size >= 24) svg += `<text x="${(x + size / 2).toFixed(1)}" y="33" fill="${t > 0.55 ? "#141A2E" : "var(--text)"}" font-size="${size >= 40 ? 15 : 12}" font-weight="600" text-anchor="middle" class="num">${Math.round(a * 100)}</text>`;
      svg += "</g>";
    });
    return `<svg viewBox="0 0 1300 60" role="img" aria-label="Autarkie je Monat in Prozent">${svg}</svg>`;
  }

  function renderTrend() {
    const el = $("#trend");
    const all = real();
    if (!all.length) return empty(el, "Noch keine Monatswerte.");
    const rows = trendRange ? all.slice(-trendRange) : all;
    const first = rows[0].month, last = rows[rows.length - 1].month;
    const eeg = eegMonth();
    const covers = eeg && first < eeg
      ? `Die Monate vor der Inbetriebnahme am ${state.settings.eeg_date.slice(8, 10)}.${state.settings.eeg_date.slice(5, 7)}.${state.settings.eeg_date.slice(0, 4)} liegen auf einem grauen Band`
      : "";
    const ps = (state.periods || []).filter((p) => p.key !== "all");
    const cols = ps.map((p) => `<th scope="col">${esc(p.label)}<br><span class="when">${esc(spanShort(p.first, p.last))}</span></th>`).join("");
    const line = (label, f, cls) => `<tr><th scope="row">${label}</th>${ps.map((p) => `<td class="${p.key === "last12" ? cls || "now" : ""}">${f(p)}</td>`).join("")}</tr>`;
    el.innerHTML = `
      ${head("Sommer und Winter", `${spanDates(first, last)} · jeder Balken ein Abrechnungsmonat`, covers, seg([[0, "Seit Start"], [24, "24 Monate"], [12, "12 Monate"]], trendRange, "data-trend"))}
      <section class="panel"><div class="head"><h2>Erzeugung gegen Netzbezug, kWh je Monat <span class="when">${esc(spanShort(first, last))}</span></h2>
        <div class="legend-inline"><span><i style="background:var(--sun)"></i>Erzeugung</span><span><i style="background:var(--grid)"></i>Netzbezug</span>${eeg && first < eeg ? '<span><i style="background:var(--band);border:1px solid var(--line)"></i>vor Inbetriebnahme</span>' : ""}</div></div>
        <div class="chartwrap wide">${mirrorSvg(rows)}</div></section>
      <section class="panel"><div class="head"><h2>Autarkie je Monat, % <span class="when">${esc(spanShort(first, last))}</span></h2><span class="sub">je kräftiger, desto mehr vom eigenen Dach</span></div>
        <div class="chartwrap wide">${bandSvg(rows)}</div></section>
      <section class="panel"><h2>Jahresvergleich</h2>
        <div class="chartwrap"><table class="cmp" style="min-width:560px"><thead><tr><th scope="col" style="text-align:left">Größe</th>${cols}</tr></thead><tbody>
          ${line("Erzeugung", (p) => kwh(p.pv_yield))}
          ${line("Eigenverbrauchsquote", (p) => pct(p.own_consumption_quota))}
          ${line("Autarkie", (p) => pct(p.autarky))}
          ${line("Einspeisung", (p) => kwh(p.feed_kwh))}
          ${line("Netzbezug", (p) => kwh(p.grid_kwh), "grid")}
          ${line("Wert", (p) => eur(p.revenue, 0))}
        </tbody></table></div>
        <p class="sub" style="margin:0">Angefangene Jahre sind als solche benannt; ihre Summen sind nicht mit vollen Jahren vergleichbar.</p></section>
      <p class="source">Quelle: Monatswerte im PV Monitor, je Abrechnungsmonat. Netzbezug einschließlich Wärmestrom, solange es den Zähler gab.</p>`;
    el.querySelectorAll("[data-trend]").forEach((b) => b.addEventListener("click", () => { trendRange = Number(b.dataset.trend); renderTrend(); }));
  }

  // ------------------------------------------------------------------ Speicher

  function storageRows(st) {
    const rows = real().filter((r) => r.battery_charged != null && (!st || r.month >= st.install_month));
    if (storageKey === "12") return rows.slice(-12);
    if (storageKey.startsWith("y")) return rows.filter((r) => r.month.startsWith(storageKey.slice(1)));
    return rows;
  }

  function throughputSvg(rows) {
    const n = rows.length, left = 60, step = 1230 / n, axis = 300, hMax = 250;
    const vMax = Math.max(1, ...rows.map((r) => Math.max(r.battery_charged || 0, r.battery_discharged || 0)));
    const bw = Math.max(4, Math.min(17, step / 2 - 2));
    const effTop = 378, effBot = 452;
    const ey = (v) => effBot - ((effBot - effTop) * (Math.max(20, v) - 20)) / 80;
    let svg = "";
    const gStep = vMax > 300 ? 100 : vMax > 120 ? 50 : 20;
    for (let v = gStep; v < vMax; v += gStep) {
      const y = axis - (hMax * v) / vMax;
      svg += `<line x1="${left}" x2="1290" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--line)" stroke-dasharray="3 5"></line><text x="52" y="${(y + 4).toFixed(1)}" fill="var(--faint)" font-size="12" text-anchor="end">${v}</text>`;
    }
    const dots = [];
    rows.forEach((r, i) => {
      const cx = left + i * step + step / 2;
      const h1 = Math.max(2, (hMax * (r.battery_charged || 0)) / vMax), h2 = Math.max(2, (hMax * (r.battery_discharged || 0)) / vMax);
      svg += `<g><title>${esc(monthName(r.month))}: ${kwh(r.battery_charged)} geladen, ${kwh(r.battery_discharged)} entladen, Wirkungsgrad ${pct0(r.battery_efficiency)}</title>`;
      svg += `<rect x="${(cx - bw - 1).toFixed(1)}" y="${(axis - h1).toFixed(1)}" width="${bw.toFixed(1)}" height="${h1.toFixed(1)}" rx="4" style="fill:var(--store)"></rect>`;
      svg += `<rect x="${(cx + 1).toFixed(1)}" y="${(axis - h2).toFixed(1)}" width="${bw.toFixed(1)}" height="${h2.toFixed(1)}" rx="4" style="fill:var(--store-hi)"></rect></g>`;
      if (n <= 26 || i % 2 === 0) svg += `<text x="${cx.toFixed(1)}" y="326" fill="var(--text2)" font-size="13" text-anchor="middle">${SHORT[mIdx(r.month)]}</text>`;
      if (i === 0 || mIdx(r.month) === 0) svg += `<text x="${(left + i * step + 6).toFixed(1)}" y="350" fill="var(--muted)" font-size="13" font-weight="600">${r.month.slice(0, 4)}</text>`;
      if (r.battery_efficiency != null) dots.push([cx, ey(r.battery_efficiency * 100)]);
    });
    svg += `<line x1="${left}" x2="1290" y1="${axis}" y2="${axis}" stroke="var(--muted)"></line>`;
    svg += `<line x1="${left}" x2="1290" y1="${ey(90).toFixed(1)}" y2="${ey(90).toFixed(1)}" stroke="var(--chip-line)" stroke-dasharray="2 4"></line><text x="52" y="${(ey(90) + 4).toFixed(1)}" fill="var(--sun-ink)" font-size="12" text-anchor="end">90 %</text>`;
    svg += `<polyline points="${dots.map((d) => d[0].toFixed(1) + "," + d[1].toFixed(1)).join(" ")}" fill="none" stroke="var(--sun)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"></polyline>`;
    svg += dots.map((d) => `<circle cx="${d[0].toFixed(1)}" cy="${d[1].toFixed(1)}" r="3.5" style="fill:var(--card)" stroke="var(--sun)" stroke-width="2"></circle>`).join("");
    svg += `<text x="${left}" y="474" fill="var(--muted)" font-size="12">Wirkungsgrad je Monat (Skala 20–100 %); im Winter mit wenig Durchsatz fällt er deutlich</text>`;
    return `<svg viewBox="0 0 1300 486" role="img" aria-label="Balken je Monat: geladen und entladen; Linie: Wirkungsgrad">${svg}</svg>`;
  }

  function paybackHtml(st) {
    if (!st) return "";
    const since = spanShort(st.install_month, st.last_month);
    if (!st.cost) {
      return `<section class="panel store"><h2>Wann hat er sich bezahlt gemacht?</h2>
        <div class="hint">Dafür braucht der PV Monitor die Kosten des Speichers. Gib unter <b>Investitionen</b> allen Speicher-Posten die Kategorie „Speicher“ und das Einbaudatum. Bisher seit Einbau (${esc(since)}) zurückgeflossen: <b>${eur(st.benefit_total, 0)}</b>.</div></section>`;
    }
    const sc = st.scenarios.filter((s) => s.month);
    const years = (m) => Number(m.slice(0, 4)) + mIdx(m) / 12;
    const startYear = Math.floor(years(st.install_month));
    const endYear = Math.max(Math.ceil(years(st.last_month)) + 2, ...sc.map((s) => Math.ceil(years(s.month)) + 1));
    const tx = (y) => 60 + ((y - startYear) / (endYear - startYear)) * 1220;
    let svg = `<line x1="60" x2="1280" y1="70" y2="70" stroke="var(--feed)" stroke-width="2"></line>`;
    if (sc.length > 1) {
      const lo = Math.min(...sc.map((s) => years(s.month))), hi = Math.max(...sc.map((s) => years(s.month)));
      svg += `<rect x="${tx(lo).toFixed(1)}" y="54" width="${Math.max(6, tx(hi) - tx(lo)).toFixed(1)}" height="32" rx="8" style="fill:var(--store)" fill-opacity="0.18"></rect>`;
    }
    svg += `<line x1="${tx(years(st.install_month)).toFixed(1)}" x2="${tx(years(st.last_month) + 1 / 12).toFixed(1)}" y1="70" y2="70" stroke="var(--store)" stroke-width="6" stroke-linecap="round"></line>`;
    const tickStep = endYear - startYear > 12 ? 2 : 1;
    for (let y = startYear; y <= endYear; y += tickStep) svg += `<line x1="${tx(y).toFixed(1)}" x2="${tx(y).toFixed(1)}" y1="64" y2="76" stroke="var(--feed)"></line><text x="${tx(y).toFixed(1)}" y="104" fill="var(--faint)" font-size="12" text-anchor="middle">${y}</text>`;
    const label = (g) => (g === 0 ? "gleiche Preise" : `+${nf(0).format(g * 100)} %/Jahr`);
    const marks = [
      { y: years(st.install_month), t: `Einbau ${SHORT[mIdx(st.install_month)]} ${st.install_month.slice(0, 4)}`, fill: "var(--store)", ink: "var(--text2)", ly: 40 },
      { y: years(st.last_month) + 1 / 12, t: "heute", fill: "var(--text)", ink: "var(--text)", ly: 40 },
      ...sc.map((s, i) => ({ y: years(s.month), t: `${label(s.growth)}: ${SHORT[mIdx(s.month)]} ${s.month.slice(0, 4)}`, fill: "var(--store)", ink: "var(--store-ink)", ly: i % 2 ? 136 : 40 })),
    ];
    svg += marks.map((k) => `<circle cx="${tx(k.y).toFixed(1)}" cy="70" r="7" style="fill:${k.fill}" stroke="var(--card)" stroke-width="2"></circle><text x="${tx(k.y).toFixed(1)}" y="${k.ly}" style="fill:${k.ink}" font-size="13" font-weight="600" text-anchor="middle">${esc(k.t)}</text>`).join("");
    const share = Math.max(0, st.share || 0);
    const scText = sc.length
      ? `Fortgeschrieben mit dem Nutzen der letzten 12 Monate und ${nf(1).format(st.aging * 100)} % Alterung pro Jahr: bezahlt ${sc.map((s) => `${SHORT[mIdx(s.month)]} ${s.month.slice(0, 4)} (${label(s.growth)})`).join(", ")}.`
      : "Für eine Fortschreibung braucht es zwölf Monate mit Speicherwerten.";
    return `<section class="panel store">
      <div class="head" style="align-items:flex-end"><div><h2>Wann hat er sich bezahlt gemacht? <span class="when">seit Einbau, ${esc(since)}</span></h2>
        <span class="sub" style="color:var(--text2)">${eur(st.cost, 0)} Kosten (Investitionen, Kategorie Speicher, ${st.items} Posten) · ${eur(st.benefit_12, 0)} Nutzen in den letzten 12 Monaten · seit Einbau ${eur(st.benefit_total, 0)} zurück</span></div>
        <span class="big num" style="font-size:44px;font-weight:700;color:var(--store-ink);line-height:1">${pct0(share)}</span></div>
      <div class="bar" style="height:14px"><i style="width:${Math.min(100, share * 100).toFixed(1)}%;background:var(--store)"></i></div>
      <div class="chartwrap wide"><svg viewBox="0 0 1300 150" role="img" aria-label="Zeitstrahl vom Einbau bis zur Amortisation">${svg}</svg></div>
      <p style="margin:0;color:var(--text2)">${esc(scText)}${st.undated_items ? ` ${st.undated_items} Speicher-Posten ohne Datum; als Einbau gilt der früheste Posten mit Datum.` : ""}</p>
      <p class="sub" style="margin:0">Nutzen je Monat = entladene kWh × damals gültiger Arbeitspreis − geladene kWh × Einspeisevergütung, die sie sonst gebracht hätten.</p>
    </section>`;
  }

  function renderStorage() {
    const el = $("#storage");
    const st = state.storage;
    if (!st) return empty(el, "Noch keine Speicherwerte. Sie kommen mit den Monatswerten (Batterie geladen und entladen).");
    const years = [...new Set(real().filter((r) => r.battery_charged != null && r.month >= st.install_month).map((r) => r.month.slice(0, 4)))];
    const options = [["since", "Seit Einbau"], ["12", "12 Monate"], ...years.map((y) => ["y" + y, y])];
    if (!options.some((o) => o[0] === storageKey)) storageKey = "since";
    const rows = storageRows(st);
    if (!rows.length) return empty(el, "Im gewählten Zeitraum gibt es keine Speicherwerte.");
    const first = rows[0].month, last = rows[rows.length - 1].month;
    const sum = (k) => rows.reduce((n, r) => n + (r[k] || 0), 0);
    const ch = sum("battery_charged"), dis = sum("battery_discharged");
    const prefix = storageKey === "since" ? "Seit Einbau: " : "";
    el.innerHTML = `
      ${head("Der Speicher", `${prefix}${spanDates(first, last)} (${rows.length} Monate)`, "geladen und entladen je Abrechnungsmonat", seg(options, storageKey, "data-store"), true)}
      <div class="stat-row">
        <div class="stat"><span>Geladen · ${esc(spanShort(first, last))}</span><b style="color:var(--store-ink)">${kwh(ch)}</b></div>
        <div class="stat"><span>Entladen · ${esc(spanShort(first, last))}</span><b>${kwh(dis)}</b></div>
        <div class="stat"><span>Verlust · ${esc(spanShort(first, last))}</span><b>${kwh(ch - dis)} · ${pct0(ch ? (ch - dis) / ch : null)}</b></div>
        <div class="stat"><span>Wirkungsgrad · ${esc(spanShort(first, last))}</span><b>${pct0(ch ? dis / ch : null)}</b></div>
      </div>
      <section class="panel"><div class="head"><h2>Durchsatz je Monat, kWh <span class="when">${esc(spanShort(first, last))}</span></h2>
        <div class="legend-inline"><span><i style="background:var(--store)"></i>geladen</span><span><i style="background:var(--store-hi)"></i>entladen</span><span><i class="line" style="background:var(--sun)"></i>Wirkungsgrad</span></div></div>
        <div class="chartwrap wide">${throughputSvg(rows)}</div></section>
      ${paybackHtml(st)}
      <p class="source">Quelle: Monatswerte im PV Monitor (Batterie geladen und entladen), Tarife und Investitionen aus diesem Add-on. Die Amortisation der ganzen Anlage steht unter Wirtschaft.</p>`;
    el.querySelectorAll("[data-store]").forEach((b) => b.addEventListener("click", () => { storageKey = b.dataset.store; renderStorage(); }));
  }

  // ------------------------------------------------------------------ theme

  function applyTheme(choice) {
    const root = document.documentElement;
    if (choice === "light" || choice === "dark") root.dataset.theme = choice;
    else delete root.dataset.theme;
    try {
      if (choice === "light" || choice === "dark") localStorage.setItem("pvm-theme", choice);
      else localStorage.removeItem("pvm-theme");
    } catch (err) {
      /* storage blocked: the choice lasts for this visit */
    }
    document.querySelectorAll("[data-theme-choice]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoice === (choice || "auto"))));
  }

  applyTheme(document.documentElement.dataset.theme || "auto");
  document.querySelectorAll("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.themeChoice)));

  function render() {
    if (!state) return;
    renderYear();
    renderTrend();
    renderStorage();
  }

  return { render, spanShort, spanDates, monthName };
})();
