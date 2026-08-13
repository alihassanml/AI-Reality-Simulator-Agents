/* AI Reality Simulator — dashboard client */

const SVG_NS = "http://www.w3.org/2000/svg";
const CENTRE = 230;
const ORBIT = 150;
const LABEL_ORBIT = 186;

/* Clockwise from the top, the ring order traces the real escalation path:
   the complaint enters at the customer and travels customer → sales → CEO →
   developer, with the investor closing the loop back to the top. */
const RING_ORDER = [
  { name: "customer",  short: "Customer", code: "CUS" },
  { name: "sales",     short: "Sales",    code: "SLS" },
  { name: "ceo",       short: "CEO",      code: "CEO" },
  { name: "developer", short: "Dev",      code: "DEV" },
  { name: "investor",  short: "Investor", code: "INV" },
];

const CODES = Object.fromEntries(RING_ORDER.map((r) => [r.name, r.code]));

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

const METRICS = [
  { key: "revenue",             label: "Revenue",            kind: "currency" },
  { key: "satisfaction",        label: "Satisfaction",       kind: "pct" },
  { key: "reputation",          label: "Reputation",         kind: "pct" },
  { key: "investor_confidence", label: "Investor confidence", kind: "pct" },
  { key: "active_issues",       label: "Active issues",      kind: "count" },
  { key: "pending_tasks",       label: "Pending tasks",      kind: "count" },
];

const IMPACT_LABELS = {
  satisfaction: "satisfaction",
  reputation: "reputation",
  investor_confidence: "investor confidence",
  active_issues: "open issues",
  pending_tasks: "pending tasks",
};

const STATUS_LABELS = {
  idle: "Idle", running: "Running", paused: "Paused",
  completed: "Complete", failed: "Failed",
};

function polar(index, radius) {
  const angle = (-90 + index * (360 / RING_ORDER.length)) * (Math.PI / 180);
  return { x: CENTRE + radius * Math.cos(angle), y: CENTRE + radius * Math.sin(angle) };
}

