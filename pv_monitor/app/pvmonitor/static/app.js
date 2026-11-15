"use strict";

// All URLs are relative: behind Home Assistant ingress the app lives under a
// path prefix it does not know.
let state = null;
let pendingMonth = null; // an entry that was checked but not saved yet
let editing = { tariff: null, investment: null };

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const nf = (digits) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const num = (v, d = 0) => (v == null ? "–" : nf(d).format(v));
const eur = (v, d = 2) => (v == null ? "–" : nf(d).format(v) + " €");
const pct = (v, d = 1) => (v == null ? "–" : nf(d).format(v * 100) + " %");
const monthLabel = (m) => (m ? `${Number(m.slice(5, 7))}/${m.slice(0, 4)}` : "–");
const dateLabel = (d) => (d ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}` : "–");
const KINDS = { grid: "Hausstrom", heat: "Wärmestrom", feed_in: "Einspeisung" };

function showError(message) {
  const box = $("#error");
  box.textContent = message || "";
  box.hidden = !message;
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body instanceof ArrayBuffer) {
    options.body = body;
    options.headers["Content-Type"] = "application/octet-stream";
  } else if (body !== undefined) {
    options.body = JSON.stringify(body);
    options.headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    throw new Error("Keine Verbindung zum PV Monitor.");
  }
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    /* no JSON body */
  }
  if (!response.ok) {
    throw new Error((data && data.error) || `Fehler ${response.status}`);
  }
  return data;
}

async function run(fn) {
  showError("");
  try {
    await fn();
  } catch (err) {
    showError(err.message);
  }
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.value === "") out[el.name] = null;
    else if (el.type === "number") out[el.name] = Number(el.value);
    else out[el.name] = el.value;
  }
  return out;
}

function checksHtml(checks) {
  if (!checks.length) return '<p class="muted">Noch keine Werte.</p>';
  return (
    '<ul class="checks">' +
    checks
      .map((c) => {
        const cls = c.ok === false ? "bad" : c.ok === null ? "na" : "";
        const mark = c.ok === false ? "!" : c.ok === null ? "–" : "✓";
        return `<li class="${cls}"><span class="mark">${mark}</span><span>${esc(c.rule)}${c.message ? ": " + esc(c.message) : ""}</span></li>`;
      })
      .join("") +
    "</ul>"
  );
}

function tile(label, value, sub) {
  return `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>`;
}

function renderOverview() {
  const s = state.summary;
  const el = $("#overview");
  if (!s.last_month) {
    el.innerHTML =
      '<div class="card"><p>Noch keine Daten. Unter <b>Daten</b> lässt sich die Excel-Historie importieren, unter <b>Monate</b> der erste Monat erfassen.</p></div>';
    return;
  }
  const r = s.rolling12;
  const last = state.months[state.months.length - 1];
  const be = s.break_even;
  const beText = !be ? "–" : monthLabel(be.month);
  const beSub = !be ? "nicht absehbar" : be.reached ? "erreicht" : "saisonal fortgeschrieben";
  el.innerHTML = `
    <h2>Wirtschaftlichkeit bis ${monthLabel(s.last_month)}</h2>
    <div class="tiles">
      ${tile("Investition", eur(s.invest_total))}
      ${tile("Erlös kumuliert", eur(s.revenue_total))}
      ${tile("Amortisation", pct(s.amortisation), "offen " + eur(s.remaining, 0))}
      ${tile("Break-even", beText, beSub)}
    </div>
    <h2>Letzte ${r.months} Monate</h2>
    <div class="tiles">
      ${tile("PV-Ertrag", num(r.pv_yield) + " kWh")}
      ${tile("Autarkiegrad", pct(r.autarky))}
      ${tile("Eigenverbrauchsquote", pct(r.own_consumption_quota))}
      ${tile("Netzbezug", num(r.grid_kwh) + " kWh")}
      ${tile("Einspeisung", num(r.feed_kwh) + " kWh")}
      ${tile("Erlös", eur(r.revenue))}
      ${tile("Stromkosten", eur(r.cost_total), "inklusive Grundpreis")}
    </div>
    <h2>${monthLabel(last.month)}</h2>
    <div class="tiles">
      ${tile("PV-Ertrag", num(last.pv_yield) + " kWh")}
      ${tile("selbst genutzt", num(last.self_use) + " kWh")}
      ${tile("Netzbezug", num(last.grid_kwh) + " kWh")}
      ${tile("Autarkiegrad", pct(last.autarky))}
      ${tile("Erlös", eur(last.revenue))}
      ${tile("Effektivpreis", last.effective_price == null ? "–" : nf(4).format(last.effective_price) + " €", "je bezogener kWh")}
    </div>
    <h2>Prüfung ${monthLabel(last.month)}</h2>
    <div class="card">${checksHtml(state.checks)}</div>`;
}

function renderMonths() {
  const el = $("#months");
  const hasHeat = state.meters.some((m) => m.kind === "heat" && !m.active_to);
  const rows = [...state.months].reverse();
  const today = new Date().toISOString().slice(0, 10);
  el.innerHTML = `
    <h2>Monat erfassen</h2>
    <div class="card">
      <form id="month-form">
        <label>Abrechnungsmonat<input name="month" type="month" required value="${esc(state.next_month)}"></label>
        <label>Abgelesen am<input name="reading_date" type="date" value="${today}"></label>
        <label>Zählerstand Hausstrom<input name="grid_reading" type="number" step="any" inputmode="decimal" required></label>
        <label>Zählerstand Einspeisung<input name="feed_reading" type="number" step="any" inputmode="decimal" required></label>
        ${hasHeat ? '<label>Zählerstand Wärmestrom<input name="heat_reading" type="number" step="any" inputmode="decimal"></label>' : ""}
        <label>PV-Ertrag (kWh)<input name="pv_yield" type="number" step="any" inputmode="decimal" required></label>
        <label>Batterie geladen (kWh)<input name="battery_charged" type="number" step="any" inputmode="decimal"></label>
        <label>Batterie entladen (kWh)<input name="battery_discharged" type="number" step="any" inputmode="decimal"></label>
        <div class="actions"><button class="primary" type="submit">Prüfen</button></div>
      </form>
      <p class="muted">Zählerstand eintragen, nicht die Differenz. Gespeichert wird erst nach der Prüfung.</p>
      <div id="month-confirm"></div>
    </div>
    <h2>Monatswerte</h2>
    <div class="scroll"><table>
      <thead><tr>
        <th>Monat</th><th>PV-Ertrag</th><th>Einspeisung</th><th>Eigennutzung</th><th>Netzbezug</th>
        <th>Verbrauch</th><th>Autarkie</th><th>Eigenverbr.</th><th>Batterie</th><th>Arbeitspreis</th>
        <th>Erlös</th><th>kumuliert</th><th>Amortisation</th><th>Effektivpreis</th><th></th>
      </tr></thead>
      <tbody>${rows
        .map((m) =>
          m.baseline
            ? `<tr><td>${monthLabel(m.month)}</td><td colspan="13" class="text muted">Startwert der Zähler (${num(m.grid_reading)} / ${num(m.feed_reading)})</td><td><button class="link" data-edit-month="${m.month}">ändern</button></td></tr>`
            : `<tr>
          <td>${monthLabel(m.month)}</td><td>${num(m.pv_yield)}</td><td>${num(m.feed_kwh)}</td>
          <td class="${m.self_use < 0 ? "neg" : ""}">${num(m.self_use)}</td><td>${num(m.grid_kwh + m.heat_kwh)}</td>
          <td>${num(m.total_consumption)}</td><td>${pct(m.autarky)}</td><td>${pct(m.own_consumption_quota)}</td>
          <td>${pct(m.battery_efficiency, 0)}</td><td>${m.price == null ? "–" : nf(4).format(m.price)}</td>
          <td>${eur(m.revenue)}</td><td>${eur(m.revenue_cum)}</td><td>${pct(m.amortisation)}</td>
          <td>${m.effective_price == null ? "–" : nf(4).format(m.effective_price)}</td>
          <td><button class="link" data-edit-month="${m.month}">ändern</button></td></tr>`
        )
        .join("")}</tbody>
    </table></div>`;

  const form = $("#month-form");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    run(async () => {
      const data = formData(form);
      const month = data.month;
      delete data.month;
      const result = await api("POST", `api/months/${month}/check`, data);
      pendingMonth = { month, data };
      renderConfirm(result);
    });
  });
  el.querySelectorAll("[data-edit-month]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const m = state.months.find((x) => x.month === btn.dataset.editMonth);
      for (const key of ["month", "reading_date", "grid_reading", "feed_reading", "heat_reading", "pv_yield", "battery_charged", "battery_discharged"]) {
        if (form.elements[key]) form.elements[key].value = m[key] ?? "";
      }
      $("#month-confirm").innerHTML = "";
      form.scrollIntoView({ behavior: "smooth" });
    })
  );
}

function renderConfirm(result) {
  const m = result.month;
  const bad = result.checks.filter((c) => c.ok === false).length;
  const exists = state.months.some((x) => x.month === m.month);
  $("#month-confirm").innerHTML = `
    <h2>${monthLabel(m.month)} bestätigen</h2>
    <div class="tiles">
      ${tile("Zählerstand Hausstrom", num(m.grid_reading, 0), m.baseline ? "Startwert" : `Bezug ${num(m.grid_kwh)} kWh`)}
      ${tile("Zählerstand Einspeisung", num(m.feed_reading, 0), m.baseline ? "Startwert" : `Einspeisung ${num(m.feed_kwh)} kWh`)}
      ${tile("PV-Ertrag", num(m.pv_yield) + " kWh", `selbst genutzt ${num(m.self_use)} kWh`)}
      ${tile("Erlös", eur(m.revenue), `Autarkie ${pct(m.autarky)}`)}
    </div>
    <div class="card">${checksHtml(result.checks)}</div>
    <p class="actions">
      <button class="primary" id="month-save">${bad ? `Trotz ${bad} Warnung${bad > 1 ? "en" : ""} speichern` : "Speichern"}</button>
      ${exists ? '<button class="secondary" id="month-delete">Monat löschen</button>' : ""}
    </p>`;
  $("#month-save").addEventListener("click", () =>
    run(async () => {
      state = await api("PUT", `api/months/${pendingMonth.month}`, pendingMonth.data);
      pendingMonth = null;
      render();
    })
  );
  const del = $("#month-delete");
  if (del)
    del.addEventListener("click", () =>
      run(async () => {
        if (!confirm(`Monat ${monthLabel(m.month)} wirklich löschen?`)) return;
        state = await api("DELETE", `api/months/${m.month}`);
        render();
      })
    );
}

function renderTariffs() {
  const el = $("#tariffs");
  const t = editing.tariff || {};
  const mode = state.settings.tariff_mode;
  el.innerHTML = `
    <h2>Tarife</h2>
    <div class="scroll"><table>
      <thead><tr><th>gilt ab Monat</th><th>Art</th><th>Vertragsbeginn</th><th>Arbeitspreis €/kWh</th><th>Grundpreis €/Jahr</th><th class="text">Anbieter / Notiz</th><th></th></tr></thead>
      <tbody>${state.tariffs
        .map(
          (x) => `<tr><td>${monthLabel(x.valid_from.slice(0, 7))}</td><td>${KINDS[x.kind]}</td><td>${dateLabel(x.starts_on)}</td>
          <td>${nf(4).format(x.energy_price)}</td><td>${num(x.base_price_year, 2)}</td>
          <td class="text">${esc(x.provider || x.note || "")}</td>
          <td><button class="link" data-edit-tariff="${x.id}">ändern</button><button class="link danger" data-del-tariff="${x.id}">löschen</button></td></tr>`
        )
        .join("")}</tbody>
    </table></div>
    <h2>${t.id ? "Tarif ändern" : "Neuer Tarif"}</h2>
    <div class="card"><form id="tariff-form">
      <label>Art<select name="kind">${Object.entries(KINDS)
        .map(([k, v]) => `<option value="${k}" ${t.kind === k ? "selected" : ""}>${v}</option>`)
        .join("")}</select></label>
      <label>gilt ab Abrechnungsmonat<input name="valid_from" type="date" required value="${esc(t.valid_from || "")}"></label>
      <label>Vertragsbeginn (tagesgenau)<input name="starts_on" type="date" value="${esc(t.starts_on || "")}"></label>
      <label>Arbeitspreis brutto €/kWh<input name="energy_price" type="number" step="any" inputmode="decimal" required value="${t.energy_price ?? ""}"></label>
      <label>Grundpreis brutto €/Jahr<input name="base_price_year" type="number" step="any" inputmode="decimal" value="${t.base_price_year ?? ""}"></label>
      <label>Anbieter<input name="provider" value="${esc(t.provider || "")}"></label>
      <label>Notiz<input name="note" value="${esc(t.note || "")}"></label>
      <label>Vertragsende<input name="contract_end" type="date" value="${esc(t.contract_end || "")}"></label>
      <label>Preisgarantie bis<input name="price_guarantee_until" type="date" value="${esc(t.price_guarantee_until || "")}"></label>
      <div class="actions"><button class="primary" type="submit">Speichern</button>${t.id ? '<button class="secondary" type="button" id="tariff-cancel">Abbrechen</button>' : ""}</div>
    </form></div>
    <h2>Tarifwechsel mitten im Monat</h2>
    <div class="card"><form id="mode-form">
      <label>Bewertung<select name="tariff_mode">
        <option value="daily" ${mode === "daily" ? "selected" : ""}>tagesgenau nach Vertragsbeginn</option>
        <option value="monthly" ${mode === "monthly" ? "selected" : ""}>monatsweise wie in der Excel</option>
      </select></label>
    </form><p class="muted">Tagesgenau gewichtet den Monat des Wechsels nach den Tagen je Tarif. Monatsweise liefert exakt die Zahlen der Excel.</p></div>
    <h2>Tarifvergleich</h2>
    <div class="card"><form id="compare-form">
      <label>Arbeitspreis €/kWh<input name="energy_price" type="number" step="any" inputmode="decimal" required></label>
      <label>Grundpreis €/Jahr<input name="base_price_year" type="number" step="any" inputmode="decimal" required></label>
      <div class="actions"><button class="primary" type="submit">Vergleichen</button></div>
    </form><div id="compare-result"></div></div>`;

  $("#tariff-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    run(async () => {
      const data = formData(ev.target);
      state = t.id ? await api("PUT", `api/tariffs/${t.id}`, data) : await api("POST", "api/tariffs", data);
      editing.tariff = null;
      render();
    });
  });
  const cancel = $("#tariff-cancel");
  if (cancel) cancel.addEventListener("click", () => { editing.tariff = null; renderTariffs(); });
  el.querySelectorAll("[data-edit-tariff]").forEach((b) =>
    b.addEventListener("click", () => {
      editing.tariff = state.tariffs.find((x) => x.id === Number(b.dataset.editTariff));
      renderTariffs();
      $("#tariff-form").scrollIntoView({ behavior: "smooth" });
    })
  );
  el.querySelectorAll("[data-del-tariff]").forEach((b) =>
    b.addEventListener("click", () =>
      run(async () => {
        if (!confirm("Tarif wirklich löschen? Alle Monate werden neu bewertet.")) return;
        state = await api("DELETE", `api/tariffs/${b.dataset.delTariff}`);
        render();
      })
    )
  );
  $("#mode-form").addEventListener("change", (ev) =>
    run(async () => {
      state = await api("PUT", "api/settings", { tariff_mode: ev.target.value });
      render();
    })
  );
  $("#compare-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    run(async () => {
      const r = await api("POST", "api/tariffs/compare", formData(ev.target));
      const diff = r.actual_cost == null ? null : r.alternative_cost - r.actual_cost;
      $("#compare-result").innerHTML = `<div class="tiles" style="margin-top:12px">
        ${tile("Netzbezug", num(r.grid_kwh) + " kWh", `letzte ${r.months} Monate`)}
        ${tile("tatsächlich gezahlt", eur(r.actual_cost))}
        ${tile("mit diesem Tarif", eur(r.alternative_cost), diff == null ? "" : (diff > 0 ? "teurer um " : "günstiger um ") + eur(Math.abs(diff)))}
        ${tile("Gleichstand bei", r.break_even_kwh == null ? "–" : num(r.break_even_kwh) + " kWh/Jahr", "gegen den aktuellen Tarif")}
      </div>`;
    });
  });
}

function renderInvestments() {
  const el = $("#investments");
  const i = editing.investment || {};
  el.innerHTML = `
    <h2>Investitionen: ${eur(state.summary.invest_total)}</h2>
    <div class="scroll"><table>
      <thead><tr><th>Datum</th><th>Anzahl</th><th class="text">Posten</th><th>Betrag</th><th></th></tr></thead>
      <tbody>${state.investments
        .map(
          (x) => `<tr><td>${dateLabel(x.date)}</td><td>${num(x.quantity)}</td><td class="text">${esc(x.label)}</td>
          <td class="${x.amount < 0 ? "neg" : ""}">${eur(x.amount)}</td>
          <td><button class="link" data-edit-inv="${x.id}">ändern</button><button class="link danger" data-del-inv="${x.id}">löschen</button></td></tr>`
        )
        .join("")}</tbody>
    </table></div>
    <p class="muted">Ein Posten ohne Datum zählt von Anfang an. Mit Datum verändert er die Amortisation erst ab diesem Monat. Verkäufe als negativen Betrag eintragen.</p>
    <h2>${i.id ? "Posten ändern" : "Neuer Posten"}</h2>
    <div class="card"><form id="inv-form">
      <label>Datum<input name="date" type="date" value="${esc(i.date || "")}"></label>
      <label>Anzahl<input name="quantity" type="number" step="any" inputmode="decimal" value="${i.quantity ?? ""}"></label>
      <label>Posten<input name="label" required value="${esc(i.label || "")}"></label>
      <label>Betrag €<input name="amount" type="number" step="any" inputmode="decimal" required value="${i.amount ?? ""}"></label>
      <label>Kategorie<input name="category" value="${esc(i.category || "")}"></label>
      <div class="actions"><button class="primary" type="submit">Speichern</button>${i.id ? '<button class="secondary" type="button" id="inv-cancel">Abbrechen</button>' : ""}</div>
    </form></div>`;
  $("#inv-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    run(async () => {
      const data = formData(ev.target);
      state = i.id ? await api("PUT", `api/investments/${i.id}`, data) : await api("POST", "api/investments", data);
      editing.investment = null;
      render();
    });
  });
  const cancel = $("#inv-cancel");
  if (cancel) cancel.addEventListener("click", () => { editing.investment = null; renderInvestments(); });
  el.querySelectorAll("[data-edit-inv]").forEach((b) =>
    b.addEventListener("click", () => {
      editing.investment = state.investments.find((x) => x.id === Number(b.dataset.editInv));
      renderInvestments();
      $("#inv-form").scrollIntoView({ behavior: "smooth" });
    })
  );
  el.querySelectorAll("[data-del-inv]").forEach((b) =>
    b.addEventListener("click", () =>
      run(async () => {
        if (!confirm("Posten wirklich löschen?")) return;
        state = await api("DELETE", `api/investments/${b.dataset.delInv}`);
        render();
      })
    )
  );
}

function renderData() {
  const el = $("#data");
  const has = state.months.length > 0;
  el.innerHTML = `
    <h2>Excel-Historie importieren</h2>
    <div class="card">
      <p>Liest Monatswerte, Investitionen und Tarife aus der bisherigen Arbeitsmappe. Übernommen werden nur die eingetragenen Werte, alles Berechnete wird neu gerechnet.</p>
      ${has ? `<p class="neg">Es sind bereits ${state.months.length} Monate vorhanden. Ein Import ersetzt alle Monate, Tarife und Investitionen.</p>` : ""}
      <form id="import-form">
        <label>Arbeitsmappe (.xlsx)<input name="file" type="file" accept=".xlsx" required></label>
        <div class="actions"><button class="primary" type="submit">${has ? "Alles ersetzen und importieren" : "Importieren"}</button></div>
      </form>
      <div id="import-result"></div>
    </div>`;
  $("#import-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    run(async () => {
      const file = ev.target.elements.file.files[0];
      if (has && !confirm("Alle vorhandenen Monate, Tarife und Investitionen ersetzen?")) return;
      const result = await api("POST", has ? "api/import?replace=1" : "api/import", await file.arrayBuffer());
      state = result.state;
      render();
      $("#import-result").innerHTML = `<p>Importiert: ${result.imported.months} Monate, ${result.imported.investments} Investitionsposten, ${result.imported.tariffs} Tarifzeilen.</p>`;
    });
  });
}

function render() {
  renderOverview();
  renderMonths();
  renderTariffs();
  renderInvestments();
  renderData();
}

document.querySelectorAll("#tabs button").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== btn.dataset.tab));
  })
);

run(async () => {
  state = await api("GET", "api/state");
  render();
});
