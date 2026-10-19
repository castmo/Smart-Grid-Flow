/*
 * Smart Grid Flow – Lovelace-kort (svenska)
 *
 * Visar värmepump, varmvattenberedare, elpriser (nu och kommande),
 * energiförbrukning per stor förbrukare, effektavgift och modellens status.
 * Registreras automatiskt av integrationen. Lägg till på en dashboard med:
 *
 *   type: custom:smart-grid-flow-card
 *
 * Valfritt: `entity: sensor.<översiktssensor>` om automatisk sökning inte räcker.
 * Nya förbrukare (sol, batteri, elbilsladdare) ritas automatiskt när integrationen
 * rapporterar dem under `consumers`.
 */
const SGF_ICONS = { heatpump: "🌡️", boiler: "🚿", solar: "☀️", battery: "🔋", ev: "🚗" };
const SGF_MODES = [
  ["price", "Lägsta pris"],
  ["balanced", "Balanserad"],
  ["stable", "Stabil temp."],
];

class SmartGridFlowCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  getCardSize() {
    return 9;
  }

  static getStubConfig() {
    return {};
  }

  set hass(hass) {
    this._hass = hass;
    const st = this._find();
    const sig = st ? st.last_updated + JSON.stringify(st.state) : "none";
    if (sig === this._sig) return;
    this._sig = sig;
    this._render(st);
  }

  /* ---------- hjälpfunktioner ---------- */
  _find() {
    const h = this._hass;
    if (this._config.entity) return h.states[this._config.entity];
    const id = Object.keys(h.states).find(
      (k) => k.startsWith("sensor.") && h.states[k].attributes.sgf_overview
    );
    this._overviewId = id;
    return id ? h.states[id] : undefined;
  }

  _sibling(domain, key) {
    const h = this._hass;
    const id = this._config.entity || this._overviewId;
    const dev = h.entities && h.entities[id] && h.entities[id].device_id;
    if (!dev) return undefined;
    return Object.keys(h.entities).find(
      (e) =>
        e.startsWith(domain + ".") &&
        h.entities[e].device_id === dev &&
        h.entities[e].translation_key === key
    );
  }

  _call(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _fmt(v, d = 2) {
    return v === null || v === undefined || isNaN(v)
      ? "–"
      : Number(v).toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  /* ---------- rendering ---------- */
  _render(st) {
    if (!st) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px">Smart Grid Flow: hittar ingen översiktssensor.</div></ha-card>`;
      return;
    }
    const a = st.attributes;
    const price = a.price || {};
    const hp = a.hp || {};
    const consumers = a.consumers || [];
    const peak = a.peak || {};
    const model = a.model || {};
    const boiler = a.boiler || {};

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <ha-card>
        <div class="head">
          <div class="title">⚡ Smart Grid Flow</div>
          <div class="chip ${price.level || ""}">
            ${this._fmt(price.total)} kr/kWh · ${price.level || "–"}
          </div>
        </div>
        ${this._flow(hp, boiler, consumers, a.flow)}
        ${this._controls(hp)}
        <h3>Elpris – ${price.tomorrow_available ? "idag & imorgon" : "idag"}</h3>
        ${this._chart(a.prices || [], price, hp.plan || [])}
        <div class="legend">
          <span><i class="dot billig"></i>Billig</span>
          <span><i class="dot normal"></i>Normal</span>
          <span><i class="dot dyr"></i>Dyr</span>
          <span><i class="line"></i>Planerat börvärde</span>
        </div>
        <h3>Bästa tid att köra stora förbrukare</h3>
        ${this._suit(a.suitability || {})}
        <h3>Förbrukning idag</h3>
        ${this._consumption(consumers)}
        <h3>Effektavgift (${peak.month || "–"})</h3>
        ${this._peak(peak)}
        <h3>Självlärande modell</h3>
        ${this._model(model, hp)}
      </ha-card>`;
    this._bind();
  }

  _flow(hp, boiler, consumers, f) {
    f = f || {};
    const W = 420, H = 335;
    const hub = { x: 210, y: 150 };
    const has = (k) => f[k] !== null && f[k] !== undefined;
    const fmt = (v) => this._fmt(Math.abs(v || 0), 2) + " kW";
    // Källor/lagring (övre raden) och förbrukare (nedre raden).
    const top = [];
    if (has("solar")) top.push({ k: "solar", ico: "☀️", name: "Solceller", kw: f.solar, dir: "in" });
    top.push({ k: "grid", ico: "🔌", name: "Elnät", kw: f.grid, dir: f.grid >= 0 ? "in" : "out",
      sub: f.grid >= 0 ? "köper" : "säljer" });
    if (has("battery")) top.push({ k: "battery", ico: "🔋", name: "Batteri", kw: f.battery,
      dir: f.battery > 0 ? "out" : "in", sub: (f.battery > 0.05 ? "laddar" : f.battery < -0.05 ? "laddar ur" : "vilar") +
      (has("soc") ? ` · ${this._fmt(f.soc, 0)}%` : "") });
    const bot = [];
    let sub = "";
    if (hp.indoor != null) sub = `${this._fmt(hp.indoor, 1)}° → ${this._fmt(hp.setpoint, 1)}°`;
    bot.push({ k: "heatpump", ico: "🌡️", name: "Värmepump", kw: f.heatpump, sub });
    bot.push({ k: "boiler", ico: "🚿", name: "Beredare", kw: f.boiler,
      sub: boiler.temp != null ? `${this._fmt(boiler.temp, 0)}°C` : boiler.on ? "på" : "" });
    if (has("ev")) bot.push({ k: "ev", ico: "🚗", name: "Elbil", kw: f.ev });
    bot.push({ k: "other", ico: "🏠", name: "Övrigt", kw: f.other });
    const place = (arr, y) => arr.map((n, i) => ({ ...n, x: (W / (arr.length + 1)) * (i + 1), y }));
    const T = place(top, 62), B = place(bot, 262);
    const dur = (kw) => Math.max(0.5, Math.min(4, 2.4 / Math.max(Math.abs(kw), 0.05))).toFixed(2);
    // Banan ritas alltid i flödesriktningen så att animationen följer strömmen.
    const wire = (from, to, kw, cls) => {
      const act = Math.abs(kw) > 0.05;
      const my = (from.y + to.y) / 2;
      return `<path d="M${from.x},${from.y} C${from.x},${my} ${to.x},${my} ${to.x},${to.y}"
        class="wire ${act ? "active " + cls : ""}" style="animation-duration:${dur(kw)}s"/>`;
    };
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="flow">`;
    T.forEach((n) => {
      const hubTop = { x: hub.x, y: hub.y - 26 }, nb = { x: n.x, y: n.y + 26 };
      svg += n.dir === "in" ? wire(nb, hubTop, n.kw, n.k) : wire(hubTop, nb, n.kw, n.k);
    });
    B.forEach((n) => {
      svg += wire({ x: hub.x, y: hub.y + 26 }, { x: n.x, y: n.y - 26 }, n.kw, n.k);
    });
    svg += `<circle cx="${hub.x}" cy="${hub.y}" r="26" class="node hub"/>
      <text x="${hub.x}" y="${hub.y + 2}" class="ico">🏠</text>
      <text x="${hub.x}" y="${hub.y + 16}" class="sub">${fmt(f.load)}</text>`;
    [...T, ...B].forEach((n) => {
      const on = Math.abs(n.kw || 0) > 0.05;
      const up = n.y < hub.y;
      const ly = up ? n.y - 42 : n.y + 42;
      svg += `<g><circle cx="${n.x}" cy="${n.y}" r="24" class="node ${on ? "on " + n.k : ""}"/>
        <text x="${n.x}" y="${n.y + 7}" class="ico">${n.ico}</text>
        <text x="${n.x}" y="${ly}" class="lbl">${n.name}</text>
        <text x="${n.x}" y="${up ? n.y - 30 : ly + 12}" class="sub">${fmt(n.kw)}${up && n.sub ? " · " + n.sub : ""}</text>
        ${!up && n.sub ? `<text x="${n.x}" y="${ly + 24}" class="sub">${n.sub}</text>` : ""}</g>`;
    });
    return svg + `</svg>`;
  }

  _controls(hp) {
    const modes = SGF_MODES.map(
      ([k, l]) => `<button data-mode="${k}" class="${hp.mode === k ? "sel" : ""}">${l}</button>`
    ).join("");
    return `<div class="controls">
      <div class="modes">${modes}</div>
      <div class="row">
        <label class="sw"><input type="checkbox" id="hpctl" ${hp.control ? "checked" : ""}/> Styr värmepump</label>
        <div class="target">Önskad temp
          <button id="tdn">−</button><b>${this._fmt(hp.target, 1)}°</b><button id="tup">+</button>
        </div>
      </div>
      <div class="muted">Planerat börvärde nu: <b>${this._fmt(hp.plan_setpoint, 1)}°</b> ·
        Beräknad besparing 36 h: <b>${this._fmt(hp.plan_savings, 2)} kr</b></div>
    </div>`;
  }

  _chart(prices, price, plan) {
    if (!prices.length) return `<div class="muted">Inga priser hämtade ännu.</div>`;
    const W = 420, H = 150, pl = 4, pr = 26, pt = 8, pb = 18;
    const n = prices.length;
    const bw = (W - pl - pr) / n;
    const max = Math.max(...prices.map((p) => p.total), 0.5);
    const now = Date.now();
    const lv = price.levels || { low: 0, high: 9 };
    const planMap = {};
    plan.forEach((p) => (planMap[new Date(p.start).getTime()] = p.setpoint));
    let bars = "", pts = [], xl = "";
    prices.forEach((p, i) => {
      const t = new Date(p.start).getTime();
      const h = ((p.total / max) * (H - pt - pb));
      const x = pl + i * bw;
      const cls = p.total <= lv.low ? "billig" : p.total >= lv.high ? "dyr" : "normal";
      const cur = t <= now && now < t + 3600000;
      bars += `<rect x="${x + 0.5}" y="${H - pb - h}" width="${bw - 1}" height="${h}" class="bar ${cls} ${t + 3600000 <= now ? "past" : ""} ${cur ? "cur" : ""}">
        <title>${new Date(t).toLocaleString("sv-SE", { weekday: "short", hour: "2-digit", minute: "2-digit" })}: ${this._fmt(p.total)} kr/kWh (spot ${this._fmt(p.spot)})</title></rect>`;
      if (planMap[t] !== undefined) {
        const y = pt + (1 - (planMap[t] - 17) / 9) * (H - pt - pb);
        pts.push(`${x + bw / 2},${y}`);
      }
      if (new Date(t).getHours() % 6 === 0)
        xl += `<text x="${x}" y="${H - 4}" class="ax">${String(new Date(t).getHours()).padStart(2, "0")}</text>`;
    });
    const nowX = pl + ((now - new Date(prices[0].start).getTime()) / 3600000) * bw;
    return `<svg viewBox="0 0 ${W} ${H}" class="chart">${bars}
      ${pts.length > 1 ? `<polyline points="${pts.join(" ")}" class="plan"/>` : ""}
      <line x1="${nowX}" x2="${nowX}" y1="${pt}" y2="${H - pb}" class="now"/>
      ${xl}
      <text x="${W - pr + 3}" y="${pt + 8}" class="ax">${this._fmt(max, 1)}</text>
      <text x="${W - pr + 3}" y="${H - pb}" class="ax">0</text></svg>`;
  }

  _hh(iso) {
    return String(new Date(iso).getHours()).padStart(2, "0");
  }

  _strip(items, label, icon, best, tip) {
    if (!items.length) return "";
    const W = 420, pl = 4, pr = 4, H = 54;
    const n = items.length, cw = (W - pl - pr) / n;
    const now = Date.now();
    const t0 = new Date(items[0].start).getTime();
    let cells = "", ax = "";
    items.forEach((it, i) => {
      const t = new Date(it.start).getTime();
      const x = pl + i * cw;
      const past = t + 3600000 <= now;
      cells += `<rect x="${x + 0.5}" y="4" width="${cw - 1}" height="24" rx="2"
        fill="hsl(${Math.round(it.score * 1.2)},62%,46%)" opacity="${past ? 0.3 : 1}"><title>${tip(it)}</title></rect>`;
      if (new Date(t).getHours() % 3 === 0)
        ax += `<text x="${x}" y="${H - 3}" class="ax">${this._hh(it.start)}</text>`;
    });
    const nx = pl + ((now - t0) / 3600000) * cw;
    const bst = best
      ? `Bäst: <b>${this._hh(best.start)}–${this._hh(best.end)}</b>`
      : "";
    return `<div class="srow"><span>${icon} ${label}</span><span class="muted">${bst}</span></div>
      <svg viewBox="0 0 ${W} ${H}" class="strip">${cells}
        <line x1="${nx}" x2="${nx}" y1="0" y2="32" class="now"/>
        <text x="${nx}" y="${H - 16}" class="ax" style="text-anchor:middle;fill:var(--primary-text-color)">nu</text>${ax}</svg>`;
  }

  _suit(s) {
    if (!s.ev) return `<div class="muted">Väntar på elpriser…</div>`;
    const ev = this._strip(s.ev, `Elbilsladdning (${this._fmt(s.ev_kw, 1)} kW)`, "🚗", s.best_ev_3h,
      (it) => `${this._hh(it.start)}:00 – ${this._fmt(it.cost)} kr/kWh inkl. ev. effekttopp · lämplighet ${it.score}%`);
    const sh = this._strip(s.shower, "Dusch", "🚿", s.best_shower,
      (it) => `Dusch ${this._hh(it.start)}:00 → beredaren värms ca kl ${this._hh(it.reheat)}:00 (${this._fmt(it.cost)} kr/kWh) · lämplighet ${it.score}%`);
    return `${ev}${sh}
      <div class="muted">Grönt = billigt, rött = dyrt. Duschens energi förbrukas när beredaren värmer upp efteråt
      (${s.shower_scheduled ? "enligt schemat för beredaren" : "ca " + s.shower_delay_h + " h efter duschen"}), så diagrammet visar priset vid uppvärmningen.</div>`;
  }

  _consumption(consumers) {
    if (!consumers.length) return `<div class="muted">Inga energisensorer konfigurerade.</div>`;
    const max = Math.max(...consumers.map((c) => c.kwh_today || 0), 0.1);
    return consumers
      .map(
        (c) => `<div class="cons">
        <div class="cname">${SGF_ICONS[c.key] || "⚡"} ${c.name}</div>
        <div class="cbar"><div style="width:${((c.kwh_today || 0) / max) * 100}%"></div></div>
        <div class="cval">${this._fmt(c.kwh_today)} kWh · ${this._fmt(c.cost_today)} kr</div></div>`
      )
      .join("");
  }

  _peak(p) {
    const top = (p.top || []).map((v) => `<span class="pk">${this._fmt(v)} kW</span>`).join("") || "<span class='muted'>Inga toppar registrerade (konfigurera huvudmätare)</span>";
    return `<div>${top}</div><div class="muted">Debiteras: <b>${this._fmt(p.billed_kw)} kW</b> × ${this._fmt(p.price_kr_kw, 0)} kr = <b>${this._fmt(p.cost, 0)} kr</b>.
      Håll timmedeleffekt under <b>${this._fmt(p.threshold)} kW</b> för att undvika högre avgift.</div>`;
  }

  _model(m, hp) {
    const pct = Math.round((m.confidence || 0) * 100);
    return `<div class="cbar"><div style="width:${pct}%"></div></div>
      <div class="muted">Säkerhet ${pct}% (${m.samples || 0} timmar inlärda) · husets tidskonstant ${this._fmt(m.time_constant_h, 0)} h ·
      temperaturfel ${this._fmt(m.thermal_error, 2)} °C/h · utetemp ${this._fmt(hp.outdoor, 1)}°C</div>`;
  }

  _bind() {
    const r = this.shadowRoot;
    r.querySelectorAll("[data-mode]").forEach((b) =>
      b.addEventListener("click", () => {
        const e = this._sibling("select", "mode");
        const label = SGF_MODES.find((m) => m[0] === b.dataset.mode)[1];
        const full = { price: "Lägsta pris", balanced: "Balanserad", stable: "Stabil temperatur" }[b.dataset.mode];
        if (e) this._call("select", "select_option", { entity_id: e, option: full || label });
      })
    );
    const ctl = r.getElementById("hpctl");
    if (ctl)
      ctl.addEventListener("change", () => {
        const e = this._sibling("switch", "hp_control");
        if (e) this._call("switch", ctl.checked ? "turn_on" : "turn_off", { entity_id: e });
      });
    const step = (d) => {
      const e = this._sibling("number", "target");
      if (!e) return;
      const cur = parseFloat(this._hass.states[e].state);
      this._call("number", "set_value", { entity_id: e, value: cur + d });
    };
    const up = r.getElementById("tup"), dn = r.getElementById("tdn");
    if (up) up.addEventListener("click", () => step(0.5));
    if (dn) dn.addEventListener("click", () => step(-0.5));
  }

  _css() {
    return `
    ha-card{display:block;padding:12px 16px 16px;--c-low:#2e9e5b;--c-mid:#e0a800;--c-high:#d64545;--c-acc:var(--primary-color)}
    .head{display:flex;justify-content:space-between;align-items:center}
    .title{font-size:1.2em;font-weight:600}
    h3{margin:16px 0 6px;font-size:.95em;font-weight:600;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.04em}
    .chip{padding:4px 10px;border-radius:14px;color:#fff;font-weight:600;background:var(--c-mid)}
    .chip.billig{background:var(--c-low)} .chip.dyr{background:var(--c-high)}
    svg{width:100%;height:auto;display:block}
    .flow .node{fill:var(--card-background-color);stroke:var(--divider-color);stroke-width:2}
    .flow .node.on{stroke:var(--c-acc)} .flow .hub{stroke:var(--c-acc)}
    .ico{font-size:20px;text-anchor:middle} .lbl{font-size:11px;text-anchor:middle;fill:var(--primary-text-color);font-weight:600}
    .sub{font-size:10px;text-anchor:middle;fill:var(--secondary-text-color)}
    .wire{fill:none;stroke:var(--divider-color);stroke-width:2}
    .wire.active{stroke:var(--c-acc);stroke-dasharray:6 6;animation:flow linear infinite}
    .wire.active.solar{stroke:#f2b01e} .wire.active.battery{stroke:var(--c-low)} .wire.active.grid{stroke:#4a90d9} .wire.active.ev{stroke:#9b59b6} .wire.active.boiler{stroke:#e67e22}
    .flow .node.on.solar{stroke:#f2b01e} .flow .node.on.battery{stroke:var(--c-low)} .flow .node.on.grid{stroke:#4a90d9}
    @keyframes flow{to{stroke-dashoffset:-12}}
    .bar{fill:var(--c-mid)} .bar.billig{fill:var(--c-low)} .bar.dyr{fill:var(--c-high)}
    .bar.past{opacity:.35} .bar.cur{stroke:var(--primary-text-color);stroke-width:1.5}
    .plan{fill:none;stroke:var(--c-acc);stroke-width:2;stroke-linejoin:round}
    .now{stroke:var(--primary-text-color);stroke-dasharray:3 3;opacity:.7}
    .ax{font-size:9px;fill:var(--secondary-text-color)}
    .legend{display:flex;gap:12px;flex-wrap:wrap;font-size:.8em;color:var(--secondary-text-color);margin-top:4px}
    .dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;background:var(--c-mid)}
    .dot.billig{background:var(--c-low)} .dot.dyr{background:var(--c-high)}
    .line{display:inline-block;width:14px;height:0;border-top:2px solid var(--c-acc);margin-right:4px;vertical-align:middle}
    .srow{display:flex;justify-content:space-between;margin-top:6px;font-size:.9em}
    .strip{margin-bottom:2px}
    .controls{margin-top:8px}
    .modes{display:flex;gap:6px} .modes button{flex:1}
    button{border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);border-radius:8px;padding:6px 10px;cursor:pointer}
    button.sel{background:var(--c-acc);color:#fff;border-color:var(--c-acc)}
    .row{display:flex;justify-content:space-between;align-items:center;margin:8px 0;gap:8px;flex-wrap:wrap}
    .target button{width:30px;margin:0 6px}
    .muted{color:var(--secondary-text-color);font-size:.85em;margin-top:4px}
    .cons{display:grid;grid-template-columns:150px 1fr 150px;gap:8px;align-items:center;margin:4px 0;font-size:.9em}
    .cbar{height:8px;border-radius:4px;background:var(--divider-color);overflow:hidden}
    .cbar div{height:100%;background:var(--c-acc)}
    .cval{text-align:right}
    .pk{display:inline-block;margin:0 6px 4px 0;padding:3px 9px;border-radius:12px;background:var(--secondary-background-color);font-weight:600}
    `;
  }
}

customElements.define("smart-grid-flow-card", SmartGridFlowCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "smart-grid-flow-card",
  name: "Smart Grid Flow",
  description: "Värmepump, varmvatten, elpriser, förbrukning och effektavgift",
});