function simulator() {
  return {
    /* ------------------------------------------------------------- state */
    status: "idle",
    agents: [],
    events: [],
    selectedEvent: "customer_complaint",
    event: null,
    currentStep: 0,
    totalSteps: 0,
    currentActor: null,
    agentState: {},
    company: {},
    lastDeltas: {},
    timeline: [],
    turns: [],
    tab: "story",
    customPrompt: "",
    lastMessage: null,
    messageCount: 0,
    inspected: null,
    memory: { long_term: [], short_term: { inbox: [], notes: [] } },
    socket: null,
    _seq: 0,

    /* ------------------------------------------------------------- setup */
    async init() {
      const res = await fetch("/api/state");
      const data = await res.json();
      this.agents = data.agents;
      this.events = data.events;
      this.company = data.company;
      this.applySnapshot(data.simulation);
      if (this.events.length) this.selectedEvent = this.events[0].key;
      data.history.forEach((e) => this.handle(e, true));
      this.$nextTick(() => this.buildRing());
      this.connect();
    },

    connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      this.socket = new WebSocket(`${proto}://${location.host}/ws`);
      this.socket.onmessage = (e) => this.handle(JSON.parse(e.data));
      this.socket.onclose = () => setTimeout(() => this.connect(), 1500);
    },

    /* ---------------------------------------------------------- geometry */
    /* The ring is built with the DOM API rather than Alpine's x-for: a
       <template> written inside <svg> is parsed as an SVG element, not an
       HTMLTemplateElement, so x-for silently renders nothing there. */
    buildRing() {
      const chordGroup = document.getElementById("chords");
      const nodeGroup = document.getElementById("nodes");
      if (!chordGroup || !nodeGroup) return;
      chordGroup.replaceChildren();
      nodeGroup.replaceChildren();

      for (let i = 0; i < RING_ORDER.length; i++) {
        for (let j = i + 1; j < RING_ORDER.length; j++) {
          const a = polar(i, ORBIT), b = polar(j, ORBIT);
          chordGroup.appendChild(svgEl("line", {
            class: "ring__chord", x1: a.x, y1: a.y, x2: b.x, y2: b.y,
          }));
        }
      }

      RING_ORDER.forEach((entry, i) => {
        const p = polar(i, ORBIT);
        const l = polar(i, LABEL_ORBIT);
        const agent = this.agents.find((a) => a.name === entry.name);
        const group = svgEl("g", { class: "ring__node", "data-status": "idle", id: `node-${entry.name}` });
        group.append(
          svgEl("circle", { class: "ring__pulse", cx: p.x, cy: p.y, r: 20 }),
          svgEl("circle", { class: "ring__node-ring", cx: p.x, cy: p.y, r: 20 }),
        );
        const initial = svgEl("text", { class: "ring__initial", x: p.x, y: p.y });
        initial.textContent = entry.code;

        /* Anchor each label on the side it sits: a centred label on a left or
           right node would run back over the node itself. */
        const dx = p.x - CENTRE;
        const sideways = Math.abs(dx) > 40;
        const label = svgEl("text", {
          class: "ring__label",
          x: sideways ? p.x + (dx > 0 ? 30 : -30) : p.x,
          y: sideways ? p.y + 4 : l.y + (p.y < CENTRE ? -4 : 10),
          "text-anchor": sideways ? (dx > 0 ? "start" : "end") : "middle",
        });
        label.textContent = agent ? agent.label.replace(" Agent", "") : entry.short;
        group.append(initial, label);
        nodeGroup.appendChild(group);
      });

      this.paintRing();
    },

    /* Alpine cannot bind SVG attributes reactively here, so status is painted
       explicitly whenever it changes. */
    paintRing() {
      RING_ORDER.forEach((entry) => {
        const group = document.getElementById(`node-${entry.name}`);
        if (group) group.setAttribute("data-status", this.statusOf(entry.name));
      });
    },

    /* ------------------------------------------------------- derivations */
    get statusLabel() { return STATUS_LABELS[this.status] || this.status; },
    get isBusy() { return this.status === "running" || this.status === "paused"; },
    get progress() { return this.totalSteps ? (this.currentStep / this.totalSteps) * 100 : 0; },
    get stepLabel() { return this.totalSteps ? `${this.currentStep}/${this.totalSteps}` : "—"; },
    get activeCount() {
      return Object.values(this.agentState).filter((s) => s.status === "thinking" || s.status === "working").length;
    },
    get currentActorLabel() {
      const a = this.agents.find((x) => x.name === this.currentActor);
      return a ? a.label : null;
    },

    get metricCards() {
      return METRICS.map((m) => {
        const value = this.company[m.key] ?? 0;
        const delta = this.lastDeltas[m.key] || 0;
        let display = value;
        if (m.kind === "currency") display = "$" + (value / 1_000_000).toFixed(2) + "M";
        let pct = null, color = "var(--amber)";
        if (m.kind === "pct") {
          pct = Math.max(0, Math.min(100, value));
          display = value + "%";
          color = value >= 70 ? "#4ADE80" : value >= 45 ? "var(--amber)" : "var(--ember)";
        }
        return {
          key: m.key, label: m.label, display, pct, color, delta,
          flash: delta ? (delta > 0 ? "up" : "down") : null,
        };
      });
    },

    statusOf(name) { return (this.agentState[name] || {}).status || "idle"; },
    detailOf(name) { return (this.agentState[name] || {}).detail || "Waiting"; },
    codeOf(name) { return CODES[name] || "?"; },

    /* ---------------------------------------------------------- controls */
    async post(path) {
      const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" } });
      return res.json();
    },
    async trigger() {
      if (this.isBusy) return;
      const typed = this.customPrompt.trim();
      const res = await fetch("/api/simulation/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          typed ? { event: "custom", prompt: typed } : { event: this.selectedEvent }
        ),
      });
      const data = await res.json();
      if (!data.ok) {
        this.tab = "log";
        this.push("error", "system", data.error || "Could not start the simulation.");
      }
    },
    async pause() { await this.post("/api/simulation/pause"); },
    async resume() { await this.post("/api/simulation/resume"); },
    async reset() {
      await this.post("/api/simulation/reset");
      this.timeline = []; this.turns = []; this.lastMessage = null;
      this.messageCount = 0; this.lastDeltas = {}; this.event = null;
      this.currentStep = 0; this.totalSteps = 0; this.currentActor = null;
    },

    async openAgent(agent) {
      this.inspected = agent;
      this.memory = { long_term: [], short_term: { inbox: [], notes: [] } };
      const res = await fetch(`/api/agents/${agent.name}/memory`);
      const data = await res.json();
      this.memory = { long_term: data.long_term, short_term: data.short_term };
    },

    /* ------------------------------------------------------------ events */
    applySnapshot(sim) {
      if (!sim) return;
      this.status = sim.status;
      this.event = sim.event;
      this.currentStep = sim.current_step;
      this.totalSteps = sim.total_steps;
      this.currentActor = sim.current_actor;
      this.agentState = sim.agents || {};
      if (sim.company) this.company = sim.company;
      this.paintRing();
    },

    push(kind, actor, text, at) {
      this.timeline.push({
        id: ++this._seq,
        kind, actor: actor || "system", text,
        at: at || new Date().toLocaleTimeString("en-GB"),
      });
      if (this.timeline.length > 300) this.timeline.shift();
      this.$nextTick(() => {
        const el = this.$refs.timeline;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    /* Events arrive one at a time; a turn card is all of a step's events
       collected together. They always arrive in step order, so the open turn is
       simply the last one created. */
    get openTurn() { return this.turns.length ? this.turns[this.turns.length - 1] : null; },

    scrollFilm() {
      this.$nextTick(() => {
        const el = this.$refs.film;
        if (el) el.scrollTo({ left: el.scrollWidth, behavior: "smooth" });
      });
    },

    labelFor(name) {
      const a = this.agents.find((x) => x.name === name);
      return a ? a.label : name;
    },

    handle(e, replaying = false) {
      switch (e.kind) {
        case "snapshot":
          this.applySnapshot(e.simulation);
          break;

        case "simulation_status":
          this.applySnapshot(e);
          break;

        case "run_started":
          this.event = e.event;
          this.company = e.company;
          this.turns = [];
          this.tab = "story";
          this.lastMessage = null;
          this.messageCount = 0;
          this.push("system", "system", `Event triggered — ${e.event.title}`, e.at);
          break;

        case "step_started":
          if (this.openTurn) this.openTurn.live = false;
          this.turns.push({
            index: e.index, actor: e.actor, actor_label: e.actor_label, label: e.label,
            thought: "", tools: [], decision: "", reason: "", priority: "",
            message: null, impact: [], live: true,
          });
          this.scrollFilm();
          this.push("system", e.actor_label, `Step ${e.index} — ${e.label}`, e.at);
          break;

        case "agent_status":
          this.agentState[e.agent] = { status: e.status, detail: e.detail };
          this.paintRing();
          break;

        case "thought":
          if (this.openTurn) this.openTurn.thought = e.text;
          this.push("thought", this.labelFor(e.actor), e.text, e.at);
          break;

        case "tool_call":
          if (this.openTurn && !this.openTurn.tools.includes(e.tool)) {
            this.openTurn.tools.push(e.tool);
          }
          this.push("tool_call", this.labelFor(e.actor), `${e.tool}() — ${e.detail}`, e.at);
          break;

        case "message":
          if (this.openTurn) this.openTurn.message = e;
          this.lastMessage = e;
          this.messageCount++;
          this.push("message", e.from_label, `→ ${e.to_label}: ${e.subject}`, e.at);
          if (!replaying) this.flyPacket(e.from, e.to, e.priority);
          break;

        case "decision":
          if (this.openTurn) {
            Object.assign(this.openTurn, {
              decision: e.decision, reason: e.reason, priority: e.priority,
            });
          }
          this.push("decision", e.actor_label, `${e.decision.replaceAll("_", " ")} — ${e.reason}`, e.at);
          break;

        case "state_update":
          if (this.openTurn) {
            for (const [field, value] of Object.entries(e.delta)) {
              this.openTurn.impact.push({ label: IMPACT_LABELS[field] || field, value });
            }
          }
          this.company = e.company;
          this.lastDeltas = e.delta;
          this.push("state", this.labelFor(e.actor),
            Object.entries(e.delta).map(([k, v]) => `${k.replaceAll("_", " ")} ${v > 0 ? "+" : ""}${v}`).join(", "),
            e.at);
          if (!replaying) setTimeout(() => { this.lastDeltas = {}; }, 2600);
          break;

        case "memory_stored":
          this.push("memory", this.labelFor(e.agent), `remembered — ${e.content}`, e.at);
          break;

        case "run_completed":
          if (this.openTurn) this.openTurn.live = false;
          this.company = e.company;
          this.push("system", "system", "Simulation complete.", e.at);
          break;

        case "run_failed":
          if (this.openTurn) this.openTurn.live = false;
          this.tab = "log";
          this.push("error", "system", e.error, e.at);
          break;

        case "simulation_reset":
          this.timeline = []; this.turns = []; this.lastMessage = null;
          this.messageCount = 0; this.lastDeltas = {};
          break;
      }
    },

    /* ----------------------------------------------------- ring animation */
    flyPacket(from, to, priority) {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const group = document.getElementById("packets");
      if (!group) return;

      const fromIndex = RING_ORDER.findIndex((r) => r.name === from);
      const toIndex = RING_ORDER.findIndex((r) => r.name === to);
      if (fromIndex < 0 || toIndex < 0) return;

      const a = polar(fromIndex, ORBIT);
      const b = polar(toIndex, ORBIT);
      const critical = priority === "critical";

      const trail = document.createElementNS(SVG_NS, "line");
      trail.setAttribute("x1", a.x); trail.setAttribute("y1", a.y);
      trail.setAttribute("x2", b.x); trail.setAttribute("y2", b.y);
      trail.setAttribute("class", "packet__trail" + (critical ? " packet__trail--critical" : ""));
      group.appendChild(trail);

      const dot = document.createElementNS(SVG_NS, "circle");
      dot.setAttribute("cx", a.x); dot.setAttribute("cy", a.y); dot.setAttribute("r", 5.5);
      dot.setAttribute("class", "packet" + (critical ? " packet--critical" : ""));
      group.appendChild(dot);

      const travel = dot.animate(
        [{ transform: "translate(0px,0px)" }, { transform: `translate(${b.x - a.x}px, ${b.y - a.y}px)` }],
        { duration: 1000, easing: "cubic-bezier(.45,.05,.3,1)" }
      );
      trail.animate([{ opacity: 0 }, { opacity: .5 }, { opacity: 0 }], { duration: 1200, easing: "ease-out" });

      travel.onfinish = () => { dot.remove(); trail.remove(); };
      setTimeout(() => { dot.remove(); trail.remove(); }, 1400);
    },
  };
}

window.simulator = simulator;
