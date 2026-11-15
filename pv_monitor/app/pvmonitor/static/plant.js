"use strict";

// The start page: roof areas with their strings, grid, battery and consumers,
// live or for a day, month or year. Plus the setup page that edits the layout.
// Uses esc, nf, num, api, run, showError and $ from app.js.

const Plant = (() => {
  let layout = null;
  let haOk = false;
  let mode = "live"; // live | day | month | year
  let date = isoDay(new Date());
  let data = null;
  let step = -1; // -1 = the whole period, otherwise an index into data.steps
  let selected = null; // string id
  let timer = null;
  let loadSeq = 0;
  let draft = null;
  let brush = null;
  let known = null; // entities offered by Home Assistant
  let idCounter = 0;

  const ICONS = ["🔌", "🌡️", "🚗", "🧺", "🌀", "🏊", "🍳", "♨️", "💡", "🖥️", "❄️", "🚿"];
  const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

  function isoDay(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function shift(period, day, n) {
    const d = new Date(day + "T12:00:00");
    if (period === "day") d.setDate(d.getDate() + n);
    else if (period === "month") d.setMonth(d.getMonth() + n, 1);
    else d.setFullYear(d.getFullYear() + n, 0, 1);
    return isoDay(d);
  }
  function periodLabel() {
    if (mode === "day") return `${date.slice(8, 10)}.${date.slice(5, 7)}.${date.slice(0, 4)}`;
    if (mode === "month") return `${MONTHS[Number(date.slice(5, 7)) - 1]} ${date.slice(0, 4)}`;
    return date.slice(0, 4);
  }
  function stepLabel(s) {
    const d = new Date(s.start);
    if (mode === "day") return `${d.getHours()}–${d.getHours() + 1} Uhr`;
    if (mode === "month") return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
    return MONTHS[d.getMonth()];
  }

  const live = () => mode === "live";
  const power = (w) => (w == null ? "–" : Math.abs(w) >= 1000 ? nf(1).format(w / 1000) + " kW" : nf(0).format(w) + " W");
  const energy = (k) => (k == null ? "–" : nf(Math.abs(k) < 100 ? 1 : 0).format(k) + " kWh");
  const amount = (v) => (live() ? power(v) : energy(v));

  // ---------------------------------------------------------------- picture

  /** Per string the shown value and its share 0..1 of the scale's top. */
  function stringLevels() {
    const kwp = Object.fromEntries(data.strings.map((s) => [s.id, s.kwp]));
    const spec = (id, v) => (v == null ? null : kwp[id] ? v / kwp[id] : v);
    let shown;
    let top;
    if (step >= 0 && data.steps && data.steps[step]) {
      shown = data.steps[step].strings;
      top = Math.max(0, ...data.steps.flatMap((s) => Object.entries(s.strings).map(([id, v]) => spec(id, v) || 0)));
    } else {
      shown = Object.fromEntries(data.strings.map((s) => [s.id, s.value]));
      // live: against the rated power, so a dull day looks dull
      const rated = live() && data.strings.every((s) => s.kwp || s.value == null);
      top = rated ? 1000 : Math.max(0, ...data.strings.map((s) => spec(s.id, s.value) || 0));
    }
    const out = {};
    for (const s of data.strings) {
      const v = shown[s.id];
      const sp = spec(s.id, v);
      out[s.id] = { value: v, has_sensor: s.has_sensor, specific: s.kwp && v != null ? v / s.kwp : null, level: sp == null || !top ? null : Math.max(0, Math.min(1, sp / top)) };
    }
    return out;
  }

  const fill = (level) => (level == null ? "var(--line)" : `color-mix(in oklab, var(--seq-hi) ${Math.round(level * 100)}%, var(--seq-lo))`);

  function roofSvg(levels) {
    const W = 400;
    const gap = 18;
    const cols = layout.areas.reduce((n, a) => n + a.cols, 0);
    const maxRows = Math.max(...layout.areas.map((a) => a.rows));
    const c = Math.max(8, Math.min(30, (W - gap * (layout.areas.length - 1)) / cols, 300 / maxRows));
    const used = cols * c + gap * (layout.areas.length - 1);
    let x = (W - used) / 2;
    const top = 24;
    const H = top + maxRows * c + 6;
    const names = Object.fromEntries(layout.strings.map((s) => [s.id, s.name]));
    let svg = "";
    for (const a of layout.areas) {
      const w = a.cols * c;
      const y0 = top + (maxRows - a.rows) * c; // areas stand on a common base line
      const title = a.name + (a.azimuth != null ? ` · ${nf(0).format(a.azimuth)}°` : "");
      svg += `<text class="area-title" x="${x + w / 2}" y="${y0 - 8}" text-anchor="middle">${esc(title)}</text>`;
      svg += `<rect class="area" x="${x - 3}" y="${y0 - 3}" width="${w + 6}" height="${a.rows * c + 6}" rx="5"/>`;
      const centers = {};
      a.cells.forEach((sid, i) => {
        if (sid == null) return;
        const cx = x + (i % a.cols) * c;
        const cy = y0 + Math.floor(i / a.cols) * c;
        const lv = levels[sid] || {};
        svg += `<rect class="cell${selected === sid ? " sel" : ""}" data-string="${esc(sid)}" x="${(cx + 1).toFixed(1)}" y="${(cy + 1).toFixed(1)}" width="${(c - 2).toFixed(1)}" height="${(c - 2).toFixed(1)}" rx="2" style="fill:${fill(lv.level)}"/>`;
        const t = (centers[sid] = centers[sid] || { x: 0, y: 0, n: 0 });
        t.x += cx + c / 2;
        t.y += cy + c / 2;
        t.n += 1;
      });
      // name and figures sit inside the string, at the centre of its modules
      for (const [sid, t] of Object.entries(centers)) {
        const lv = levels[sid] || {};
        const lines = [["name", names[sid]]];
        if (c >= 14) lines.push(["val", !lv.has_sensor ? "kein Sensor" : amount(lv.value)]);
        if (c >= 14 && t.n >= 6 && lv.specific != null) lines.push(["spec", `${nf(live() ? 0 : 2).format(lv.specific)} ${live() ? "W/kWp" : "kWh/kWp"}`]);
        const y = t.y / t.n - ((lines.length - 1) * 12) / 2;
        lines.forEach(([cls, text], i) => {
          svg += `<text class="string-label ${cls}${t.n < 4 ? " small" : ""}" x="${(t.x / t.n).toFixed(1)}" y="${(y + i * 12).toFixed(1)}" dy="0.35em" text-anchor="middle">${esc(text)}</text>`;
        });
      }
      x += w + gap;
    }
    return `<svg class="roof" viewBox="0 0 ${W} ${H.toFixed(0)}" role="img" aria-label="Dachflächen mit Strings">${svg}</svg>`;
  }

  function flowSvg() {
    const g = data.grid;
    const b = data.battery;
    const idle = live() ? 5 : 0.05;
    const node = (x, y, icon, value, lines, cls = "") =>
      `<g class="node ${cls}"><circle cx="${x}" cy="${y}" r="27"/><text class="icon" x="${x}" y="${y}" dy="0.36em" text-anchor="middle">${icon}</text>` +
      `<text class="val" x="${x}" y="${y + 45}" text-anchor="middle">${esc(value)}</text>` +
      lines.map((t, i) => `<text class="sub" x="${x}" y="${y + 60 + i * 13}" text-anchor="middle">${esc(t)}</text>`).join("") +
      "</g>";
    // a line from a to b; the dashes run in the direction of the energy
    const line = (x1, y1, x2, y2, flow, color) => {
      const cls = flow == null || Math.abs(flow) <= idle ? "idle" : flow > 0 ? "fwd" : "rev";
      return `<line class="flow ${cls}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"${cls === "idle" ? "" : ` style="stroke:var(--c-${color})"`}/>`;
    };
    let svg = line(200, 62, 200, 100, data.pv, "sun");
    svg += `<g class="node"><circle cx="200" cy="34" r="27"/><text class="icon" x="200" y="34" dy="0.36em" text-anchor="middle">☀️</text><text class="val" x="236" y="31" >${esc(amount(data.pv))}</text><text class="sub" x="236" y="46">PV-Erzeugung</text></g>`;
    svg += node(200, 128, "🏠", amount(data.house), [live() ? "Verbrauch jetzt" : "Verbrauch"]);
    if (g) {
      svg += line(100, 128, 172, 128, g.net, g.net > 0 ? "cost" : "sun"); // bought power is red, fed-in sun is yellow
      // history shows both directions; a net figure would hide the exchange
      const lines = live()
        ? [g.net == null ? "Netz" : g.net > idle ? "Netzbezug" : g.net < -idle ? "Einspeisung" : "Netz"]
        : ["Netzbezug", `Einspeisung ${energy(g.out)}`];
      svg += node(72, 128, "⚡", live() ? power(g.net == null ? null : Math.abs(g.net)) : energy(g.in), lines);
    }
    if (b) {
      svg += line(228, 128, 300, 128, b.net, "neutral"); // positive = charging = towards the battery
      const lines = live()
        ? [(b.net == null ? "Batterie" : b.net > idle ? "lädt" : b.net < -idle ? "entlädt" : "ruht") + (b.soc != null ? ` · ${nf(0).format(b.soc)} %` : "")]
        : ["geladen", `entladen ${energy(b.out)}`];
      svg += node(328, 128, "🔋", live() ? power(b.net == null ? null : Math.abs(b.net)) : energy(b.in), lines);
    }
    return `<svg class="flows" viewBox="0 0 400 ${live() ? 196 : 208}" role="img" aria-label="Energiefluss">${svg}</svg>`;
  }

  function consumersHtml() {
    const list = data.consumers.map((c) => ({ ...c }));
    if (!list.length) return "";
    if (data.other != null) list.push({ id: "_other", name: "Sonstiges", icon: "🏠", value: data.other });
    list.sort((a, b) => (b.value || 0) - (a.value || 0));
    const top = Math.max(data.house || 0, ...list.map((c) => c.value || 0)) || 1;
    return (
      `<h2>Verbraucher</h2><div class="consumers">` +
      list
        .map(
          (c) =>
            `<div class="consumer"><span class="icon">${esc(c.icon || "🔌")}</span><span class="name">${esc(c.name)}</span><b>${esc(amount(c.value))}</b><span class="bar"><i style="width:${Math.max(0, Math.min(100, ((c.value || 0) / top) * 100)).toFixed(1)}%"></i></span></div>`
        )
        .join("") +
      "</div>"
    );
  }

  function detailHtml() {
    const s = data.strings.find((x) => x.id === selected);
    if (!s) return "";
    const facts = [`${s.modules} Module`, s.kwp ? `${nf(2).format(s.kwp)} kWp` : "Modulleistung fehlt"].join(" · ");
    return `<h2>String ${esc(s.name)}</h2><p class="muted chart-note">${esc(facts)}</p>${!live() && data.steps && data.steps.length ? '<div class="card chart" id="string-chart"></div>' : ""}`;
  }

  function render() {
    const el = $("#plant");
    if (!layout) return;
    const tabs = [["live", "Live"], ["day", "Tag"], ["month", "Monat"], ["year", "Jahr"]]
      .map(([m, t]) => `<button data-mode="${m}" class="${mode === m ? "active" : ""}">${t}</button>`)
      .join("");
    let html = `<div class="range" role="group" aria-label="Ansicht">${tabs}</div>`;
    if (!live())
      html += `<div class="datenav"><button data-nav="-1" aria-label="zurück">‹</button><span>${esc(periodLabel())}</span><button data-nav="1" aria-label="weiter" ${shift(mode, date, 1) > isoDay(new Date()) ? "disabled" : ""}>›</button></div>`;
    if (!layout.areas.length || !layout.strings.length) {
      html += '<div class="card"><p>Das Anlagenbild ist noch nicht eingerichtet. Unter <b>Einrichtung</b> legst du Strings, Dachflächen und Verbraucher an und ordnest ihnen die Sensoren aus Home Assistant zu.</p></div>';
    } else if (!haOk) {
      html += '<div class="card"><p>Keine Verbindung zu Home Assistant. Das Anlagenbild braucht den PV Monitor als App in Home Assistant.</p></div>';
    } else if (!data) {
      html += '<div class="card"><p class="muted">Lade Werte …</p></div>';
    } else {
      const levels = stringLevels();
      html += `<div class="card picture"><div class="roofwrap">${roofSvg(levels)}</div>`;
      if (!live() && data.steps && data.steps.length > 1)
        html += `<div class="slider"><input type="range" min="-1" max="${data.steps.length - 1}" value="${step}" aria-label="Zeitpunkt"><span>${step < 0 ? "ganzer Zeitraum" : esc(stepLabel(data.steps[step]))}</span></div>`;
      html += `</div><div class="card picture">${flowSvg()}</div>${consumersHtml()}${detailHtml()}`;
    }
    el.innerHTML = html;

    el.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
    el.querySelectorAll("[data-nav]").forEach((b) =>
      b.addEventListener("click", () => {
        date = shift(mode, date, Number(b.dataset.nav));
        step = -1;
        load();
      })
    );
    const bindStrings = () =>
      el.querySelectorAll("[data-string]").forEach((n) =>
        n.addEventListener("click", () => {
          selected = selected === n.dataset.string ? null : n.dataset.string;
          render();
        })
      );
    bindStrings();
    const slider = el.querySelector(".slider input");
    if (slider)
      slider.addEventListener("input", () => {
        step = Number(slider.value);
        // redraw only the roof, so the thumb keeps the focus while dragging
        el.querySelector(".roofwrap").innerHTML = roofSvg(stringLevels());
        el.querySelector(".slider span").textContent = step < 0 ? "ganzer Zeitraum" : stepLabel(data.steps[step]);
        bindStrings();
      });
    const chart = $("#string-chart");
    if (chart)
      Charts.draw(chart, {
        title: "Verlauf",
        labels: data.steps.map(stepLabel),
        labelHead: "Zeit",
        ticks: (label, i) => (mode === "day" ? (i % 3 === 0 ? String(new Date(data.steps[i].start).getHours()) : null) : mode === "month" ? label.slice(0, 2) : label.slice(0, 3)),
        format: (v) => nf(v < 10 ? 2 : 1).format(v) + " kWh",
        series: [{ name: "Ertrag", type: "bar", color: "var(--c-sun)", values: data.steps.map((s) => s.strings[selected] ?? null) }],
      });
  }

  async function load() {
    const seq = ++loadSeq;
    if (!layout || !layout.strings.length || !haOk) return render();
    try {
      const fresh = live() ? await api("GET", "api/plant/live") : await api("GET", `api/plant/history?period=${mode}&date=${date}`);
      if (seq !== loadSeq) return; // a newer request is on its way
      data = fresh;
      showError("");
    } catch (err) {
      if (seq !== loadSeq) return;
      showError(err.message);
    }
    render();
  }

  function setMode(m) {
    mode = m;
    data = null;
    step = -1;
    schedule();
    render();
    load();
  }

  function schedule() {
    clearInterval(timer);
    timer = null;
    if (live() && !$("#plant").hidden) timer = setInterval(load, 5000);
  }

  // ------------------------------------------------------------------ setup

  const newId = (p) => `${p}${Date.now().toString(36)}${idCounter++}`;
  const entityInput = (path, value, label) =>
    `<label>${label}<input data-p="${path}" list="ents" value="${esc(value || "")}" placeholder="sensor.…" autocapitalize="off" autocomplete="off" spellcheck="false"></label>`;

  function renderSetup() {
    const el = $("#setup");
    if (!draft) return;
    const strings = draft.strings
      .map(
        (s, i) => `<div class="card"><form onsubmit="return false">
        <label>Name<input data-p="strings.${i}.name" value="${esc(s.name)}"></label>
        <label>Modulleistung (W)<input data-p="strings.${i}.module_watts" type="number" step="any" inputmode="decimal" value="${s.module_watts ?? ""}"></label>
        <label>Wechselrichter<input data-p="strings.${i}.inverter" value="${esc(s.inverter || "")}"></label>
        ${entityInput(`strings.${i}.power_entity`, s.power_entity, "Sensor Leistung")}
        ${entityInput(`strings.${i}.energy_entity`, s.energy_entity, "Sensor Energie (optional)")}
        <div class="actions"><button class="link danger" data-act="del-string" data-i="${i}">String entfernen</button></div>
      </form></div>`
      )
      .join("");
    const brushes =
      `<div class="brushes">Feld antippen setzt: ` +
      [{ id: null, name: "leer" }, ...draft.strings].map((s) => `<button class="${brush === s.id ? "active" : ""}" data-act="brush" data-id="${esc(s.id ?? "")}">${esc(s.name)}</button>`).join("") +
      "</div>";
    const areas = draft.areas
      .map((a, i) => {
        const c = Math.min(34, Math.floor(320 / a.cols));
        const cells = a.cells
          .map((sid, n) => {
            const idx = draft.strings.findIndex((s) => s.id === sid);
            return `<button class="pcell${sid ? " on" : ""}" data-act="paint" data-i="${i}" data-n="${n}" style="${sid ? `--k:${idx % 6}` : ""}">${sid ? esc((draft.strings[idx] || {}).name || "") : ""}</button>`;
          })
          .join("");
        return `<div class="card"><form onsubmit="return false">
        <label>Name<input data-p="areas.${i}.name" value="${esc(a.name)}"></label>
        <label>Ausrichtung (° Kompass)<input data-p="areas.${i}.azimuth" type="number" step="any" inputmode="decimal" value="${a.azimuth ?? ""}"></label>
        <label>Neigung (°)<input data-p="areas.${i}.tilt" type="number" step="any" inputmode="decimal" value="${a.tilt ?? ""}"></label>
        <label>Spalten<input data-p="areas.${i}.cols" type="number" min="1" max="40" inputmode="numeric" value="${a.cols}"></label>
        <label>Reihen<input data-p="areas.${i}.rows" type="number" min="1" max="40" inputmode="numeric" value="${a.rows}"></label>
        <div class="actions"><button class="link danger" data-act="del-area" data-i="${i}">Fläche entfernen</button></div>
      </form>
      ${brushes}
      <div class="painter" style="grid-template-columns:repeat(${a.cols}, ${c}px);grid-auto-rows:${c}px">${cells}</div></div>`;
      })
      .join("");
    const devices = draft.devices
      .map((d, i) => {
        const two = d.kind !== "consumer";
        const a = d.kind === "grid" ? ["Bezug", "Einspeisung"] : ["Laden", "Entladen"];
        return `<div class="card"><form onsubmit="return false">
        <label>Art<select data-p="devices.${i}.kind">${[["grid", "Netz"], ["battery", "Batterie"], ["consumer", "Verbraucher"]].map(([k, t]) => `<option value="${k}" ${d.kind === k ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        <label>Name<input data-p="devices.${i}.name" value="${esc(d.name)}"></label>
        ${d.kind === "consumer" ? `<label>Symbol<select data-p="devices.${i}.icon">${ICONS.map((ic) => `<option ${d.icon === ic ? "selected" : ""}>${ic}</option>`).join("")}</select></label>` : ""}
        ${entityInput(`devices.${i}.power_entity`, d.power_entity, two ? `Leistung ${a[0]} (oder Saldo)` : "Sensor Leistung")}
        ${two ? entityInput(`devices.${i}.power_entity_2`, d.power_entity_2, `Leistung ${a[1]} (optional)`) : ""}
        ${entityInput(`devices.${i}.energy_entity`, d.energy_entity, two ? `Zähler ${a[0]}` : "Sensor Energie (optional)")}
        ${two ? entityInput(`devices.${i}.energy_entity_2`, d.energy_entity_2, `Zähler ${a[1]}`) : ""}
        ${d.kind === "battery" ? entityInput(`devices.${i}.soc_entity`, d.soc_entity, "Ladestand (%)") : ""}
        ${two ? `<label class="check"><input type="checkbox" data-p="devices.${i}.invert" ${d.invert ? "checked" : ""}> Saldo-Sensor: Vorzeichen umkehren</label>` : ""}
        <div class="actions"><button class="link danger" data-act="del-device" data-i="${i}">Gerät entfernen</button></div>
      </form></div>`;
      })
      .join("");
    const options = (known || []).map((e) => `<option value="${esc(e.entity_id)}">${esc(e.name)} (${esc(e.unit)})</option>`).join("");
    el.innerHTML = `
      <datalist id="ents">${options}</datalist>
      <p class="muted">${haOk ? (known ? `${known.length} Sensoren aus Home Assistant stehen zur Auswahl.` : "Lade Sensoren aus Home Assistant …") : "Keine Verbindung zu Home Assistant, Sensoren lassen sich nur von Hand eintragen."}</p>
      <h2>1. Strings</h2>${strings}
      <p><button class="secondary" data-act="add-string">String hinzufügen</button></p>
      <h2>2. Dachflächen</h2>${draft.strings.length ? "" : '<p class="muted">Lege zuerst die Strings an.</p>'}${areas}
      <p><button class="secondary" data-act="add-area">Dachfläche hinzufügen</button></p>
      <h2>3. Netz, Batterie und Verbraucher</h2>
      <p class="muted">Bei Netz und Batterie genügt ein Saldo-Sensor: positiv bedeutet Bezug bzw. Laden. Läuft er andersherum, das Vorzeichen umkehren.</p>${devices}
      <p><button class="secondary" data-act="add-device">Gerät hinzufügen</button></p>
      <p class="actions"><button class="primary" data-act="save">Einrichtung speichern</button></p>
      <h2>Sichern und übernehmen</h2>
      <div class="card"><p class="muted">Die Einrichtung als Text, zum Sichern oder Einfügen.</p>
        <textarea id="layout-json" rows="6" spellcheck="false"></textarea>
        <p class="actions"><button class="secondary" data-act="export">Aktuelle Einrichtung anzeigen</button><button class="secondary" data-act="import">Text übernehmen</button></p></div>`;
  }

  function setPath(path, value) {
    const parts = path.split(".");
    let node = draft;
    for (const p of parts.slice(0, -1)) node = node[p];
    node[parts[parts.length - 1]] = value;
  }

  function resizeArea(a, cols, rows) {
    const cells = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) cells.push(r < a.rows && c < a.cols ? a.cells[r * a.cols + c] : null);
    Object.assign(a, { cols, rows, cells });
  }

  function onSetupChange(ev) {
    const input = ev.target;
    const path = input.dataset.p;
    if (!path) return;
    let value = input.type === "checkbox" ? input.checked : input.value.trim();
    if (input.type === "number") value = input.value === "" ? null : Number(input.value);
    else if (value === "") value = input.type === "checkbox" ? false : null;
    const [list, i, key] = path.split(".");
    if (list === "areas" && (key === "cols" || key === "rows")) {
      const a = draft.areas[i];
      const n = Math.max(1, Math.min(40, Math.round(value || 1)));
      resizeArea(a, key === "cols" ? n : a.cols, key === "rows" ? n : a.rows);
      return renderSetup();
    }
    setPath(path, value);
    if (key === "kind" || (list === "strings" && key === "name")) renderSetup();
  }

  function onSetupClick(ev) {
    const btn = ev.target.closest("[data-act]");
    if (!btn) return;
    const i = Number(btn.dataset.i);
    const act = btn.dataset.act;
    if (act === "paint") {
      const a = draft.areas[i];
      const n = Number(btn.dataset.n);
      a.cells[n] = a.cells[n] === brush ? null : brush;
    } else if (act === "brush") brush = btn.dataset.id || null;
    else if (act === "add-string") {
      const s = { id: newId("s"), name: `String ${draft.strings.length + 1}`, module_watts: null, inverter: "", power_entity: null, energy_entity: null };
      draft.strings.push(s);
      brush = s.id;
    } else if (act === "del-string") {
      const [gone] = draft.strings.splice(i, 1);
      draft.areas.forEach((a) => (a.cells = a.cells.map((c) => (c === gone.id ? null : c))));
      if (brush === gone.id) brush = null;
    } else if (act === "add-area") draft.areas.push({ id: newId("a"), name: `Fläche ${draft.areas.length + 1}`, azimuth: null, tilt: null, cols: 4, rows: 4, cells: Array(16).fill(null) });
    else if (act === "del-area") draft.areas.splice(i, 1);
    else if (act === "add-device") {
      const kind = !draft.devices.some((d) => d.kind === "grid") ? "grid" : !draft.devices.some((d) => d.kind === "battery") ? "battery" : "consumer";
      draft.devices.push({ id: newId("d"), kind, name: { grid: "Netz", battery: "Batterie", consumer: "Verbraucher" }[kind], icon: "🔌", power_entity: null, power_entity_2: null, energy_entity: null, energy_entity_2: null, soc_entity: null, invert: false });
    } else if (act === "del-device") draft.devices.splice(i, 1);
    else if (act === "export") {
      $("#layout-json").value = JSON.stringify(draft, null, 1);
      return;
    } else if (act === "import") {
      try {
        const doc = JSON.parse($("#layout-json").value);
        draft = { areas: doc.areas || [], strings: doc.strings || [], devices: doc.devices || [] };
        showError("");
      } catch (err) {
        return showError("Der Text ist kein gültiges JSON.");
      }
    } else if (act === "save") {
      return run(async () => {
        const saved = await api("PUT", "api/plant/layout", draft);
        layout = saved.layout;
        draft = JSON.parse(JSON.stringify(layout));
        data = null;
        selected = null;
        renderSetup();
        btnFlash("Gespeichert");
      });
    }
    renderSetup();
  }

  function btnFlash(text) {
    const b = $('#setup [data-act="save"]');
    if (!b) return;
    b.textContent = text;
    setTimeout(() => b.isConnected && (b.textContent = "Einrichtung speichern"), 2000);
  }

  // ------------------------------------------------------------------ wiring

  async function init() {
    $("#setup").addEventListener("change", onSetupChange);
    $("#setup").addEventListener("click", onSetupClick);
    try {
      const res = await api("GET", "api/plant/layout");
      layout = res.layout;
      haOk = res.ha;
    } catch (err) {
      layout = { areas: [], strings: [], devices: [] };
      showError(err.message);
    }
    onTab(document.querySelector("#tabs button.active").dataset.tab);
  }

  function onTab(tab) {
    schedule();
    if (tab === "plant") {
      render();
      load();
    } else if (tab === "setup" && layout) {
      draft = JSON.parse(JSON.stringify(layout));
      renderSetup();
      if (haOk && !known)
        api("GET", "api/plant/entities")
          .then((r) => {
            known = r.entities;
            if (!$("#setup").hidden) {
              $("#ents").innerHTML = known.map((e) => `<option value="${esc(e.entity_id)}">${esc(e.name)} (${esc(e.unit)})</option>`).join("");
              $("#setup > p.muted").textContent = `${known.length} Sensoren aus Home Assistant stehen zur Auswahl.`;
            }
          })
          .catch((err) => showError(err.message));
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearInterval(timer);
    else if (!$("#plant").hidden) {
      schedule();
      load();
    }
  });

  return { init, onTab };
})();

Plant.init();
