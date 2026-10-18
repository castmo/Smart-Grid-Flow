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
        ${this._flow(hp, boiler, consumers)}
        ${this._controls(hp)}
        <h3>Elpris – ${price.tomorrow_available ? "idag & imorgon" : "idag"}</h3>
        ${this._chart(a.prices || [], price, hp.plan || [])}
        <div class="legend">
          <span><i class="dot billig"></i>Billig</span>
          <span><i class="dot normal"></i>Normal</span>
          <span><i class="dot dyr"></i>Dyr</span>
          <span><i class="line"></i>Planerat börvärde</span>
        </div>
        <h3>Förbrukning idag</h3>
        ${this._consumption(consumers)}
        <h3>Effektavgift (${peak.month || "–"})</h3>
        ${this._peak(peak)}
        <h3>Självlärande modell</h3>
        ${this._model(model, hp)}
      </ha-card>`;
    this._bind();
  }

  _flow(hp, boiler, consumers) {
    const list = consumers.length
      ? consumers
      : [{ key: "heatpump", name: "Värmepump", power_kw: 0 }];
    const W = 420;
    const rowH = Math.max(70, 190 / list.length);
    const H = Math.max(190, rowH * list.length + 10);
    const hub = { x: 190, y: H / 2 };
    const grid = { x: 40, y: H / 2 };
    const total = list.reduce((s, c) => s + (c.power_kw || 0), 0);
    const dur = (kw) => Math.max(0.6, Math.min(5, 3 / Math.max(kw, 0.05))).toFixed(2);
    const line = (x1, y1, x2, y2, kw, cls) =>
      `<path d="M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}"
         class="wire ${kw > 0.05 ? "active " + cls : ""}" style="animation-duration:${dur(kw)}s"/>`;
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="flow">`;
    svg += line(grid.x + 24, grid.y, hub.x - 24, hub.y, total, "grid");
    svg += `<g><circle cx="${grid.x}" cy="${grid.y}" r="26" class="node"/>
            <text x="${grid.x}" y="${grid.y + 6}" class="ico">🔌</text>
            <text x="${grid.x}" y="${grid.y + 44}" class="lbl">Elnät</text>
            <text x="${grid.x}" y="${grid.y + 57}" class="sub">${this._fmt(total, 2)} kW</text></g>`;
    svg += `<g><circle cx="${hub.x}" cy="${hub.y}" r="24" class="node hub"/>
            <text x="${hub.x}" y="${hub.y + 6}" class="ico">🏠</text></g>`;
    list.forEach((c, i) => {
      const x = 340;
      const y = rowH * i + rowH / 2 + 5;
      const kw = c.power_kw || 0;
      let sub = `${this._fmt(kw, 2)} kW`;
      if (c.key === "heatpump" && hp.indoor != null)
        sub += ` · ${this._fmt(hp.indoor, 1)}° → ${this._fmt(hp.setpoint, 1)}°`;
      if (c.key === "boiler")
        sub += boiler.temp != null ? ` · ${this._fmt(boiler.temp, 0)}°C` : boiler.on ? " · på" : " · av";
      const isSource = c.key === "solar";
      svg += line(isSource ? x - 24 : hub.x + 24, isSource ? y : hub.y, isSource ? hub.x + 24 : x - 24, isSource ? hub.y : y, kw, c.key);
      svg += `<g><circle cx="${x}" cy="${y}" r="24" class="node ${kw > 0.05 ? "on" : ""}"/>
              <text x="${x}" y="${y + 6}" class="ico">${SGF_ICONS[c.key] || "⚡"}</text>
              <text x="${x}" y="${y + 40}" class="lbl">${c.name || c.key}</text>
              <text x="${x}" y="${y + 53}" class="sub">${sub}</text></g>`;
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
    ha-card{padding:12px 16px 16px;--c-low:#2e9e5b;--c-mid:#e0a800;--c-high:#d64545;--c-acc:var(--primary-color)}
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
    .wire.active.solar{stroke:var(--c-mid)} .wire.active.battery{stroke:var(--c-low)}
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
    .controls{margin-top:8px}
    .modes{display:flex;gap:6px} .modes button{flex:1}
    button{border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);border-radius:8px;padding:6px 10px;cursor:pointer}
    button.sel{background:var(--c-acc);color:#fff;border-color:var(--c-acc)}
    .row{display:flex;justify-content:space-between;align-items:center;margin:8px 0;gap:8px;flex-wrap:wrap}
    .target button{width:30px;margin:0 6px}
    .muted{color:var(--secondary-text-color);font-size:.85em;margin-top:4px}
    .cons{display:grid;grid-template-columns:130px 1fr 120px;gap:8px;align-items:center;margin:4px 0;font-size:.9em}
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
