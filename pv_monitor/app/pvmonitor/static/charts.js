"use strict";

// Small SVG charts: one y-axis, bars (optionally stacked) and lines over a
// shared category axis, with legend, hover tooltip and a table view.

const Charts = (() => {
  const escC = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function niceStep(span, target) {
    const raw = span / target;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  }

  function extent(series) {
    let lo = 0;
    let hi = 0;
    const stacks = {};
    for (const s of series) {
      if (s.type === "info") continue; // not drawn, so it does not stretch the axis
      s.values.forEach((v, i) => {
        if (v == null) return;
        if (s.type === "bar" && s.stack) {
          const key = s.stack + ":" + i;
          stacks[key] = (stacks[key] || 0) + Math.max(v, 0);
          hi = Math.max(hi, stacks[key]);
          lo = Math.min(lo, v);
        } else {
          hi = Math.max(hi, v);
          lo = Math.min(lo, v);
        }
      });
    }
    return [lo, hi];
  }

  /**
   * options: { labels: [..], ticks: (label, index) => text|null, series: [{name,
   * color, type: "bar"|"line"|"info" (tooltip and table only), stack, dashed, faint, values}], format: v => text,
   * unit, height }
   */
  function draw(el, options) {
    const { labels, series, format } = options;
    const n = labels.length;
    const W = Math.max(280, el.clientWidth || 320);
    const H = options.height || 220;
    let [lo, hi] = extent(series);
    if (hi === lo) hi = lo + 1;
    const step = niceStep(hi - lo, 4);
    hi = Math.ceil(hi / step) * step;
    lo = Math.floor(lo / step) * step;
    // the left margin follows the widest axis label, so none is clipped
    const widest = Math.max(format(lo, true).length, format(hi, true).length);
    const m = { l: Math.round(widest * 6.4) + 12, r: 10, t: 8, b: 22 };
    const pw = W - m.l - m.r;
    const ph = H - m.t - m.b;
    const y = (v) => m.t + ph - ((v - lo) / (hi - lo)) * ph;
    const band = pw / Math.max(n, 1);
    const cx = (i) => m.l + band * (i + 0.5);

    let svg = "";
    for (let v = lo; v <= hi + step / 2; v += step) {
      const yy = y(v).toFixed(1);
      svg += `<line class="grid${Math.abs(v) < step / 1e6 ? " zero" : ""}" x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}"/>`;
      svg += `<text class="tick" x="${m.l - 6}" y="${yy}" dy="0.32em" text-anchor="end">${escC(format(v, true))}</text>`;
    }
    let lastTickX = -Infinity;
    labels.forEach((label, i) => {
      const text = options.ticks ? options.ticks(label, i) : label;
      if (text == null || cx(i) - lastTickX < 34) return;
      lastTickX = cx(i);
      svg += `<text class="tick" x="${cx(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${escC(text)}</text>`;
    });

    const barSeries = series.filter((s) => s.type === "bar");
    const stackNames = [...new Set(barSeries.map((s) => s.stack || s.name))];
    const groupW = Math.max(2, Math.min(26 * stackNames.length, band - 2));
    const barW = Math.max(1.5, groupW / stackNames.length - (stackNames.length > 1 ? 2 : 0));
    const top = new Map();
    for (const s of barSeries) {
      const slot = stackNames.indexOf(s.stack || s.name);
      s.values.forEach((v, i) => {
        if (v == null || v === 0) return;
        const key = slot + ":" + i;
        const base = top.get(key) || 0;
        const from = v >= 0 ? base : 0;
        const to = v >= 0 ? base + v : v;
        if (v >= 0) top.set(key, to);
        const y1 = y(Math.max(from, to));
        let h = Math.abs(y(from) - y(to));
        const gap = base > 0 && h > 4 ? 2 : 0; // surface gap between stacked segments
        h -= gap;
        const x = cx(i) - groupW / 2 + slot * (groupW / stackNames.length) + (stackNames.length > 1 ? 1 : 0);
        const r = Math.min(3, barW / 2, h / 2);
        svg += `<rect x="${x.toFixed(1)}" y="${y1.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(h, 0.5).toFixed(1)}" rx="${r.toFixed(1)}" style="fill:${s.color}"/>`;
      });
    }
    for (const s of series.filter((x) => x.type === "line")) {
      let d = "";
      let pen = false;
      s.values.forEach((v, i) => {
        if (v == null) {
          pen = false;
          return;
        }
        d += `${pen ? "L" : "M"}${cx(i).toFixed(1)} ${y(v).toFixed(1)}`;
        pen = true;
      });
      svg += `<path d="${d}" fill="none" style="stroke:${s.color}" stroke-width="${s.faint ? 1 : 2}" ${s.faint ? 'opacity="0.45"' : ""} ${s.dashed ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    svg += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ph}" visibility="hidden"/>`;
    svg += `<rect class="hit" x="${m.l}" y="${m.t}" width="${pw}" height="${ph}" fill="transparent"/>`;

    const named = series.filter((s) => !s.hidden);
    const drawn = named.filter((s) => s.type !== "info");
    const legend =
      drawn.length > 1
        ? `<div class="legend">${drawn
            .map((s) => `<span><i class="${s.type}${s.dashed ? " dashed" : ""}${s.faint ? " faint" : ""}" style="--c:${s.color}"></i>${escC(s.name)}</span>`)
            .join("")}</div>`
        : "";
    const table = `<details><summary>Tabelle</summary><div class="scroll"><table><thead><tr><th>${escC(options.labelHead || "Monat")}</th>${named
      .map((s) => `<th>${escC(s.name)}</th>`)
      .join("")}</tr></thead><tbody>${labels
      .map((label, i) => `<tr><td>${escC(label)}</td>${named.map((s) => `<td>${s.values[i] == null ? "–" : escC((s.format || format)(s.values[i]))}</td>`).join("")}</tr>`)
      .reverse()
      .join("")}</tbody></table></div></details>`;

    el.innerHTML = `${legend}<div class="plot"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${escC(options.title || "")}">${svg}</svg><div class="tip" hidden></div></div>${table}`;

    const plot = el.querySelector(".plot");
    const tip = el.querySelector(".tip");
    const cross = el.querySelector(".cross");
    const hit = el.querySelector(".hit");
    const show = (ev) => {
      const box = plot.getBoundingClientRect();
      const px = ev.clientX - box.left;
      const i = Math.max(0, Math.min(n - 1, Math.floor((px - m.l) / band)));
      const rows = named
        .filter((s) => s.values[i] != null)
        .map((s) => `<div><i class="${s.type}" style="--c:${s.color}"></i>${escC(s.name)}<b>${escC((s.format || format)(s.values[i]))}</b></div>`)
        .join("");
      if (!rows) return hide();
      cross.setAttribute("x1", cx(i));
      cross.setAttribute("x2", cx(i));
      cross.setAttribute("visibility", "visible");
      tip.innerHTML = `<div class="tip-head">${escC(labels[i])}</div>${rows}`;
      tip.hidden = false;
      const tw = tip.offsetWidth;
      let left = cx(i) + 10;
      if (left + tw > W) left = cx(i) - 10 - tw;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = m.t + "px";
    };
    const hide = () => {
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", hide);
  }

  return { draw };
})();
