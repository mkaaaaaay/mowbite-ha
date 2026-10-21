// the MowBite card: the mower the way the MowBite app shows it, in the app's own look.
// it comes with the integration, which also feeds it (mowbite/subscribe) and takes its buttons (mowbite/action)

const ACTION_IDS = {
  start: 'mower_logic:idle/start_mowing',
  pause: 'mower_logic:mowing/pause',
  continue: 'mower_logic:mowing/continue',
  home: 'mower_logic:mowing/abort_mowing',
  skip_area: 'mower_logic:mowing/skip_area',
  reset_emergency: 'mower_logic/reset_emergency',
  reset_job: 'mower_logic:idle/reset_job',
  skip_path: 'mower_logic:mowing/skip_path',
};

// paused counts too, the mower is standing somewhere on the lawn then. recording drives with gps as well
const DRIVING = new Set(['MOWING', 'PAUSED', 'DOCKING', 'UNDOCKING', 'AREA_RECORDING']);
// skipping an area or a path drops what's left of it, so it goes out only after a few seconds and a second tap takes
// it back
const SKIP_DELAY = 4;

// every temperature of the mower in a fixed order, the blade side first, then the wheels, unknown ones after them
const TEMP_ORDER = [
  ['om_mow_motor_temp', 'Mow motor'],
  ['om_mow_esc_temp', 'Mow ESC'],
  ['om_left_esc_temp', 'Left ESC'],
  ['om_right_esc_temp', 'Right ESC'],
];

// the app's themes (its globals.css), auto follows Home Assistant's dark mode with dark or light
const THEMES = ['frost', 'dark', 'light', 'aurora', 'sunny'];

const GPS_QUALITY_LABEL = {none: 'no fix', fix: 'RTK fix', float: 'float', poor: 'too inaccurate'};

// the app's texts, English is the key
const DE = {
  'Emergency stop': 'Notaus',
  'Charged, in the dock': 'Geladen, im Dock',
  'Charging in the dock': 'Lädt im Dock',
  'Mowing {area}': 'Mäht {area}',
  Mowing: 'Mäht',
  'Heading home': 'Fährt nach Hause',
  'Leaving the dock': 'Verlässt das Dock',
  Paused: 'Pausiert',
  'Recording an area': 'Nimmt eine Fläche auf',
  'Waiting on the lawn': 'Wartet auf dem Rasen',
  charging: 'lädt',
  'since {time}': 'seit {time}',
  'Release the mower, then reset the emergency to drive again.':
    'Mäher freimachen und dann den Notaus zurücksetzen, um weiterzufahren.',
  'No data from the mower since {time}': 'Keine Daten vom Mäher seit {time}',
  'Connection lost, last data at {time}': 'Verbindung verloren, letzte Daten um {time}',
  'no fix': 'kein Fix',
  off: 'aus',
  'RTK fix': 'RTK-Fix',
  float: 'Float',
  'too inaccurate': 'zu ungenau',
  Speed: 'Tempo',
  Charging: 'Ladestrom',
  Battery: 'Akku',
  Rain: 'Regen',
  detected: 'erkannt',
  'Mow motor': 'Mähmotor',
  'Mow controller': 'Mähregler',
  'Left drive controller': 'Fahrregler links',
  'Right drive controller': 'Fahrregler rechts',
  Start: 'Start',
  Pause: 'Pause',
  'Go home': 'Nach Hause',
  // soft hyphens: a narrow button breaks them where German does, not anywhere (not every browser hyphenates German)
  'Skip area': 'Über­springen',
  Continue: 'Weiter',
  'Undo ({n} s)': 'Rück­gängig ({n} s)',
  'Reset emergency': 'Notaus zurücksetzen',
  'waiting for the mower…': 'warte auf den Mäher…',
  'connecting…': 'verbinde…',
  'Drop the interrupted job': 'Unterbrochenen Job verwerfen',
  'Drop the interrupted job? The next start mows from the beginning.':
    'Unterbrochenen Job verwerfen? Beim nächsten Start mäht er von vorne.',
  'Drop it': 'Verwerfen',
  Cancel: 'Abbrechen',
  'Not a MowBite mower: {entity}': 'Kein MowBite-Mäher: {entity}',
  Mower: 'Mäher',
  Look: 'Aussehen',
  'Frosted glass': 'Milchglas',
  Dark: 'Dunkel',
  Light: 'Hell',
  'Like Home Assistant': 'Wie Home Assistant',
};

const ICONS = {
  play: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  pause:
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1.5"/><rect x="14" y="5" width="4" height="14" rx="1.5"/></svg>',
  home: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11.5 12 4l8 7.5"/><path d="M6 10v9a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-9"/><path d="M10 20v-6h4v6"/></svg>',
  skip: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M5 5v14l9-7z"/><rect x="16" y="5" width="3" height="14"/></svg>',
  warning:
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20L12 3z"/><line x1="12" y1="10" x2="12" y2="14"/><circle cx="12" cy="17.3" r="0.6" fill="currentColor" stroke="none"/></svg>',
};

function batteryColor(percent) {
  if (percent > 50) return 'success';
  if (percent > 20) return 'warning';
  return 'error';
}

// how good the gps position is, told by its estimated accuracy (m): a few cm is an rtk fix, up to the mower's limit
// (mower_logic/max_position_accuracy, 0.2 m by default) still usable, 999 and more is no fix at all
function gpsQuality(accuracy, limit = 0.2) {
  if (accuracy === undefined || accuracy === null || accuracy >= 999) return 'none';
  if (accuracy <= 0.05) return 'fix';
  return accuracy <= limit ? 'float' : 'poor';
}

const escape = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

// the card's own looks around the app's (DASHBOARD_CSS from mowbite-app.js: the themes' colors from the app's
// globals.css, its dashboard from page.module.css)
const STYLE = `
  :host {
    display: block;
  }

  /* no card of its own around it: the glass sits right on the dashboard's background */
  ha-card {
    background: none;
    border: none;
    box-shadow: none;
  }

  .mb {
    container: card / inline-size;
    color: var(--foreground);
    font-family: Arial, Helvetica, sans-serif;
    -webkit-font-smoothing: antialiased;
    user-select: none;
    -webkit-user-select: none;
  }

  .page {
    display: grid;
    gap: 16px;
  }

  /* the app's name, small and quiet in the glass's bottom edge */
  .status {
    position: relative;
  }

  .wordmark {
    position: absolute;
    right: 14px;
    bottom: 3px;
    font-size: 10px;
    letter-spacing: 0.3px;
    color: var(--text-secondary);
    opacity: 0.55;
    pointer-events: none;
  }

  .wordmark strong {
    font-weight: 700;
  }

  .message {
    font-size: 14px;
  }

  /* a phone has less room than the app gets: a bit less padding so four buttons still fit */
  @container card (max-width: 420px) {
    .status,
    .today {
      padding: 14px;
    }
  }

  /* the backdrop blur needs a prefix in older webviews (the wall tablet's) */
  .status,
  .today {
    -webkit-backdrop-filter: var(--card-blur, none);
  }

  [hidden] {
    display: none !important;
  }

  /* no blur behind the glass: an old tablet draws that slowly, the glass is then only see-through */
  .mb.noblur {
    --card-blur: none;
  }
`;

// ---- the map, drawn the way the MowBite app draws it (MapView, mapIcons)

// the app's map colours, its settings change them
const MAP_COLORS = {
  // the app's colors and their defaults (src/lib/settings.ts COLORS)
  mower: '#ff1fa3',
  dock: '#2196f3',
  track: '#ff1fa3',
  transit: '#ff1fa3',
  mow: '#4caf50',
  unmowed: '#ffb300',
  nav: '#29b6f6',
  obstacle: '#ef5350',
  draft: '#888888',
  selected: '#ff1fa3',
  vertex: '#2196f3',
  stripes: '#ff1fa3',
  body: '#ff1fa3',
  swath: '#ffffff',
  edge: '#c5e1a5',
};

// ---- the app's pictures of the mowers, docks and the garden style: the ones that came with the integration
// (mowbite-art.js, built from MowBite by scripts/build-art.mjs), or the mower's own when its MowBite serves them, so the
// card looks like the MowBite the mower runs

// what the card draws with them, worked out where the pictures are. plain data in, plain data and svg text out, so the
// same runs on the mower's own pictures in their sandbox (this function's text goes in there)
function artOps(art) {
  return {
    api: () => art.ART_API,
    mower(key, o) {
      const icon = art.mowerIcon(key);
      return {key: icon.key, fit: icon.fit, side: icon.side, upright: icon.upright, svg: icon.draw(o)};
    },
    dock(key) {
      const icon = art.dockIcon(key);
      return {key: icon.key, real: icon.real, svg: icon.draw()};
    },
    body: (sizes, keepRectangle) => art.sizesBody(sizes, keepRectangle) ?? null,
    // the garden's life (ART_API 2): its layers as svg text in MowBite's order, null with none of it on
    life: (input) => (art.gardenLife ? art.gardenLife(input) : null),
    // the garden style's textures, fills and things in the app's own units (its 400 wide square, fit: where the map
    // lies in it), and the real edges in metres
    areas({areas, looks, lookVariants, lookSizes, lookTurns, lookClosed, lookGrounds, body, garden, uid, fit}) {
      // ART_API 3: the whole garden as MapView draws it, placed, clipped and turned by the app itself, its edges in
      // the 400 square
      if (art.gardenAreas) {
        const g = art.gardenAreas({areas, looks, lookVariants, lookSizes, lookTurns, lookClosed, lookGrounds, body, uid, fit});
        const e = g.edges;
        return {
          grid: true,
          defs: garden ? g.defs : '',
          fills: garden ? g.fills : {},
          things: garden ? g.things : {},
          over: garden ? g.over : {},
          covers: garden ? (g.covers ?? []) : [],
          edges: e ? {line: e.line, outside: e.grassOutside, obstacles: e.grassObstacles} : null,
        };
      }
      const {minX, minY, m, padX, padY} = fit;
      const app = (p) => ({x: (p.x - minX) * m + padX, y: 400 - ((p.y - minY) * m + padY)});
      const ring = (o) => o.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(3)} ${(-p.y).toFixed(3)}`).join('') + 'Z';
      const out = {defs: '', fills: {}, things: {}, over: {}, covers: [], edges: null};
      if (garden) {
        const angles = [];
        const clips = [];
        for (const a of areas) {
          const type = a.properties?.type;
          if (type === 'mow') {
            out.fills[a.id] = a.properties.mowable === false ? 'meadow' : `lawn${angles.length}`;
            angles.push(a.properties.angle ?? art.autoMowAngle(a.outline));
          } else if ((type === 'obstacle' || type === 'nav') && (a.outline ?? []).length > 2) {
            const look = art.areaLook(a, looks);
            out.fills[a.id] = art.groundOf(look);
            if (!art.isThing(look)) continue;
            // a thing inside the area's real edge, cut to it should it still stick out
            const inside = ((body && art.insideEdge(a.outline, body)) || a.outline).map(app);
            const {cx, cy, deg, w, h} = art.placeThing(look, inside);
            out.things[a.id] =
              `<g class="gardenThing${a.properties.active === false ? ' gardenOff' : ''}" clip-path="url(#${uid}clip${clips.length})">` +
              `<g transform="translate(${cx} ${cy}) rotate(${deg})">${art.drawThing(look, {x: -w / 2, y: -h / 2, w, h}) ?? ''}</g></g>`;
            clips.push(inside.map((p) => `${p.x},${p.y}`).join(' '));
          }
        }
        out.defs = art.gardenDefs(uid, m, angles, clips);
      }
      if (body) {
        const e = art.realEdges(areas, body);
        out.edges = {
          line: [...e.lawn, ...e.obstacles].map(ring).join(''),
          outside: e.grass.outside.map(ring).join(''),
          obstacles: e.grass.obstacles.map(ring).join(''),
        };
      }
      return out;
    },
  };
}

// the pictures that came with the integration, loaded next to the card with the same version
class BundledArt {
  constructor() {
    this.ops = import(new URL('mowbite-art.js' + new URL(import.meta.url).search, import.meta.url).href)
      .then((module) => artOps(module))
      .catch((err) => {
        console.warn('MowBite card: the map pictures are missing', err);
        return null;
      });
  }

  async call(op, ...args) {
    const ops = await this.ops;
    if (!ops) throw new Error('no pictures');
    return ops[op](...args);
  }
}
const bundledArt = new BundledArt();

// The mower's own pictures, from its MowBite (/mowbite-art.js, through the integration). Its code runs in a frame of
// its own with a unique origin (sandbox without allow-same-origin): it can't reach Home Assistant, the page or its
// login, it only answers with plain data and svg text, and that is cleaned before it goes into the card
class SandboxArt {
  constructor(code) {
    this.pending = new Map();
    this.next = 1;
    this.frame = document.createElement('iframe');
    this.frame.setAttribute('sandbox', 'allow-scripts');
    this.frame.setAttribute('aria-hidden', 'true');
    this.frame.style.cssText = 'position:fixed;width:0;height:0;border:0;visibility:hidden;';
    this.frame.srcdoc = `<!doctype html><script type="module">
const artOps = ${artOps.toString()};
let ops = null;
addEventListener('message', async (event) => {
  const {id, code, op, args} = event.data ?? {};
  try {
    if (code !== undefined) {
      const url = URL.createObjectURL(new Blob([code], {type: 'text/javascript'}));
      ops = artOps(await import(url));
      parent.postMessage({id, ok: true, result: ops.api()}, '*');
    } else {
      parent.postMessage({id, ok: true, result: ops[op](...args)}, '*');
    }
  } catch (err) {
    parent.postMessage({id, ok: false, error: String(err?.message ?? err)}, '*');
  }
});
parent.postMessage({ready: true}, '*');
<\/script>`;
    this.onMessage = (event) => {
      if (event.source !== this.frame.contentWindow) return;
      const data = event.data ?? {};
      if (data.ready) return this.loaded?.();
      const waiting = this.pending.get(data.id);
      if (!waiting) return;
      this.pending.delete(data.id);
      if (data.ok) waiting.resolve(data.result);
      else waiting.reject(new Error(data.error));
    };
    window.addEventListener('message', this.onMessage);
    const loaded = new Promise((resolve) => (this.loaded = resolve));
    document.body.appendChild(this.frame);
    this.api = loaded.then(() => this.send({code}));
  }

  send(message) {
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.frame.contentWindow.postMessage({id, ...message}, '*');
      setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error('the pictures did not answer'));
      }, 20000);
    });
  }

  async call(op, ...args) {
    await this.api;
    return cleanArt(op, await this.send({op, args}));
  }

  destroy() {
    window.removeEventListener('message', this.onMessage);
    this.frame.remove();
  }
}

// what can come back from the mower's pictures, with only the svg that draws: no scripts, no event handlers, no
// links or anything loaded from elsewhere
function cleanArt(op, result) {
  if (!result || typeof result !== 'object') return result;
  const out = JSON.parse(JSON.stringify(result));
  if (op === 'mower' || op === 'dock') out.svg = cleanSvg(out.svg);
  if (op === 'areas') {
    out.defs = cleanSvg(out.defs);
    for (const key of ['things', 'over']) for (const [id, svg] of Object.entries(out[key] ?? {})) out[key][id] = cleanSvg(svg);
    for (const [id, fill] of Object.entries(out.fills ?? {})) if (!/^[\w-]+$/.test(fill)) delete out.fills[id];
    for (const [key, d] of Object.entries(out.edges ?? {})) if (typeof d !== 'string' || !/^[MLHVZAC0-9.,eE\s-]*$/i.test(d)) out.edges[key] = '';
    out.covers = (out.covers ?? []).filter((c) => ['cx', 'cy', 'r'].every((k) => Number.isFinite(c?.[k])));
  }
  if (op === 'life') {
    for (const key of ['defs', 'lawn', 'things', 'stones', 'sky', 'canopies']) out[key] = cleanSvg(out[key]);
    out.covers = (out.covers ?? []).filter((c) => ['cx', 'cy', 'r'].every((k) => Number.isFinite(c?.[k])));
  }
  return out;
}

const SVG_ALLOWED = new Set(
  (
    'g path circle ellipse rect line polyline polygon defs linearGradient radialGradient stop pattern clipPath mask ' +
    'symbol use text tspan title desc animate animateTransform animateMotion set filter feGaussianBlur feOffset ' +
    'feMerge feMergeNode feFlood feComposite feColorMatrix feBlend feMorphology feDropShadow feTurbulence ' +
    'feDisplacementMap marker'
  ).split(' '),
);

function cleanSvg(text) {
  if (typeof text !== 'string' || !text) return '';
  const doc = new DOMParser().parseFromString(`<svg xmlns="${svgNS}" xmlns:xlink="http://www.w3.org/1999/xlink">${text}</svg>`, 'image/svg+xml');
  const root = doc.documentElement;
  if (root.nodeName !== 'svg' || doc.getElementsByTagName('parsererror').length) return '';
  for (const el of [...root.querySelectorAll('*')]) {
    if (!SVG_ALLOWED.has(el.localName) || el.namespaceURI !== svgNS) {
      el.remove();
      continue;
    }
    for (const attr of [...el.attributes]) {
      const name = attr.name.toLowerCase();
      const value = attr.value;
      const local = /url\((?!\s*['"]?#)/i.test(value) || /javascript:|data:|expression\(|@import/i.test(value);
      if (name.startsWith('on') || local || ((name === 'href' || name === 'xlink:href') && !value.startsWith('#'))) {
        el.removeAttribute(attr.name);
      }
    }
  }
  return [...root.childNodes].map((n) => new XMLSerializer().serializeToString(n)).join('').replace(/ xmlns="[^"]*"/g, '');
}

// per mower: the pictures it draws with, the mower's own once its MowBite serves pictures this card knows (ART_API 1,
// 2 with the garden's life), else the ones that came with the integration
const ART_APIS = [1, 2, 3];
const mowerArt = new Map();
function artFor(card) {
  const entity = card._config.entity;
  if (!mowerArt.has(entity)) {
    const choice = {art: bundledArt, listeners: new Set()};
    mowerArt.set(entity, choice);
    card._hass
      .callWS({type: 'mowbite/art', entity_id: entity})
      .then(async (answer) => {
        if (!answer?.code || !ART_APIS.includes(answer.api)) return;
        const own = new SandboxArt(answer.code);
        const api = await own.api.catch(() => null);
        if (!ART_APIS.includes(api)) {
          own.destroy();
          return;
        }
        choice.art = own;
        for (const listener of choice.listeners) listener(own);
      })
      .catch(() => {});
  }
  return mowerArt.get(entity);
}

// half the mower's length, m, when the app draws it at its real size
const MOWER_SIZE = 0.4;
// icons that don't grow with the map are this many pixels, times the size set in the app
const ICON_PX = 8;

// until the app's pictures are there (or if they can't load): an arrowhead for the mower, a dot for the dock
const FALLBACK_MOWER = {fit: null, side: false, upright: false, draw: () => '<polygon points="1,0 -0.6,0.6 -0.6,-0.6" fill="var(--c-mower)" stroke="#fff" stroke-width="0.5"/>'};
const FALLBACK_DOCK = {real: null, draw: () => '<circle r="0.6" fill="var(--c-dock)" stroke="#fff" stroke-width="0.5"/>'};

const MAP_BUTTONS = {
  plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  minus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 12h14"/></svg>',
  locate:
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
  fit: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/></svg>',
};

const MAP_STYLE = `
  .map {
    position: relative;
    border-radius: 18px;
    overflow: hidden;
    border: 1px solid var(--card-border);
    background: #0a0a0a;
    aspect-ratio: 1;
    max-height: 560px;
    touch-action: none;
  }

  .map svg {
    display: block;
    width: 100%;
    height: 100%;
    cursor: grab;
  }

  .map svg * {
    vector-effect: non-scaling-stroke;
  }

  .map svg.dragging {
    cursor: grabbing;
  }

  .mowArea {
    fill: var(--c-mow);
    fill-opacity: 0.35;
    stroke: var(--c-mow);
    stroke-width: 1.5;
  }

  .navArea {
    fill: var(--c-nav);
    fill-opacity: 0.2;
    stroke: var(--c-nav);
    stroke-width: 1.5;
  }

  .obstacleArea {
    fill: var(--c-obstacle);
    fill-opacity: 0.25;
    stroke: var(--c-obstacle);
    stroke-width: 1;
  }

  .inactive {
    fill-opacity: 0.08;
    stroke-dasharray: 4 3;
  }

  /* drivable but not mowed: its own color, the edge stays solid */
  .skipMowing {
    fill: var(--c-unmowed);
    fill-opacity: 0.15;
    stroke: var(--c-unmowed);
  }

  .track {
    fill: none;
    stroke: var(--c-track);
    stroke-opacity: 0.55;
    stroke-width: 1.5;
    stroke-linejoin: round;
    stroke-linecap: round;
  }

  .transit {
    fill: none;
    stroke: var(--c-transit);
    stroke-opacity: 0.6;
    stroke-width: 1.5;
    stroke-dasharray: 4 4;
  }

  /* what's still to mow of the area, like the app's plan to do */
  .planTodo,
  .planLane,
  .planOutline {
    fill: none;
    stroke: var(--foreground);
    stroke-opacity: 0.35;
    stroke-width: 1;
    stroke-dasharray: 3 3;
    stroke-linejoin: round;
    pointer-events: none;
  }

  .draftArea {
    fill: var(--c-draft);
    fill-opacity: 0.12;
    stroke: var(--c-draft);
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }

  .dock,
  .mower,
  .gardenThing,
  .overLayer,
  .mowerUnder {
    pointer-events: none;
  }

  /* the mower's outline where a crown or a parasol hides it (the app's MapView) */
  .mowerUnderBody {
    fill: none;
    stroke: #fff;
    stroke-opacity: 0.9;
    stroke-width: 1.5;
  }

  .turn {
    transition: transform 0.35s ease-in-out;
  }

  /* lawn too, between the lines (the middle of the mower) and the real edges, as green as the mowing areas */
  .realGrass {
    pointer-events: none;
    fill: var(--c-mow);
    fill-opacity: 0.35;
    fill-rule: evenodd;
    stroke: none;
  }

  /* where the edges really are, the outlines being the middle of the mower */
  .realEdge {
    pointer-events: none;
    fill: none;
    stroke: var(--c-edge);
    stroke-opacity: 0.9;
    stroke-width: 1.25;
    stroke-dasharray: 5 3;
    stroke-linejoin: round;
  }

  /* the garden style (the app's gardenLook): paving around the lawn, half see-through so the page shows a little,
     the areas filled with their textures, an inactive one and its picture faded */
  .map.gardenMap {
    background: transparent;
  }

  .map svg.garden {
    background: color-mix(in srgb, #8f8778 30%, transparent);
  }

  .garden .inactive,
  .gardenOff {
    opacity: 0.45;
  }

  .garden .realGrass {
    fill: #4e8d3e;
    fill-opacity: 1;
  }

  /* left uncut in the last job */
  .leftover {
    fill: none;
    stroke: var(--c-unmowed);
    stroke-opacity: 0.85;
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .tightPlace {
    fill: var(--c-obstacle);
    fill-opacity: 0.8;
    stroke: #fff;
    stroke-width: 1;
  }

  /* the strip the blade cut, as wide as the blade on the map */
  .swath path {
    vector-effect: none;
    fill: none;
    stroke: var(--c-swath);
    stroke-opacity: 0.22;
    stroke-linecap: butt;
    stroke-linejoin: round;
  }

  .swath path.swathEnd {
    fill: var(--c-swath);
    fill-opacity: 0.22;
    stroke: none;
  }

  .mowerBody {
    fill: var(--c-body);
    fill-opacity: 0.12;
    stroke: var(--c-body);
    stroke-opacity: 0.85;
    stroke-width: 1.25;
    stroke-linejoin: round;
  }

  .mowerBlade {
    fill: none;
    stroke: var(--c-swath);
    stroke-opacity: 0.85;
    stroke-width: 1;
    stroke-dasharray: 3 2;
  }

  .mowerBlade.on {
    fill: var(--c-swath);
    fill-opacity: 0.2;
    stroke-dasharray: none;
  }

  .mowerAxle {
    fill: var(--c-body);
  }

  .zoomButtons {
    position: absolute;
    top: 10px;
    right: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .zoomButtons button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    padding: 0;
    border-radius: 10px;
    border: 1px solid var(--card-border);
    background: var(--card);
    color: var(--foreground);
    cursor: pointer;
    box-shadow: var(--btn-3d);
  }

  .zoomButtons button.on {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 60%, transparent);
  }

  /* wide enough: the status and the map side by side, like the app on a big screen */
  @container card (min-width: 760px) {
    .page.withMap {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      align-items: start;
    }

    .page.withMap .message {
      grid-column: 1 / -1;
    }

    /* the status and the map side by side and as high as each other, today under both */
    .page.withMap .status {
      grid-column: 1;
      grid-row: 1;
    }

    /* the map takes the status' height (contain: size, its own doesn't count) */
    .page.withMap .map {
      grid-column: 2;
      grid-row: 1;
      align-self: stretch;
      aspect-ratio: auto;
      max-height: none;
      contain: size;
    }

    .page.withMap .today {
      grid-column: 1 / -1;
    }
  }
`;

// The mower's body and blade from its sizes, in metres: a rectangle around the point OpenMower follows (the middle
// between the rear drive wheels), front ahead of it, rear behind, width wide, and the blade bladeAhead ahead of it and
// bladeOffset to the left. Nothing without them
const MAX_BLADE = 0.4;
function bodyFrom(s, keepRectangle) {
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const width = num(s?.width);
  const front = num(s?.front);
  const rear = num(s?.rear);
  if (width === null || front === null || rear === null || width <= 0 || front + rear <= 0) return null;
  const blade = num(s?.blade) ?? 0;
  return {
    width,
    front,
    rear,
    blade: blade > 0 && blade <= MAX_BLADE ? blade : 0,
    bladeAhead: num(s?.bladeAhead) ?? 0,
    bladeOffset: num(s?.bladeOffset) ?? 0,
    ...(outlineOf(s?.outline) ? {outline: outlineOf(s.outline)} : {}),
  };
}

// the body's real contour from above, [ahead, left] in m, as the app and the planner keep it
function outlineOf(v) {
  if (!Array.isArray(v) || v.length < 3) return undefined;
  return v.every((p) => Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === 'number' && Number.isFinite(n)))
    ? v
    : undefined;
}

// the corners of the body and the blade's centre in the map, for the mower at x, y facing heading (rad, ccw)
function bodyShape(b, x, y, heading) {
  const c = Math.cos(heading);
  const s = Math.sin(heading);
  const at = (ahead, left) => ({x: x + c * ahead - s * left, y: y + s * ahead + c * left});
  return {
    // the contour's points, or the rectangle's corners
    corners: b.outline
      ? b.outline.map(([ahead, left]) => at(ahead, left))
      : [at(b.front, b.width / 2), at(-b.rear, b.width / 2), at(-b.rear, -b.width / 2), at(b.front, -b.width / 2)],
    blade: at(b.bladeAhead, b.bladeOffset),
    middle: at((b.front - b.rear) / 2, 0),
  };
}

// shorter steps of the track don't say which way the mower drove
const MIN_STEP = 0.05;
// the heading is taken over this much track, gps wobble on short steps would swing the blade about
const SMOOTH = 0.25;
// a step turning further than this is a turn on the spot: the blade swings round it, drawn in steps of 15°
const SPIN = Math.PI / 3;
const SWING_STEP = Math.PI / 12;
// a piece of the strip ends where the heading turned this far from where it began
const PIECE_TURN = Math.PI / 4;
const turned = (a, b) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
const towards = (a, b) => Math.atan2(b.y - a.y, b.x - a.x);

// The strip the blade cut along a stretch of track driven with the blades on, worked out point by point as the track
// grows: the blade's centre, ahead of and beside the point the track follows, with the heading taken from the way it
// drove (it mows forwards). In pieces, one per lane and per bit of a turn, so drawn see-through the strip shows darker
// where lanes overlap. Each piece begins where the one before ended
class SwathScan {
  constructor(b) {
    this.b = b;
    // the finished pieces, they don't change any more, and the one still growing
    this.pieces = [];
    this.piece = [];
    this.start = 0;
    this.heading = null;
    // the track since the last turn on the spot
    this.run = [];
    this.from = null;
  }

  blade(p, h) {
    const b = this.b;
    return {
      x: p.x + Math.cos(h) * b.bladeAhead - Math.sin(h) * b.bladeOffset,
      y: p.y + Math.sin(h) * b.bladeAhead + Math.cos(h) * b.bladeOffset,
    };
  }

  add(p, h) {
    if (this.piece.length > 1 && Math.abs(turned(h, this.start)) > PIECE_TURN) {
      this.pieces.push(this.piece);
      this.piece = [this.piece[this.piece.length - 1]];
    }
    if (this.piece.length < 2) this.start = h;
    this.piece.push(p);
  }

  push(to) {
    const from = this.from;
    if (!from) {
      this.from = to;
      return;
    }
    if (Math.hypot(to.x - from.x, to.y - from.y) < MIN_STEP) return;
    const step = towards(from, to);
    if (this.heading === null) {
      this.add(this.blade(from, step), step);
      this.run = [from];
    } else if (Math.abs(turned(step, this.heading)) > SPIN) {
      const d = turned(step, this.heading);
      const steps = Math.ceil(Math.abs(d) / SWING_STEP);
      for (let n = 1; n <= steps; n++) {
        const h = this.heading + (d * n) / steps;
        this.add(this.blade(from, h), h);
      }
      this.run = [from];
    }
    const run = this.run;
    run.push(to);
    let back = run.length - 2;
    while (back > 0 && Math.hypot(to.x - run[back].x, to.y - run[back].y) < SMOOTH) back--;
    this.heading = towards(run[back], to);
    this.add(this.blade(to, this.heading), this.heading);
    this.from = to;
  }
}

// the half of the blade's circle beyond the end of a piece (at end, coming from from): where it started or stopped
// mowing the strip is round
function swathEnd(from, end, r) {
  const len = Math.hypot(end.x - from.x, end.y - from.y) || 1;
  const d = {x: (end.x - from.x) / len, y: (end.y - from.y) / len};
  return Array.from({length: 9}, (_, i) => {
    const a = -Math.PI / 2 + (Math.PI * i) / 8;
    return {x: end.x + r * (d.x * Math.cos(a) - d.y * Math.sin(a)), y: end.y + r * (d.x * Math.sin(a) + d.y * Math.cos(a))};
  });
}

// a track polyline takes this many points, then the next one goes on: a new point only redraws a short one
const TRACK_CHUNK = 200;
// further than this the mower doesn't glide, it's put there (m)
const JUMP = 5;
// following the mower the map shows this many metres around it, like the app's overview, until zoomed
const FOLLOW_SPAN = 6;

// Poses come about once a second. Easing towards each new one looks like stop and go, so like the app the mower is
// played back one update interval late, at constant speed between the last two
class EasedPose {
  constructor() {
    this.samples = [];
    this.interval = 200;
  }

  // a new pose, false when it's the one there already
  push(pose, now) {
    const list = this.samples;
    if (!pose) {
      const had = list.length > 0;
      list.length = 0;
      return had;
    }
    const last = list[list.length - 1];
    if (last && last.pose.x === pose.x && last.pose.y === pose.y && last.pose.heading === pose.heading) {
      last.pose = pose;
      return false;
    }
    if (last) {
      const dt = now - last.t;
      if (Math.hypot(pose.x - last.pose.x, pose.y - last.pose.y) > JUMP || dt > 3000) list.length = 0;
      else this.interval = this.interval * 0.8 + Math.min(1500, Math.max(50, dt)) * 0.2;
    }
    list.push({t: now, pose});
    if (list.length > 10) list.shift();
    return true;
  }

  // where the mower is drawn now, and whether it's still on its way to the newest pose
  at(now) {
    const list = this.samples;
    if (!list.length) return {pose: null, moving: false};
    const newest = list[list.length - 1];
    const at = now - this.interval;
    if (list.length < 2 || at >= newest.t) return {pose: newest.pose, moving: false};
    let i = list.length - 2;
    while (i > 0 && list[i].t > at) i--;
    const a = list[i];
    const b = list[i + 1];
    const f = Math.min(1, Math.max(0, (at - a.t) / (b.t - a.t || 1)));
    return {
      pose: {
        ...newest.pose,
        x: a.pose.x + (b.pose.x - a.pose.x) * f,
        y: a.pose.y + (b.pose.y - a.pose.y) * f,
        heading: a.pose.heading + turned(b.pose.heading, a.pose.heading) * f,
      },
      moving: true,
    };
  }
}

const svgPath = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(3)} ${(-p.y).toFixed(3)}`).join('');

const svgNS = 'http://www.w3.org/2000/svg';

class MowbiteMap {
  // the map's svg in a section with its zoom buttons. world coordinates in metres, y up: drawn with y flipped,
  // every line stays as wide on screen whatever the zoom (non-scaling strokes)
  constructor(section) {
    this.section = section;
    section.innerHTML = `
      <svg class="svg" xmlns="${svgNS}" preserveAspectRatio="xMidYMid meet">
        <g class="areas"></g>
        <g class="docks"></g>
        <g class="edges"></g>
        <g class="leftovers"></g>
        <g class="plan"></g>
        <g class="swath"></g>
        <g class="tracks"></g>
        <g class="tight"></g>
        <g class="mowerBodyLayer"></g>
        <g class="mowerIcon"></g>
        <g class="mowerTop"></g>
        <g class="overLayer"></g>
        <g class="underLayer"></g>
      </svg>
      <div class="zoomButtons">
        <button data-zoom="in" title="+">${MAP_BUTTONS.plus}</button>
        <button data-zoom="out" title="-">${MAP_BUTTONS.minus}</button>
        <button data-zoom="follow" title="⌖">${MAP_BUTTONS.locate}</button>
        <button data-zoom="fit" title="⛶">${MAP_BUTTONS.fit}</button>
      </div>`;
    this.svg = section.querySelector('svg');
    this.areas = section.querySelector('.areas');
    this.docks = section.querySelector('.docks');
    this.edges = section.querySelector('.edges');
    this.tracks = section.querySelector('.tracks');
    this.planLayer = section.querySelector('.plan');
    this.leftoverLayer = section.querySelector('.leftovers');
    this.tightLayer = section.querySelector('.tight');
    // the plan to do drawn, only drawn again when it changed
    this.todo = '';
    this.swath = section.querySelector('.swath');
    this.bodyLayer = section.querySelector('.mowerBodyLayer');
    this.mower = section.querySelector('.mowerIcon');
    this.top = section.querySelector('.mowerTop');
    // the garden's crowns and parasols over the mower, and its outline where they hide it (the app's covers)
    this.overLayer = section.querySelector('.overLayer');
    this.underLayer = section.querySelector('.underLayer');
    this.covers = [];
    this.body = null;
    this.points = [];
    // the stretch with the blades on the strip is still growing along: its scan and its growing piece and ends
    this.stretch = null;
    // an old tablet's light card glides at fewer frames
    this.light = false;
    // the mower glides between the poses that come in, drawn every frame while it moves, in follow mode with the map
    // gliding along under it
    this.eased = new EasedPose();
    this.frame = 0;
    this.drawnAt = 0;
    this.followSpan = FOLLOW_SPAN;
    // whether the view is already the window around the mower, or still the one from before following
    this.windowed = false;
    // the svg's size, measured when it changes rather than every frame
    this.box = null;
    this.map = null;
    this.icons = {};
    this.view = null; // {x, y, w, h} in svg units (x, -y)
    this.follow = false;
    this.pose = null;
    this.emergency = false;
    // which way a side view faces, and how fast the mower drives (m/s, for the icons that walk)
    this.facing = 1;
    this.speed = 0;
    // the app's map style: plain or garden, the pictures picked per area, keep the rectangle over a model's outline
    this.look = {style: null, looks: {}};
    this.uid = 'mb' + Math.random().toString(36).slice(2, 8);
    this.runs = []; // {blades, points: "x,y x,y", el}
    this.pointers = new Map();
    section.querySelector('.zoomButtons').addEventListener('click', (ev) => {
      const button = ev.target.closest('button');
      if (!button) return;
      const what = button.dataset.zoom;
      if (what === 'in') this.zoom(1 / 1.5);
      if (what === 'out') this.zoom(1.5);
      if (what === 'fit') this.setFollow(false), this.fit();
      if (what === 'follow') this.setFollow(!this.follow);
    });
    this.svg.addEventListener('pointerdown', (ev) => this.down(ev));
    this.svg.addEventListener('pointermove', (ev) => this.move(ev));
    this.svg.addEventListener('pointerup', (ev) => this.up(ev));
    this.svg.addEventListener('pointercancel', (ev) => this.up(ev));
    // icons that keep their size on screen have to follow when the map gets bigger or smaller
    // the pictures it draws with (setArt), and what they drew: the mower's icons by what they show, the dock's
    this.art = null;
    this.mowerIcons = new Map();
    this.dockIcon = null;
    this.areasDrawn = 0;
    this.resize = new ResizeObserver(() => this.refresh());
    this.resize.observe(section);
    this.svg.addEventListener(
      'wheel',
      (ev) => {
        ev.preventDefault();
        this.zoom(ev.deltaY > 0 ? 1.2 : 1 / 1.2, this.toWorld(ev.clientX, ev.clientY));
      },
      {passive: false},
    );
  }

  refresh() {
    const box = this.svg.getBoundingClientRect();
    this.box = {width: box.width, height: box.height};
    if (this.view) this.setView(this.view, true);
    else this.fit();
    this.wake();
  }

  destroy() {
    this.destroyed = true;
    this.resize.disconnect();
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  // pixels per metre at the current view, the svg is fitted (meet) into its box
  get k() {
    if (!this.view || !this.box?.width) return 40;
    return Math.min(this.box.width / this.view.w, this.box.height / this.view.h);
  }

  toWorld(clientX, clientY) {
    const box = this.svg.getBoundingClientRect();
    const k = this.k;
    const cx = this.view.x + this.view.w / 2 + (clientX - box.left - box.width / 2) / k;
    const cy = this.view.y + this.view.h / 2 + (clientY - box.top - box.height / 2) / k;
    return {x: cx, y: cy};
  }

  setMap(map) {
    this.map = map;
    this.drawAreas();
    if (!this.view) this.fit();
    this.drawDocks();
  }

  // the app's map style and the pictures picked for the areas (its settings), drawn again when they change
  setLook(settings) {
    const look = {
      style: settings?.mapStyle ?? null,
      looks: settings?.looks ?? {},
      // how each picture is drawn, as picked under the map (ART_API 3)
      lookVariants: settings?.lookVariants ?? {},
      lookSizes: settings?.lookSizes ?? {},
      lookTurns: settings?.lookTurns ?? {},
      lookClosed: settings?.lookClosed ?? {},
      // the ground picked under a picture (soil, mulch, turf, gravel ...)
      lookGrounds: settings?.lookGrounds ?? {},
    };
    if (JSON.stringify(look) === JSON.stringify(this.look)) return;
    this.look = look;
    this.drawAreas();
  }

  setSpeed(speed) {
    this.speed = speed;
  }

  // what the garden's life goes by besides the map (the app's LifeInput): settings.garden, the place on earth, the
  // weather, rain, the last jobs. drawn again when one of them changes, the time every 5 minutes like the app, the
  // mower's light at night and the live cuts while it drives every 10 s (30 s on a light card)
  setLife(life) {
    const now = Date.now();
    const key = JSON.stringify([life.garden, life.datum, life.weather, life.rain, life.jobsAt, Math.floor(now / 300000)]);
    const moving = this.lifeParts && (this.lifeParts.growth || this.lifeDark) && life.driving;
    this.life = life;
    if (key !== this.lifeKey || (moving && now - (this.lifeAt ?? 0) > (this.light ? 30000 : 10000))) {
      this.lifeKey = key;
      this.drawAreas();
    }
  }

  // the app's pictures (BundledArt or the mower's own SandboxArt), everything drawn with them again
  setArt(art) {
    if (art === this.art) return;
    this.art = art;
    this.mowerIcons = new Map();
    this.dockIcon = null;
    this.drawAreas();
    this.drawDocks();
    this.mower.dataset.key = '';
    this.drawMower();
  }

  // the areas as the app draws them: biggest first, plain in their colors or in the garden style as lawn in stripes
  // along its mowing direction, ways and obstacles as their pictures. with the mower's sizes the real edges too: the
  // outlines are the middle of the mower, its body reaches half its width further
  drawAreas() {
    const map = this.map;
    if (!map) {
      this.areas.innerHTML = '';
      this.edges.innerHTML = '';
      return;
    }
    const size = (a) => Math.abs((a.outline ?? []).reduce((sum, p, i, o) => sum + p.x * o[(i + 1) % o.length].y - o[(i + 1) % o.length].x * p.y, 0));
    const areas = [...(map.areas ?? [])].sort((a, b) => size(b) - size(a));
    // the areas are drawn in the app's own units: its 400 wide square with the whole map fitted in 20 from the edge.
    // the garden's pictures and textures have sizes in those units, and their stripes start at its corner
    const all = (map.areas ?? []).flatMap((a) => a.outline ?? []);
    const xs = all.map((p) => p.x);
    const ys = all.map((p) => p.y);
    const [minX, maxX, minY, maxY] = all.length ? [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)] : [0, 1, 0, 1];
    const m = Math.min(360 / (maxX - minX || 1), 360 / (maxY - minY || 1));
    const padX = 20 + (360 - (maxX - minX) * m) / 2;
    const padY = 20 + (360 - (maxY - minY) * m) / 2;
    const app = (p) => `${((p.x - minX) * m + padX).toFixed(2)},${(400 - ((p.y - minY) * m + padY)).toFixed(2)}`;
    const toMap = `translate(${minX - padX / m} ${-minY - (400 - padY) / m}) scale(${1 / m})`;
    const garden = this.look.style === 'garden';
    const uid = this.uid;
    const draw = (art) => {
      const fills = art?.fills ?? {};
      const things = art?.things ?? {};
      // with the garden's life: its long grass on the active lawns, its things (with their shadows) instead of the
      // areas' own, its stones instead of the real edges' line
      const life = art?.life;
      const drawn = areas.map((area) => {
        const p = area.properties ?? {};
        const cls = [
          p.type === 'nav' ? 'navArea' : p.type === 'obstacle' ? 'obstacleArea' : p.type === 'mow' ? 'mowArea' : 'draftArea',
          p.active === false ? 'inactive' : '',
          p.mowable === false ? 'skipMowing' : '',
        ]
          .filter(Boolean)
          .join(' ');
        const long = life?.long && p.type === 'mow' && p.active !== false && p.mowable !== false;
        const name = long ? 'long' : fills[area.id];
        const fill = garden && name ? ` style="fill:url(#${uid}${name});fill-opacity:1"` : '';
        let out = `<polygon class="${cls}" points="${(area.outline ?? []).map(app).join(' ')}"${fill}/>`;
        if (garden && !life && things[area.id]) out += things[area.id];
        return out;
      });
      const edges = art?.edges;
      const isGarden = garden && !!art;
      this.svg.classList.toggle('garden', isGarden);
      // the page shows a little through the garden's paving, like in the app
      this.section.classList.toggle('gardenMap', isGarden);
      // the real edges in metres (the card's own loop) or in the 400 square (the app's garden)
      const inGrid = (svg) => (art?.grid ? `<g transform="${toMap}">${svg}</g>` : svg);
      this.areas.innerHTML =
        (edges?.outside ? inGrid(`<path class="realGrass" d="${edges.outside}"/>`) : '') +
        `<g transform="${toMap}">${garden ? (art?.defs ?? '') + (life?.defs ?? '') : ''}${drawn.join('')}${life?.lawn ?? ''}</g>` +
        (edges?.obstacles ? inGrid(`<path class="realGrass" d="${edges.obstacles}"/>`) : '') +
        (life ? `<g transform="${toMap}">${life.things}${life.stones}${life.sky}</g>` : '');
      this.edges.innerHTML = edges?.line && !life?.stones ? inGrid(`<path class="realEdge" d="${edges.line}"/>`) : '';
      // crowns and parasols over the mower (the life's canopies with it on), and where they hide it in metres
      const over = life ? (life.canopies ?? '') : garden ? Object.values(art?.over ?? {}).join('') : '';
      this.overLayer.innerHTML = over ? `<g transform="${toMap}">${over}</g>` : '';
      const covers = garden ? ((life ? life.covers : art?.covers) ?? []) : [];
      this.covers = covers.map((c) => ({x: minX + (c.cx - padX) / m, y: -(minY + (400 - c.cy - padY) / m), r: c.r / m}));
      this.underLayer.innerHTML = this.covers.length
        ? `<defs><mask id="${uid}under" maskUnits="userSpaceOnUse" x="-10000" y="-10000" width="20000" height="20000">` +
          this.covers.map((c) => `<circle cx="${c.x}" cy="${c.y}" r="${c.r}" fill="#fff"/>`).join('') +
          `</mask></defs><g mask="url(#${uid}under)" class="mowerUnder"><polygon class="mowerUnderBody"/></g>`
        : '';
      this.drawMower();
      const growth = !!life?.parts?.growth;
      if (growth !== !!this.lifeGrowth) {
        this.lifeGrowth = growth;
        this.drawSwath();
      }
    };
    // the plain areas right away, the garden and the real edges once the pictures worked them out
    const turn = ++this.areasDrawn;
    if (!this.areas.firstChild) draw(null);
    if (!this.art || (!garden && !this.body)) return draw(null);
    const fit = {minX, minY, m, padX, padY};
    const life = this.lifeInput(garden, fit);
    this.lifeAt = Date.now();
    Promise.all([
      this.art.call('areas', {...this.look, areas: map.areas ?? [], body: this.body, garden, uid, fit}),
      life ? this.art.call('life', life).catch(() => null) : null,
    ])
      .then(([art, lifeArt]) => {
        if (turn !== this.areasDrawn || this.destroyed) return;
        this.lifeParts = lifeArt?.parts ?? null;
        this.lifeDark = !!lifeArt?.sky;
        draw({...art, life: lifeArt});
      })
      .catch(() => turn === this.areasDrawn && draw(null));
  }

  // the garden's life's input, null when none of it is on (or the pictures don't know it, they answer null then)
  lifeInput(garden, fit) {
    const life = this.life;
    const parts = life?.garden;
    if (!garden || !parts || !Object.values(parts).some((on) => on === true)) return null;
    // the live track in pieces of {x, y, b} like the app's, only for the cuts
    const track = [];
    if (parts.growth) for (let i = 0; i < this.points.length; i += 400) track.push(this.points.slice(i, i + 401));
    return {
      areas: this.map.areas ?? [],
      garden: parts,
      looks: this.look.looks,
      lookVariants: this.look.lookVariants,
      lookSizes: this.look.lookSizes,
      lookTurns: this.look.lookTurns,
      lookClosed: this.look.lookClosed,
      lookGrounds: this.look.lookGrounds,
      body: this.body,
      fit,
      uid: this.uid,
      now: Date.now(),
      datum: life.datum ?? undefined,
      weather: life.weather ?? undefined,
      rain: !!life.rain,
      mower: this.pose ? {x: this.pose.x, y: this.pose.y} : undefined,
      jobs: parts.growth ? (life.jobs ?? []) : [],
      track,
    };
  }

  setIcons(icons) {
    this.icons = icons ?? {};
    this.drawDocks();
    this.drawMower();
  }

  // the track: runs of points with the blades on (solid) or off (dashed), new points appended to the last run
  setTrack(update) {
    if (!update) return;
    if (update.reset) {
      this.tracks.innerHTML = '';
      this.runs = [];
      this.points = [];
    }
    const added = this.points.length;
    for (const [x, y, blades] of update.points) this.points.push({x, y, b: !!blades});
    const touched = new Set();
    for (const [x, y, blades] of update.points) {
      let run = this.runs[this.runs.length - 1];
      const point = `${x},${-y}`;
      if (!run || run.blades !== !!blades || run.points.length >= TRACK_CHUNK) {
        const el = document.createElementNS(svgNS, 'polyline');
        el.setAttribute('class', blades ? 'track' : 'transit');
        // the new run starts where the last one ended, so the line doesn't break
        const start = run ? run.points[run.points.length - 1] : null;
        run = {blades: !!blades, points: start ? [start] : [], el};
        this.runs.push(run);
        this.tracks.appendChild(el);
      }
      run.points.push(point);
      touched.add(run);
    }
    for (const run of touched) run.el.setAttribute('points', run.points.join(' '));
    if (update.reset) this.drawSwath();
    else this.growSwath(added);
  }

  // what's still to do of the area being mowed, from the app's plan progress (a list of point lists)
  setTodo(todo) {
    const d = (todo ?? [])
      .filter((p) => p.length > 1)
      .map((p) => p.map((q, i) => `${i ? 'L' : 'M'}${q.x.toFixed(2)} ${(-q.y).toFixed(2)}`).join(''))
      .join('');
    if (d === this.todo) return;
    this.todo = d;
    this.planLayer.innerHTML = d ? `<path class="planTodo" d="${d}"/>` : '';
  }

  // what the last job left uncut, as the planner found it
  setLeftovers(paths) {
    this.leftoverLayer.innerHTML = (paths ?? [])
      .map((points) => `<polyline class="leftover" points="${points.map(([x, y]) => `${x},${-y}`).join(' ')}"/>`)
      .join('');
  }

  // where the body came too close to an edge in the last job
  setTight(places) {
    this.tightLayer.innerHTML = (places ?? [])
      .map(([x, y]) => `<circle class="tightPlace" cx="${x}" cy="${-y}" r="0.06"/>`)
      .join('');
  }

  // the mower's sizes, from the app or the integration, null without them
  setBody(body) {
    if (JSON.stringify(body) === JSON.stringify(this.body)) return;
    this.body = body;
    this.drawAreas();
    this.drawSwath();
    this.drawDocks();
    this.drawMower();
  }

  setLight(light) {
    this.light = light;
  }

  // the strip anew, along the whole track
  drawSwath() {
    this.swath.innerHTML = '';
    this.stretch = null;
    if (this.body?.blade) this.swath.setAttribute('stroke-width', this.body.blade);
    this.growSwath(0);
  }

  // the strip along the track's points from start on. a finished piece is added once, only the growing piece and the
  // blade's round ends are drawn again
  growSwath(start) {
    const body = this.body;
    // the garden's growth draws the cut lawn itself, the app leaves the blade's strip out then
    if (!body?.blade || this.lifeGrowth) return;
    for (let i = start; i < this.points.length; i++) {
      const p = this.points[i];
      if (!p.b) {
        if (this.stretch) this.flushSwath();
        this.stretch = null;
        continue;
      }
      if (!this.stretch) {
        const open = document.createElementNS(svgNS, 'path');
        const ends = document.createElementNS(svgNS, 'path');
        ends.setAttribute('class', 'swathEnd');
        this.swath.append(open, ends);
        this.stretch = {scan: new SwathScan(body), done: 0, open, ends};
      }
      this.stretch.scan.push(p);
    }
    if (this.stretch) this.flushSwath();
  }

  flushSwath() {
    const stretch = this.stretch;
    const {scan, open, ends} = stretch;
    while (stretch.done < scan.pieces.length) {
      const el = document.createElementNS(svgNS, 'path');
      el.setAttribute('d', svgPath(scan.pieces[stretch.done++]));
      this.swath.insertBefore(el, open);
    }
    const growing = scan.piece.length > 1 ? scan.piece : null;
    if (growing) open.setAttribute('d', svgPath(growing));
    else open.removeAttribute('d');
    // where the blade started and where it is or stopped, the strip is round
    const first = scan.pieces[0] ?? growing;
    const last = growing ?? scan.pieces[scan.pieces.length - 1];
    if (first && last) {
      const r = this.body.blade / 2;
      ends.setAttribute(
        'd',
        `${svgPath(swathEnd(first[1], first[0], r))}Z${svgPath(swathEnd(last[last.length - 2], last[last.length - 1], r))}Z`,
      );
    } else {
      ends.removeAttribute('d');
    }
  }

  setPose(pose, emergency) {
    const moved = this.eased.push(pose, performance.now());
    if (moved || emergency !== this.emergency || (pose && !this.pose)) {
      this.emergency = emergency;
      this.wake();
    }
  }

  wake() {
    if (!this.frame) this.frame = requestAnimationFrame((now) => this.tick(now));
  }

  // one frame: the mower where it is on its way, and the view along with it in follow mode
  tick(now) {
    this.frame = 0;
    // a hidden map draws nothing, it catches up when it shows again
    if (!this.box?.width) return;
    const {pose, moving} = this.eased.at(now);
    // the mower is slow: drawn only once it moved a pixel on screen, most frames would draw it where it already is.
    // on an old tablet's light card at most 12 times a second
    const last = this.pose;
    let draw = true;
    if (moving && last && pose) {
      const k = this.k;
      const step = Math.max(Math.hypot(pose.x - last.x, pose.y - last.y) * k, Math.abs(turned(pose.heading, last.heading)) * 0.3 * k);
      draw = step >= 1 && (!this.light || now - this.drawnAt >= 80);
    }
    if (draw) {
      this.drawnAt = now;
      this.pose = pose;
      this.drawMower();
      if (this.follow && pose) this.followMower(this.light);
    }
    if (moving) this.wake();
  }

  setFollow(on) {
    this.follow = on;
    this.windowed = false;
    this.section.querySelector('[data-zoom="follow"]').classList.toggle('on', on);
    if (on && this.pose) this.followMower();
  }

  // like the app: the mower in the middle of a window a few metres wide, as big as it was zoomed to the last time.
  // lazy (an old tablet's light card): moving the view repaints the whole map, so it only moves, in one step, once
  // the mower is well off the middle, and puts it a little behind the middle so it has room ahead
  followMower(lazy = false) {
    if (!this.view) return;
    const v = this.view;
    const w = this.windowed ? v.w : this.followSpan;
    const h = this.windowed ? v.h : this.followSpan;
    const x = this.pose.x;
    const y = -this.pose.y;
    if (lazy && this.windowed) {
      const dx = x - (v.x + v.w / 2);
      const dy = y - (v.y + v.h / 2);
      if (Math.abs(dx) < w * 0.3 && Math.abs(dy) < h * 0.3) return;
      // ahead in the direction it drives (svg y points down)
      const ahead = Math.min(w, h) * 0.2;
      const hx = Math.cos(this.pose.heading) * ahead;
      const hy = -Math.sin(this.pose.heading) * ahead;
      this.setView({x: x + hx - w / 2, y: y + hy - h / 2, w, h});
      return;
    }
    this.windowed = true;
    this.setView({x: x - w / 2, y: y - h / 2, w, h});
  }

  fit() {
    const xs = [];
    const ys = [];
    for (const area of this.map?.areas ?? []) for (const c of area.outline ?? []) xs.push(c.x), ys.push(-c.y);
    for (const d of this.map?.docking_stations ?? []) xs.push(d.position.x), ys.push(-d.position.y);
    if (this.pose) xs.push(this.pose.x), ys.push(-this.pose.y);
    if (!xs.length) return;
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const pad = Math.max(maxX - minX, maxY - minY, 2) * 0.06;
    this.setView({x: minX - pad, y: minY - pad, w: maxX - minX + 2 * pad, h: maxY - minY + 2 * pad});
  }

  center(x, y) {
    if (!this.view) return;
    this.setView({...this.view, x: x - this.view.w / 2, y: y - this.view.h / 2});
  }

  zoom(factor, at) {
    if (!this.view) return;
    const v = this.view;
    // following, it zooms around the mower, and the next time it follows it's that close again
    const following = this.follow && this.pose && this.windowed;
    if (following) at = {x: this.pose.x, y: -this.pose.y};
    const cx = at ? at.x : v.x + v.w / 2;
    const cy = at ? at.y : v.y + v.h / 2;
    const w = Math.min(Math.max(v.w * factor, 0.5), 2000);
    const h = (v.h * w) / v.w;
    this.setView({x: cx - ((cx - v.x) * w) / v.w, y: cy - ((cy - v.y) * h) / v.h, w, h});
    if (following) this.followSpan = Math.min(w, h);
  }

  setView(view, resized = false) {
    const zoomed = resized || !this.view || view.w !== this.view.w || view.h !== this.view.h;
    this.view = view;
    this.svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
    // icons that keep their size on screen follow the zoom, moving the view leaves them as they are
    if (zoomed) {
      this.drawDocks();
      this.drawMower();
    }
  }

  drawDocks() {
    if (!this.view) return;
    const k = this.k;
    const key = this.icons.dock ?? '';
    if (this.art && this.dockIcon?.asked !== key) {
      this.dockIcon = {asked: key};
      this.art
        .call('dock', key)
        .then((icon) => {
          if (this.dockIcon?.asked !== key) return;
          this.dockIcon = {asked: key, ...icon};
          this.drawDocks();
        })
        .catch(() => {});
    }
    const icon = this.dockIcon?.svg !== undefined ? this.dockIcon : FALLBACK_DOCK;
    const size = this.icons.dockSize ?? 1;
    const drawn = icon.svg ?? icon.draw();
    this.docks.innerHTML = (this.map?.docking_stations ?? [])
      .map((station) => {
        const deg = (-station.heading * 180) / Math.PI;
        if (icon.real) {
          // a real station at its real size under the docked mower, its pins at the mower's front (as big as the
          // other icons at least)
          const {length, pins} = icon.real;
          const ahead = (this.body?.front ?? 0.43) + pins - length / 2;
          const x = station.position.x + Math.cos(station.heading) * ahead;
          const y = station.position.y + Math.sin(station.heading) * ahead;
          const half = Math.max(length / 2, (ICON_PX * size) / k);
          return `<g class="dock" transform="translate(${x} ${-y}) rotate(${deg}) scale(${half})">${drawn}</g>`;
        }
        return `<g class="dock" transform="translate(${station.position.x} ${-station.position.y}) scale(${(ICON_PX * size) / k})">${drawn}</g>`;
      })
      .join('');
  }

  drawMower() {
    const pose = this.pose;
    if (!pose || !this.view) {
      if (this.mower.firstChild) this.mower.innerHTML = '';
      this.mower.dataset.key = '';
      if (this.bodyLayer.firstChild) this.bodyLayer.innerHTML = '';
      this.drawBlade(null);
      return;
    }
    const k = this.k;
    const body = this.body;
    // the icon's kind (fit, side, upright) is known once one of its drawings came
    const known = this.mowerIcons.get(this.icons.mower ?? '');
    const icon = known?.meta ?? FALLBACK_MOWER;
    const shape = body ? bodyShape(body, pose.x, pose.y, pose.heading) : null;
    // which way a side view faces: it only turns once the mower clearly heads the other way, so it doesn't flicker
    // while the mower drives up or down the map
    const across = Math.cos(pose.heading);
    if (across > 0.3) this.facing = 1;
    else if (across < -0.3) this.facing = -1;
    // svg y points down, so the map's ccw heading becomes a cw rotation
    const deg = (-pose.heading * 180) / Math.PI;

    // its outline where a crown or a parasol hides it
    const under = this.underLayer.querySelector('.mowerUnderBody');
    if (under && shape) under.setAttribute('points', shape.corners.map((c) => `${c.x},${-c.y}`).join(' '));
    // the body as it really is, under the icon
    if (shape) {
      if (!this.bodyLayer.firstElementChild) this.bodyLayer.innerHTML = '<polygon class="mowerBody"/>';
      this.bodyLayer.firstElementChild.setAttribute('points', shape.corners.map((c) => `${c.x},${-c.y}`).join(' '));
    } else if (this.bodyLayer.firstChild) {
      this.bodyLayer.innerHTML = '';
    }

    // a real mower from above lies exactly on its body, other icons the same size on screen as the dock or at their
    // real size (never smaller than a few pixels), in the middle of the body with the sizes set
    const onBody = !!(icon.fit && shape);
    // a figure's legs and a pushed mower walk with the speed, a tenth of a m/s is close enough
    const speed = Math.round((this.speed ?? 0) * 10) / 10;
    const blades = !!pose.blades;
    const look = `${this.emergency}|${speed}|${blades}`;
    const drawing = this.mowerDrawing(look, {speed, emergency: this.emergency, blades});
    const key = `${this.icons.mower}|${look}|${onBody}|${drawing ? 'art' : ''}`;
    if (this.mower.dataset.key !== key) {
      const drawn = drawing ?? FALLBACK_MOWER.draw();
      // a side view heading left would stand on its head, mirrored it keeps its feet on the ground, a figure only
      // looks left or right: turned by css, so it turns around instead of flipping over at once
      const inner = onBody ? drawn : icon.fit ? `<g transform="scale(1 ${icon.fit})">${drawn}</g>` : drawn;
      this.mower.innerHTML = `<g class="mower"><g class="turn">${inner}</g></g>`;
      this.mower.dataset.key = key;
    }
    const turn = onBody || !icon.side ? '' : icon.upright ? `scaleX(${this.facing})` : `scaleY(${this.facing})`;
    const turnEl = this.mower.firstElementChild.firstElementChild;
    if (turnEl.style.transform !== turn) turnEl.style.transform = turn;
    let transform;
    if (onBody) {
      transform = `translate(${shape.middle.x} ${-shape.middle.y}) rotate(${deg}) scale(${(body.front + body.rear) / 2} ${body.width / 2})`;
    } else if (icon.upright) {
      // a figure isn't turned with the heading at all, it stands upright at the mower
      const at = this.icons.mowerRealSize && shape ? shape.middle : pose;
      const realSize = this.icons.mowerRealSize && shape ? (body.front + body.rear) / 2 : MOWER_SIZE;
      const base = this.icons.mowerRealSize ? Math.max(realSize, 7 / k) : ICON_PX / k;
      const size = base * (this.icons.mowerRealSize && shape ? 1 : (this.icons.mowerSize ?? 1));
      transform = `translate(${at.x} ${-at.y}) scale(${size})`;
    } else {
      const real = this.icons.mowerRealSize ? shape : null;
      const at = real ? real.middle : pose;
      const realSize = real ? (body.front + body.rear) / 2 : MOWER_SIZE;
      const base = this.icons.mowerRealSize ? Math.max(realSize, 7 / k) : ICON_PX / k;
      const size = base * (real ? 1 : (this.icons.mowerSize ?? 1));
      transform = `translate(${at.x} ${-at.y}) rotate(${deg}) scale(${size})`;
    }
    this.mower.firstElementChild.setAttribute('transform', transform);
    this.drawBlade(shape, k);
  }

  // the mower's icon as the pictures draw it for how it looks now (emergency, speed, blades), asked once and kept.
  // null while it's being asked, it's drawn again when it came
  mowerDrawing(look, o) {
    if (!this.art) return null;
    const key = this.icons.mower ?? '';
    let icon = this.mowerIcons.get(key);
    if (!icon) this.mowerIcons.set(key, (icon = {meta: null, drawings: new Map()}));
    if (icon.drawings.has(look)) return icon.drawings.get(look);
    icon.drawings.set(look, null);
    this.art
      .call('mower', key, o)
      .then((drawn) => {
        icon.meta = {fit: drawn.fit, side: drawn.side, upright: drawn.upright};
        icon.drawings.set(look, drawn.svg);
        this.mower.dataset.key = '';
        this.drawMower();
      })
      .catch(() => icon.drawings.delete(look));
    return null;
  }

  // over the icon: the blade where it sits under the mower, filled while it's on, and the point OpenMower follows
  drawBlade(shape, k) {
    const top = this.top;
    if (!shape) {
      if (top.firstChild) top.innerHTML = '';
      top.dataset.key = '';
      return;
    }
    const r = this.body.blade / 2;
    const key = `${r}`;
    if (top.dataset.key !== key) {
      top.dataset.key = key;
      top.innerHTML =
        (r > 0
          ? `<g class="mowerBladeAt"><circle class="mowerBlade" r="${r}"/></g>`
          : '') + '<circle class="mowerAxle"/>';
    }
    const at = top.firstElementChild.classList.contains('mowerBladeAt') ? top.firstElementChild : null;
    if (at) {
      at.setAttribute('transform', `translate(${shape.blade.x} ${-shape.blade.y})`);
      at.firstElementChild.classList.toggle('on', !!this.pose.blades);
    }
    const axle = top.lastElementChild;
    axle.setAttribute('cx', this.pose.x);
    axle.setAttribute('cy', -this.pose.y);
    axle.setAttribute('r', 1.5 / k);
  }

  // dragging moves the map, two fingers zoom it
  down(ev) {
    this.svg.setPointerCapture(ev.pointerId);
    this.pointers.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    this.svg.classList.add('dragging');
  }

  move(ev) {
    const last = this.pointers.get(ev.pointerId);
    if (!last || !this.view) return;
    const now = {x: ev.clientX, y: ev.clientY};
    if (this.pointers.size === 1) {
      const k = this.k;
      this.setFollow(false);
      this.setView({...this.view, x: this.view.x - (now.x - last.x) / k, y: this.view.y - (now.y - last.y) / k});
    } else if (this.pointers.size === 2) {
      const other = [...this.pointers.entries()].find(([id]) => id !== ev.pointerId)?.[1];
      if (other) {
        const before = Math.hypot(last.x - other.x, last.y - other.y);
        const after = Math.hypot(now.x - other.x, now.y - other.y);
        if (before > 0 && after > 0) this.zoom(before / after, this.toWorld((now.x + other.x) / 2, (now.y + other.y) / 2));
      }
    }
    this.pointers.set(ev.pointerId, now);
  }

  up(ev) {
    this.pointers.delete(ev.pointerId);
    if (!this.pointers.size) this.svg.classList.remove('dragging');
  }
}

// the app's own logic for the dashboard (mowbite-app.js, built from MowBite by scripts/build-art.mjs): one copy per
// mower, it keeps what it asked (the day's events, the schedule) like the app does for the mower it shows
const appModules = new Map();
function loadApp(entity) {
  if (!appModules.has(entity)) {
    const search = new URL(import.meta.url).search;
    const url = new URL(`mowbite-app.js${search}${search ? '&' : '?'}mower=${encodeURIComponent(entity)}`, import.meta.url);
    appModules.set(
      entity,
      import(url.href).catch((err) => {
        console.warn('MowBite card: the dashboard logic is missing', err);
        appModules.delete(entity);
        return null;
      }),
    );
  }
  return appModules.get(entity);
}

// how many runs the dashboard can show (six finished and one under way), and how many earlier days are looked
// through for them (the app's useRecentRuns)
const LATEST = 7;
const LATEST_DAYS = 7;
// the start the schedule left out, closed on this device, by its time
const MISSED_SEEN_KEY = 'mowbite-scheduleMissedSeen';

// What the dashboard asks the mower and the app, the way the app's dashboard does: the day's runs (again every 30 s
// and right away when the state changes), why an emergency stop is on, the wifi, the schedule and its log,
// maintenance due, and how far the mower got with the area it mows
class Dashboard {
  constructor(card, app) {
    this.card = card;
    this.app = app;
    this.timers = [];
    this.recent = null;
    this.wifi = undefined;
    this.schedule = null;
    this.log = [];
    this.due = [];
    this.reasons = null;
    this.methods = null;
    this.state = undefined;
    this.emergency = false;
    this.plan = null;
    this.asking = null;
    this.leftoverRun = null;
    app.setTransport({rpc: (method, params, timeout) => card._rpc(method, params, timeout), get: (path) => card._get(path)});
    app.setLanguage(card._lang);
    const every = (f, ms) => {
      f();
      this.timers.push(setInterval(f, ms));
    };
    every(() => this.loadRuns(), 30000);
    every(() => this.loadWifi(), 30000);
    every(() => this.loadLog(), 60000);
    every(() => this.loadSchedule(), 10 * 60000);
    every(() => this.loadDue(), 10 * 60000);
    every(() => this.card._update(), 10000);
    void this.loadMethods();
  }

  stop() {
    this.stopped = true;
    for (const t of this.timers) clearInterval(t);
    clearInterval(this.reasonTimer);
  }

  changed() {
    if (!this.stopped) this.card._update();
  }

  // what the garden's life goes by (settings.garden on in the garden style): the last 5 jobs for the lawn's growth,
  // asked again after each job and every half hour, the weather for the season every 20 minutes (only with the
  // weather on in the app, like there)
  life(settings, datum, driving) {
    const garden = settings?.mapStyle === 'garden' ? settings.garden : null;
    if (!garden) return {garden: null};
    const now = Date.now();
    if (garden.growth && !this.jobsAsking && (!this.jobsAt || now - this.jobsAt > 30 * 60000 || (this.wasDriving && !driving))) {
      void this.loadJobs();
    }
    this.wasDriving = driving;
    if (settings.weather && garden.season && datum && !this.weatherAsking && (!this.weatherAt || now - this.weatherAt > 20 * 60000)) {
      this.weatherAsking = true;
      this.app.weather
        .loadWeather(datum.lat, datum.lon)
        .then((w) => {
          this.weather = w;
          this.changed();
        })
        .catch(() => {})
        .finally(() => {
          this.weatherAsking = false;
          this.weatherAt = Date.now();
        });
    }
    return {garden, datum, weather: settings.weather ? this.weather : undefined, jobs: this.jobs ?? [], jobsAt: this.jobsAt};
  }

  // the last five jobs' tracks like the app's (position.history.list, newest first, a resumed job only once)
  async loadJobs() {
    this.jobsAsking = true;
    try {
      const list = (await this.card._rpc('position.history.list', [])) ?? [];
      const jobs = [];
      for (const job of list.filter((j, i) => list.findIndex((k) => k.job_id === j.job_id) === i).slice(0, 5)) {
        const history = await this.card._rpc('position.history', {job_id: job.job_id}, 20000).catch(() => null);
        jobs.push({job_id: job.job_id, timestamp: job.timestamp, segments: history?.segments ?? []});
      }
      this.jobs = jobs;
    } catch {
      // an OpenMower without the position history: no growth from it
      this.jobs = [];
    }
    this.jobsAsking = false;
    this.jobsAt = Date.now();
    this.changed();
  }

  // the rpcs the mower has: the leftovers only with the MowBite Planner
  async loadMethods() {
    this.methods = await this.app.rpcMethods().catch(() => null);
    this.changed();
  }

  // the state changed: there's something new in the history, it's asked again right away (forgetToday)
  setState(state, emergency) {
    if (state !== this.state) {
      const first = this.state === undefined;
      this.state = state;
      if (!first) {
        this.app.history.forgetToday();
        void this.loadRuns();
      }
    }
    if (emergency !== this.emergency) {
      this.emergency = emergency;
      this.reasons = null;
      clearInterval(this.reasonTimer);
      if (emergency) {
        // why it's on, from the ros log: when it comes on and every half minute while it lasts
        const ask = () =>
          void this.app.roslog
            .rosLogAround(Date.now() / 1000, 12 * 3600, 60)
            .then((lines) => {
              if (this.emergency) this.reasons = this.app.roslog.emergencyReasons(lines);
              this.changed();
            })
            .catch(() => {});
        ask();
        this.reasonTimer = setInterval(ask, 30000);
      }
    }
  }

  async loadRuns() {
    const {history, events} = this.app;
    try {
      const files = await history.historyDays();
      const todayKey = history.fileDay(new Date());
      const today = (await history.eventsOfDay(files, todayKey)).events;
      const runs = events.groupRuns(today, true).flatMap((e) => (e.kind === 'run' ? [e.run] : []));
      const latest = [...runs].reverse();
      for (const d of history.localDays(files).filter((d) => d !== todayKey).slice(0, LATEST_DAYS)) {
        if (latest.length >= LATEST) break;
        const old = events.groupRuns((await history.eventsOfDay(files, d)).events, false);
        latest.push(...old.flatMap((e) => (e.kind === 'run' ? [e.run] : [])).reverse());
      }
      this.recent = {today, runs, latest: latest.slice(0, LATEST)};
    } catch {
      // no event history: the mower can't be reached, or its OpenMower doesn't keep one
    }
    this.changed();
  }

  async loadWifi() {
    const s = await this.app.system.loadSystem().catch(() => null);
    this.wifi = s && !s.remote ? s.wifiSignal : undefined;
    this.changed();
  }

  async loadSchedule() {
    this.schedule = await this.app.schedule.loadSchedule().catch(() => null);
    this.changed();
  }

  async loadLog() {
    this.log = (await this.app.schedule.loadScheduleLog().catch(() => null)) ?? [];
    this.changed();
  }

  async loadDue() {
    const {stats} = this.app;
    const s = await stats.loadStats().catch(() => null);
    this.due = s ? stats.dueParts(s).map((p) => ({key: p.key, used: stats.partUse(s, p).seconds / 3600, due: p.dueHours})) : [];
    this.changed();
  }

  // the start the schedule left out, until it's closed on this device
  get missed() {
    const missed = this.schedule?.enabled ? this.app.schedule.missedStart(this.log) : null;
    let seen = 0;
    try {
      seen = Number(localStorage.getItem(MISSED_SEEN_KEY)) || 0;
    } catch {}
    return missed && missed.t !== seen ? missed : null;
  }

  closeMissed(t) {
    try {
      localStorage.setItem(MISSED_SEEN_KEY, String(t));
    } catch {}
    this.changed();
  }

  planned(datum) {
    if (!this.schedule) return null;
    return this.app.schedule.nextStart(this.schedule, undefined, datum ? this.app.sun.sunTimes(datum.lat, datum.lon) : null);
  }

  // how far the mower got with the area it mows (the app's usePlanProgress): its plan, where robot_state says it is
  // in it, and the time left from how fast the plan got done while the blades ran in the area
  progress(state, map) {
    const {areaPlan, planProgress, leftovers} = this.app;
    const areaId =
      state?.current_state === 'MOWING' && map && (state.current_area ?? -1) >= 0
        ? (map.areas ?? []).filter((a) => a.properties?.type === 'mow')[state.current_area]?.id
        : undefined;
    if (!areaId) return null;
    const events = this.recent?.today;
    // when the mower started on the area: its latest AREA event. the MowBite Planner may have handed out the
    // leftovers of the last mow in place of the plan, the plan doesn't fit then
    const since = events?.filter((e) => e.type === 'AREA' && e.area_id === areaId).at(-1)?.t;
    const key = `${areaId} ${since}`;
    if (since && this.leftoverRun?.key !== key) {
      this.leftoverRun = {key, yes: false};
      const look = () =>
        void leftovers.leftoversHandedOut(areaId, since).then(
          (yes) => {
            if (this.leftoverRun?.key !== key) return;
            if (yes) {
              this.leftoverRun.yes = true;
              this.changed();
            } else if (Date.now() / 1000 - since < 120) setTimeout(look, 20000);
          },
          () => {},
        );
      look();
    }
    const leftoverRun = !!since && this.leftoverRun?.key === key && this.leftoverRun.yes;
    if (leftoverRun) return {done: [], todo: [], doneLength: 0, todoLength: 0, fraction: 0, areaId, secondsLeft: null, leftovers: true};
    if (this.plan?.areaId !== areaId && this.asking !== areaId) {
      this.asking = areaId;
      areaPlan
        .mowerPaths(areaId, map)
        .then((paths) => {
          this.plan = paths ? {areaId, paths} : null;
        })
        .catch(() => {
          this.plan = null;
        })
        .finally(() => {
          this.asking = null;
          this.changed();
        });
    }
    const path = state.current_path ?? -1;
    const progress = this.plan?.areaId === areaId && path >= 0 ? planProgress.splitPlan(this.plan.paths, path, state.current_path_index ?? 0) : null;
    if (!progress) return null;
    const seconds = events ? planProgress.bladeSeconds(events, areaId, Date.now() / 1000) : 0;
    const rate = seconds > 60 && progress.doneLength > 5 ? progress.doneLength / seconds : null;
    if (rate && seconds > 600) planProgress.saveRate(rate);
    const r = rate ?? planProgress.savedRate();
    return {...progress, areaId, secondsLeft: r ? progress.todoLength / r : null};
  }
}

class MowbiteCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        {name: 'entity', required: true, selector: {entity: {domain: 'lawn_mower', integration: 'mowbite'}}},
        {
          name: 'theme',
          selector: {
            select: {
              mode: 'dropdown',
              options: [
                {value: 'frost', label: 'Frosted glass'},
                {value: 'aurora', label: 'Aurora'},
                {value: 'sunny', label: 'Sunny'},
                {value: 'dark', label: 'Dark'},
                {value: 'light', label: 'Light'},
                {value: 'auto', label: 'Like Home Assistant'},
              ],
            },
          },
        },
        {
          name: 'map',
          selector: {
            select: {
              mode: 'dropdown',
              options: [
                {value: 'integration', label: 'As set in the integration'},
                {value: 'app', label: 'As set in the MowBite app'},
                {value: 'auto', label: 'While the mower drives'},
                {value: 'always', label: 'Always'},
                {value: 'never', label: 'Never'},
              ],
            },
          },
        },
        {name: 'map_height', selector: {number: {min: 150, max: 1000, step: 10, mode: 'box', unit_of_measurement: 'px'}}},
        {name: 'status', selector: {boolean: {}}},
        {name: 'today', selector: {boolean: {}}},
        {name: 'leftovers', selector: {boolean: {}}},
        {name: 'blur', selector: {boolean: {}}},
      ],
      computeLabel: (schema) =>
        ({
          entity: 'Mower',
          theme: 'Look',
          map: 'Map',
          map_height: 'Map height (empty: square like in the app)',
          status: 'Status and buttons',
          today: 'Today: what was mowed, the last runs, the next start',
          leftovers: 'Check the last mow for leftovers',
          blur: 'Blur behind the glass (slower on old tablets)',
        })[schema.name],
    };
  }

  static getStubConfig(hass) {
    const mower = Object.values(hass?.entities ?? {}).find(
      (e) => e.platform === 'mowbite' && e.entity_id.startsWith('lawn_mower.'),
    );
    return {entity: mower?.entity_id ?? '', theme: 'frost', map: 'integration', status: true, blur: true};
  }

  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._data = null;
    this._error = null;
    this._unsub = null;
    this._subscribing = false;
    this._retry = null;
    this._skip = null;
    this._skipTimer = null;
    this._confirmReset = false;
    // the app's dashboard logic and what it asked, the leftovers card's state, the last runs unfolded
    this._app = null;
    this._dash = null;
    this._leftovers = {};
    this._moreRuns = false;
    this._pose = null;
    this._speed = 0;
    // the pictures it draws with (artFor), and the body worked out with them
    this._art = null;
    this._bodyAsked = null;
    this._built = false;
    this._mapData = null;
    this._settings = {};
    this._track = null;
    this._map = null;
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error('entity: the MowBite lawn mower, e.g. lawn_mower.openmower');
    const changed = this._config && this._config.entity !== config.entity;
    this._config = {theme: 'frost', map: 'integration', status: true, today: true, leftovers: true, blur: true, ...config};
    if (changed) {
      this._unsubscribe();
      this._data = null;
      this._mapData = null;
      this._track = null;
    }
    this._built = false;
    if (changed) {
      this._stopDashboard();
      this._art?.listeners.delete(this._onArt);
      this._art = null;
    }
    this._render();
    this._subscribe();
    this._startDashboard();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._app?.setLanguage(this._lang);
    this._applyLook();
    if (first) {
      // the waiting text was drawn before the language was known
      this._update();
      this._subscribe();
      this._startDashboard();
    }
  }

  // the app's own logic for the dashboard, its looks with it: drawn again once they're there
  _startDashboard() {
    this._useArt();
    if (this._dash || this._starting || !this._hass || !this._config || !this.isConnected) return;
    const entity = this._config.entity;
    this._starting = true;
    loadApp(entity).then((app) => {
      this._starting = false;
      if (!app || this._dash || entity !== this._config?.entity || !this.isConnected) return;
      const restyle = !this._app;
      this._app = app;
      app.setLanguage(this._lang);
      this._dash = new Dashboard(this, app);
      if (restyle && this._built) this._render();
      else this._update();
    });
  }

  _stopDashboard() {
    this._dash?.stop();
    this._dash = null;
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    if (!this._built && this._config) this._render();
    this._subscribe();
    this._startDashboard();
  }

  disconnectedCallback() {
    this._map?.destroy();
    this._map = null;
    this._built = false;
    this._unsubscribe();
    clearTimeout(this._retry);
    this._stopSkip();
    this._stopDashboard();
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return {columns: 12, min_columns: 6, rows: 'auto'};
  }

  // ---- talking to the integration

  async _subscribe() {
    if (this._unsub || this._subscribing || !this._hass || !this._config || !this.isConnected) return;
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage((data) => this._onData(data), {
        type: 'mowbite/subscribe',
        entity_id: this._config.entity,
      });
      this._error = null;
    } catch (err) {
      this._error = err?.code === 'not_found' ? this._t('Not a MowBite mower: {entity}', {entity: this._config.entity}) : err?.message || String(err);
      this._update();
      // the integration may still be starting
      clearTimeout(this._retry);
      this._retry = setTimeout(() => this._subscribe(), 10000);
    } finally {
      this._subscribing = false;
    }
  }

  _unsubscribe() {
    const unsub = this._unsub;
    this._unsub = null;
    if (unsub) unsub().catch(() => {});
  }

  _onData(data) {
    if (data.closed) {
      // the entry is reloading, the new one is there in a moment
      this._unsubscribe();
      clearTimeout(this._retry);
      this._retry = setTimeout(() => this._subscribe(), 2000);
      return;
    }
    this._trackSpeed(data);
    this._data = data;
    if ('map' in data) {
      this._mapData = data.map;
      this._map?.setMap(data.map);
    }
    if ('settings' in data) {
      this._settings = data.settings ?? {};
      this._applyLook();
      this._map?.setIcons(this._settings.icons);
      this._map?.setLook(this._settings);
    }
    this._updateBody();
    this._map?.setSpeed(this._speed);
    if ('planning' in data) {
      this._planning = data.planning;
      this._map?.setLeftovers(data.planning.leftovers);
      this._map?.setTight(data.planning.tight);
    }
    if (data.track) {
      // the whole track again after a reset, otherwise only the new points
      if (data.track.reset || !this._track) this._track = {reset: true, points: [...data.track.points]};
      else for (const point of data.track.points) this._track.points.push(point);
      this._map?.setTrack(data.track);
    }
    this._update();
  }

  // the app's sizes, the planner's (measured on the mower), the ones set in the integration
  _updateBody() {
    const data = this._data ?? {};
    // like the app: the planner's sizes (measured on the mower, with its outline) first, then the app's
    const planner = bodyFrom(data.planner_sizes);
    const sizes = planner ? null : this._settings?.mower ?? data.mower_sizes;
    this._body = planner ?? bodyFrom(sizes);
    this._map?.setBody(this._body);
    // sizes that are exactly a model's with a measured outline get that outline, as the app's pictures know them
    // (not the planner's, it has its own outline or none)
    const key = JSON.stringify([sizes, this._settings?.keepRectangle, !!this._art]);
    if (!sizes || !this._art || key === this._bodyAsked) return;
    this._bodyAsked = key;
    this._art.art
      .call('body', sizes, this._settings?.keepRectangle)
      .then((body) => {
        if (this._bodyAsked !== key || !body) return;
        this._body = body;
        this._map?.setBody(body);
      })
      .catch(() => {});
  }

  // the pictures this mower draws with: the integration's until the mower's own are there
  _useArt() {
    if (this._art || !this._hass || !this._config) return;
    this._art = artFor(this);
    this._onArt = (art) => {
      this._map?.setArt(art);
      this._bodyAsked = null;
      this._updateBody();
    };
    this._art.listeners.add(this._onArt);
    this._onArt(this._art.art);
  }

  // the mower's rpc and the app's endpoints for the app's dashboard logic, read only (the integration checks it)
  async _rpc(method, params, timeout) {
    try {
      const answer = await this._hass.callWS({type: 'mowbite/rpc', entity_id: this._config.entity, method, params: params ?? {}});
      return answer.result;
    } catch (err) {
      const code = String(err?.code ?? '');
      throw {code: code.startsWith('rpc_') ? Number(code.slice(4)) : code === 'timeout' ? 'timeout' : code, message: err?.message};
    }
  }

  async _get(path) {
    try {
      return await this._hass.callWS({type: 'mowbite/app', entity_id: this._config.entity, path});
    } catch {
      return {status: 502, body: ''};
    }
  }

  async _action(name) {
    try {
      await this._hass.callWS({type: 'mowbite/action', entity_id: this._config.entity, action: name});
    } catch (err) {
      this.dispatchEvent(
        new CustomEvent('hass-notification', {detail: {message: err?.message || String(err)}, bubbles: true, composed: true}),
      );
    }
  }

  // no speed on the wire, so estimate m/s from pose updates (smoothed, gps jitter is noisy)
  _trackSpeed(data) {
    const pose = data.state?.pose;
    const t = data.state_time;
    if (!pose || !t) return;
    const last = this._pose;
    if (last && t > last.t) {
      const dt = t - last.t;
      if (dt > 0.05) {
        const instant = Math.hypot(pose.x - last.x, pose.y - last.y) / dt;
        const alpha = 1 - Math.pow(0.5, dt / 0.4);
        this._speed += (instant - this._speed) * alpha;
        this._pose = {x: pose.x, y: pose.y, t};
      }
    } else if (!last) {
      this._pose = {x: pose.x, y: pose.y, t};
    }
  }

  // ---- texts

  get _lang() {
    const lang = this._hass?.locale?.language || this._hass?.language || 'en';
    return lang.toLowerCase().startsWith('de') ? 'de' : 'en';
  }

  // the app's own words (its language files), the card's own for what only the card says
  _t(text, values) {
    const app = this._app?.tr(text);
    let s = app !== undefined && app !== text ? app : (this._lang === 'de' && DE[text]) || text;
    for (const [k, v] of Object.entries(values ?? {})) s = s.replace(`{${k}}`, v);
    return s;
  }

  _fmt(n, digits = 0) {
    if (this._app) return this._app.fmt(n, digits);
    return new Intl.NumberFormat(this._lang, {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(n);
  }

  _clock(seconds, withSeconds = false) {
    if (this._app) return this._app.dates.clock(seconds, withSeconds);
    return new Date(seconds * 1000).toLocaleTimeString(this._lang, {
      hour: '2-digit',
      minute: '2-digit',
      ...(withSeconds ? {second: '2-digit'} : {}),
    });
  }

  // ---- drawing

  _applyLook() {
    const root = this.shadowRoot.querySelector('.mb');
    if (!root) return;
    // for hyphenation of the button labels
    root.lang = this._lang;
    let theme = this._config?.theme ?? 'frost';
    if (theme === 'auto') theme = this._hass?.themes?.darkMode ? 'dark' : 'light';
    for (const t of THEMES) root.classList.toggle(t, t === theme);
    root.classList.toggle('noblur', this._config?.blur === false);
    const mapSection = this.shadowRoot.querySelector('.map');
    const height = Number(this._config?.map_height);
    if (mapSection) {
      mapSection.style.aspectRatio = height > 0 ? 'auto' : '';
      mapSection.style.height = height > 0 ? `${height}px` : '';
      mapSection.style.maxHeight = height > 0 ? 'none' : '';
    }
    const colors = {...MAP_COLORS, ...(this._settings?.colors ?? {})};
    for (const [key, value] of Object.entries(colors)) root.style.setProperty(`--c-${key}`, value);
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}${this._app?.DASHBOARD_CSS ?? ''}${MAP_STYLE}</style>
      <ha-card>
        <div class="mb frost">
          <div class="page">
            <p class="message dim" hidden></p>
            <section class="status" hidden>
              <div class="statusTop">
                <div class="ring">
                  <svg viewBox="0 0 80 80"><circle cx="40" cy="40" r="34" class="ringBg"/><circle cx="40" cy="40" r="34" class="ringFill"/></svg>
                  <div><strong class="percent"></strong></div>
                </div>
                <div class="headline"><h2></h2><strong class="reason" hidden></strong><span class="sub dim"></span></div>
              </div>
              <div class="factBlock">
                <div class="facts info"></div>
                <div class="facts temps"></div>
              </div>
              <div class="controls">
                <button class="reset" data-button="reset_emergency" hidden></button>
                <button class="main" data-button="start"></button>
                <button data-button="pause"></button>
                <button data-button="home"></button>
                <button data-button="skip"></button>
                <button class="skipPathButton" data-button="skip_path" hidden></button>
                <button class="resetJobButton" data-button="ask_reset_job" hidden></button>
                <div class="resetJob" hidden>
                  <span></span>
                  <button class="reset" data-button="reset_job"></button>
                  <button data-button="cancel_reset_job"></button>
                </div>
                <div class="leftovers" hidden></div>
              </div>
              <div class="wordmark"><strong>mow</strong>bite</div>
            </section>
            <section class="map" hidden></section>
            <section class="today" hidden>
              <div class="todayHead"><h2></h2></div>
              <div class="missed schedMissed" hidden>${ICONS.warning}<a><strong></strong><span></span></a><button data-button="close_missed">×</button></div>
              <div class="missed maintenance" hidden>${ICONS.warning}<a><strong></strong><span></span></a></div>
              <div class="todayNumbers" hidden>
                <div><strong class="mowed"></strong><span class="mowedLabel"></span></div>
                <div><strong class="runCount"></strong><span class="runLabel"></span></div>
                <div class="problemsBox"><strong class="problemCount"></strong><span class="problemLabel"></span></div>
              </div>
              <span class="nextRun" hidden></span>
              <span class="label runsLabel" hidden></span>
              <div class="runList" hidden></div>
            </section>
          </div>
        </div>
      </ha-card>`;
    this.shadowRoot.querySelector('.page').addEventListener('click', (ev) => {
      const button = ev.target.closest('button');
      if (button && !button.disabled && button.dataset.button) this._press(button.dataset.button);
    });
    this._built = true;
    this._map?.destroy();
    this._map = new MowbiteMap(this.shadowRoot.querySelector('.map'));
    if (this._art) this._map.setArt(this._art.art);
    this._map.setIcons(this._settings?.icons);
    this._map.setLook(this._settings);
    this._map.setBody(this._body ?? null);
    if (this._mapData) this._map.setMap(this._mapData);
    if (this._track) this._map.setTrack(this._track);
    if (this._planning) {
      this._map.setLeftovers(this._planning.leftovers);
      this._map.setTight(this._planning.tight);
    }
    this._applyLook();
    this._update();
  }

  _press(button) {
    const state = this._data?.state;
    switch (button) {
      case 'start':
        return this._action('start');
      case 'pause':
        // paused: the pause button turns into continue
        return this._action(state?.current_state === 'PAUSED' && this._has('continue') ? 'continue' : 'pause');
      case 'home':
        return this._action('home');
      case 'skip':
        return this._toggleSkip('skip_area');
      case 'skip_path':
        return this._toggleSkip('skip_path');
      case 'ask_reset_job':
        this._confirmReset = true;
        return this._update();
      case 'cancel_reset_job':
        this._confirmReset = false;
        return this._update();
      case 'reset_job':
        this._confirmReset = false;
        this._update();
        return this._action('reset_job');
      case 'reset_emergency':
        return this._action('reset_emergency');
      case 'check_leftovers':
        return this._checkLeftovers();
      case 'mow_leftovers':
        return this._mowLeftovers();
      case 'close_leftovers':
        this._leftovers = {};
        return this._update();
      case 'close_missed':
        return this._dash?.closeMissed(this._dash.missed?.t);
      case 'more_runs':
        this._moreRuns = !this._moreRuns;
        return this._update();
    }
  }

  // a tapped skip (area or path) goes out after a few seconds, a second tap takes it back
  _toggleSkip(name) {
    if (this._skip?.name === name) {
      this._stopSkip();
      return this._update();
    }
    this._stopSkip();
    this._skip = {name, left: SKIP_DELAY};
    this._skipTimer = setInterval(() => {
      if (this._skip.left > 1) {
        this._skip.left--;
        this._update();
        return;
      }
      this._stopSkip();
      this._update();
      this._action(name);
    }, 1000);
    this._update();
  }

  _stopSkip() {
    clearInterval(this._skipTimer);
    this._skipTimer = null;
    this._skip = null;
  }

  // what the last finished mow left unmowed, as the MowBite Planner finds it on its track (the app's LeftoversCard)
  async _checkLeftovers() {
    const app = this._app;
    if (!app) return;
    this._leftovers = {busy: true};
    this._update();
    try {
      const found = await app.leftovers.askLeftovers({jobId: this._leftoverJob()});
      this._leftovers = found ? {found} : {};
    } catch (err) {
      this._leftovers = {error: this._leftoversError(err)};
    }
    this._update();
  }

  async _mowLeftovers() {
    this._leftovers = {...this._leftovers, busy: true};
    this._update();
    try {
      await this._hass.callWS({type: 'mowbite/action', entity_id: this._config.entity, action: 'mow_leftovers'});
      this._leftovers = {found: this._leftovers.found, started: true};
    } catch (err) {
      this._leftovers = {...this._leftovers, busy: false, error: err?.code === 'planner_failed' ? this._t("The planner didn't take it.") : err?.message || String(err)};
    }
    this._update();
  }

  _leftoversError(err) {
    return err?.code !== 'timeout' && err?.message ? err.message : this._t('The mower did not answer.');
  }

  // the last finished mow, for what it left
  _leftoverJob() {
    return this._dash?.recent?.latest.find((r) => r.outcome === 'done' && r.areas.length > 0 && r.jobId)?.jobId;
  }

  _has(name) {
    return this._data?.actions?.[ACTION_IDS[name]] === true;
  }

  // charger: on the charging contacts whatever the state (mower_logic's is_charging, or the voltage on them)
  _headline(state, docked, charger, chargeState, area) {
    if (state.emergency) return {title: this._t('Emergency stop'), tone: 'error'};
    // left on in the dock it says so, it's why the map shows
    if (state.current_state === 'AREA_RECORDING')
      return {title: charger ? this._t('Recording mode, in the dock') : this._t('Recording an area'), tone: 'live'};
    if (docked)
      return chargeState === 'Done'
        ? {title: this._t('Charged, in the dock'), tone: 'good'}
        : {title: this._t('Charging in the dock'), tone: 'good'};
    switch (state.current_state) {
      case 'MOWING':
        return {title: area ? this._t('Mowing {area}', {area}) : this._t('Mowing'), tone: 'live'};
      case 'DOCKING':
        return {title: this._t('Heading home'), tone: 'live'};
      case 'UNDOCKING':
        return {title: this._t('Leaving the dock'), tone: 'live'};
      case 'PAUSED':
        return {title: this._t('Paused'), tone: 'warn'};
      case 'IDLE':
        return {title: this._t('Waiting on the lawn'), tone: 'warn'};
      default:
        return {title: String(state.current_state ?? '').toLowerCase().replace(/_/g, ' '), tone: 'neutral'};
    }
  }

  // every temperature with its limit: the one OpenMower gives the sensor, 70 °C without one
  _temperatures(infos, values) {
    const rank = (id) => {
      const i = TEMP_ORDER.findIndex(([k]) => k === id);
      return i < 0 ? TEMP_ORDER.length : i;
    };
    return Object.entries(infos)
      .filter(([id, info]) => info.value_description === 'TEMPERATURE' && Number.isFinite(Number(values[id])))
      .map(([id, info]) => {
        const value = Number(values[id]);
        const limit =
          info.max_value > 0 ? info.max_value : info.has_critical_high && info.upper_critical_value > 0 ? info.upper_critical_value : 70;
        const name = TEMP_ORDER.find(([k]) => k === id)?.[1];
        return {id, label: name ? this._t(name) : info.sensor_name || id, value: `${Math.round(value)} °C`, warn: value >= limit};
      })
      .sort((a, b) => rank(a.id) - rank(b.id) || a.label.localeCompare(b.label));
  }

  // two to a row, the wide ones and one left without a partner over the whole row (the app's wholeRow). the first
  // part of a value stands out, what follows after " · " is plainer
  _facts(el, facts) {
    const whole = facts.map((f) => !!f.wide);
    let single = -1;
    facts.forEach((f, i) => {
      if (f.wide && single >= 0) whole[single] = true;
      single = f.wide || single >= 0 ? -1 : i;
    });
    if (single >= 0) whole[single] = true;
    const html = facts
      .map((f, i) => {
        const [main, ...rest] = String(f.value).split(' · ');
        const cls = [f.warn ? 'warn' : '', whole[i] ? 'whole' : ''].filter(Boolean).join(' ');
        const value = `<strong>${escape(main)}${rest.length ? `<small> · ${escape(rest.join(' · '))}</small>` : ''}</strong>`;
        return `<div${cls ? ` class="${cls}"` : ''}><span>${escape(f.label)}</span>${value}${f.extra ? `<span>${escape(f.extra)}</span>` : ''}</div>`;
      })
      .join('');
    el.hidden = !facts.length;
    // only when something changed, so nothing flickers twice a second
    if (el.dataset.html !== html) {
      el.innerHTML = html;
      el.dataset.html = html;
    }
  }

  _html(el, html) {
    if (el.dataset.html !== html) {
      el.innerHTML = html;
      el.dataset.html = html;
    }
  }

  _button(button, {icon, label, disabled}) {
    this._html(button, `${icon ? ICONS[icon] : ''}${escape(label)}`);
    button.disabled = disabled;
  }

  _update() {
    if (!this._built) return;
    const $ = (s) => this.shadowRoot.querySelector(s);
    const data = this._data;
    const state = data?.state;
    const message = $('.message');
    const status = $('.status');
    const dash = this._dash;
    const app = this._app;

    if (this._error || !state) {
      message.hidden = false;
      message.textContent = this._error ?? (data?.connected ? this._t('waiting for the mower…') : this._t('connecting…'));
      status.hidden = true;
      $('.map').hidden = true;
      $('.today').hidden = true;
      return;
    }
    message.hidden = true;
    status.hidden = this._config.status === false;

    const sensors = data.sensors ?? {};
    const live = !!data.available;
    const current = state.current_state ?? '';
    const driving = DRIVING.has(current);
    const charger = !!state.is_charging || Number(sensors.om_v_charge) > 20;
    const docked = current === 'IDLE' && charger;
    const battery = Math.round((state.battery_percentage ?? 0) * 100);
    const chargeState = sensors.om_charge_state;
    const charging = docked && chargeState !== 'Done';
    const emergency = !!state.emergency;
    dash?.setState(current, emergency);
    // the area being mowed: from the day's events like the app, else what the integration knows
    const events = dash?.recent?.today ?? [];
    const area = current === 'MOWING' ? (events.filter((e) => e.type === 'AREA').at(-1)?.area_name ?? data.area) : undefined;
    const head = this._headline(state, docked, charger, chargeState, area);

    status.className = `status ${live ? `tone-${head.tone}` : 'stale'}`;

    // the map like on the app's overview: while the mower drives, or always if set so. the card's own setting first,
    // then the integration's, then the app's
    let mode = !this._config.map || this._config.map === 'integration' ? (data.map_mode ?? 'app') : this._config.map;
    if (mode === 'app') mode = this._settings?.dashboard?.map ?? 'auto';
    const showMap = !!this._mapData && mode !== 'never' && (mode === 'always' || driving);
    const mapSection = $('.map');
    const appeared = showMap && mapSection.hidden;
    mapSection.hidden = !showMap;
    $('.page').classList.toggle('withMap', showMap && this._config.status !== false);
    const progress = dash?.progress(state, this._mapData) ?? null;
    if (this._map) {
      if (appeared) this._map.refresh();
      // it follows the mower while it drives, like the app
      if (driving !== this._wasDriving) this._map.setFollow(driving);
      this._wasDriving = driving;
      this._map.setLight(this._config.blur === false);
      this._map.setPose(data.position ?? state.pose, emergency);
      this._map.setTodo(progress?.todo ?? null);
      if (dash) this._map.setLife({...dash.life(this._settings, data.datum, driving), rain: !!state.rain_detected, driving});
    }

    // a waiting skip is dropped when there's nothing to skip anymore or the connection went
    if (this._skip && (!live || current !== 'MOWING' || !this._has(this._skip.name))) this._stopSkip();

    const ring = $('.ring');
    ring.className = `ring ring-${batteryColor(battery)}`;
    const c = 2 * Math.PI * 34;
    $('.ringFill').setAttribute('stroke-dasharray', `${(c * battery) / 100} ${c}`);
    $('.percent').textContent = `${battery}%`;
    $('.headline h2').textContent = head.title;

    // why the emergency stop is on, from the mower's log
    const reason = $('.reason');
    const why = emergency ? dash?.reasons : null;
    reason.hidden = !why?.length;
    if (why?.length && app) {
      const text = app.events.emergencyText(why);
      reason.textContent = text.charAt(0).toUpperCase() + text.slice(1);
    }

    const sub = $('.sub');
    if (live) {
      sub.className = 'sub dim';
      sub.textContent = emergency
        ? this._t('Release the mower, then reset the emergency to drive again.')
        : data.since
          ? this._t('since {time}', {time: this._clock(data.since)})
          : '';
    } else {
      sub.className = 'sub offline';
      const time = data.state_time ? this._clock(data.state_time, true) : '–';
      sub.textContent = this._t(data.connected ? 'No data from the mower since {time}' : 'Connection lost, last data at {time}', {time});
    }

    const acc = state.pose?.pos_accuracy;
    const gps = gpsQuality(acc, data.max_position_accuracy ?? undefined);
    const num = (id) => (sensors[id] !== undefined && sensors[id] !== '' ? Number(sensors[id]) : undefined);
    const facts = [];
    // standing still the mower switches gps off, "off" there says nothing
    if (driving || gps !== 'none') {
      facts.push({
        label: 'GPS',
        value: gps === 'none' ? this._t(driving ? 'no fix' : 'off') : `${this._fmt(acc * 100, 1)} cm · ${this._t(GPS_QUALITY_LABEL[gps])}`,
        // only an rtk fix is good while driving
        warn: driving && gps !== 'fix',
      });
    }
    if (driving) facts.push({label: this._t('Speed'), value: `${this._fmt(this._speed, 2)} m/s`});
    if (progress?.leftovers) {
      facts.push({label: this._t('Progress'), value: this._t('leftovers of the last mow'), wide: true});
    } else if (progress) {
      const left = progress.secondsLeft !== null ? ` · ${this._t('{time} left', {time: this._duration(progress.secondsLeft)})}` : '';
      facts.push({label: this._t('Progress'), value: `${Math.round(progress.fraction * 100)} %${left}`, wide: true});
    }
    if (charging && num('om_charge_current') !== undefined)
      facts.push({label: this._t('Charging'), value: `${this._fmt(num('om_charge_current'), 1)} A`});
    if (num('om_v_battery') !== undefined) facts.push({label: this._t('Battery'), value: `${this._fmt(num('om_v_battery'), 1)} V`});
    if (state.rain_detected) facts.push({label: this._t('Rain'), value: this._t('detected'), warn: true});
    // the app and the correction data for gps come over it
    if (dash?.wifi !== undefined && app) {
      const level = app.coverage.wifiLevel(dash.wifi);
      facts.push({label: this._t('Wi-Fi'), value: `${dash.wifi} dBm · ${this._t(app.status.WIFI_LEVEL_LABEL[level])}`, warn: level === 'bad'});
    }
    this._facts($('.facts.info'), facts);
    this._facts($('.facts.temps'), this._temperatures(data.sensor_infos ?? {}, sensors));

    // the mower still offers start while the emergency stop is active, it has to be reset first
    const off = (name) => !live || !this._has(name) || emergency;
    const button = (name) => $(`[data-button="${name}"]`);
    const reset = button('reset_emergency');
    reset.hidden = !emergency;
    this._button(reset, {icon: 'warning', label: this._t('Reset emergency'), disabled: !live});
    this._button(button('start'), {icon: 'play', label: this._t('Start'), disabled: off('start')});
    const paused = current === 'PAUSED' && this._has('continue');
    this._button(
      button('pause'),
      paused
        ? {icon: 'play', label: this._t('Continue'), disabled: off('continue')}
        : {icon: 'pause', label: this._t('Pause'), disabled: off('pause')},
    );
    this._button(button('home'), {icon: 'home', label: this._t('Go home'), disabled: off('home')});
    const undo = (name) => (this._skip?.name === name ? this._t('Undo ({n} s)', {n: this._skip.left}) : null);
    this._button(button('skip'), {icon: 'skip', label: undo('skip_area') ?? this._t('Skip area'), disabled: off('skip_area')});
    const skipPath = button('skip_path');
    skipPath.hidden = !(live && current === 'MOWING' && this._has('skip_path') && !emergency);
    skipPath.title = this._t('The mower leaves the rest of the outline pass or lanes it is on and goes on with the next ones.');
    this._button(skipPath, {icon: 'skip', label: undo('skip_path') ?? this._t('Skip this path'), disabled: false});

    const canResetJob = live && this._has('reset_job') && !emergency;
    if (!canResetJob) this._confirmReset = false;
    button('ask_reset_job').hidden = !canResetJob || this._confirmReset;
    button('ask_reset_job').textContent = this._t('Drop the interrupted job');
    const confirm = $('.resetJob');
    confirm.hidden = !canResetJob || !this._confirmReset;
    confirm.querySelector('span').textContent = this._t('Drop the interrupted job? The next start mows from the beginning.');
    button('reset_job').textContent = this._t('Drop it');
    button('cancel_reset_job').textContent = this._t('Cancel');

    this._updateLeftovers($('.leftovers'), live && this._has('start') && !emergency);
    this._updateToday($('.today'), data);
  }

  // idle in the dock: what the last mow left, and mowing just that (with the MowBite Planner)
  _updateLeftovers(el, shown) {
    const known = !!this._dash?.methods?.has('planner.leftovers');
    el.hidden = !shown || !known || this._config.leftovers === false;
    if (el.hidden) return;
    const live = !!this._data?.available;
    const state = this._leftovers ?? {};
    const found = state.found;
    const map = this._mapData;
    const name = (id) => map?.areas?.find((a) => a.id === id)?.properties?.name || this._t('unnamed');
    const m2 = (v) => this._fmt(v, v < 1 ? 2 : 1);
    const left = found?.areas.filter((a) => a.passes > 0) ?? [];
    let html = '';
    if (!found) {
      html += `<button class="leftoversButton" data-button="check_leftovers"${!live || state.busy ? ' disabled' : ''}>${escape(
        state.busy ? this._t('Looking at the track…') : this._t('Check the last mow for leftovers'),
      )}</button>`;
    } else {
      const notes = found.areas.filter((a) => a.passes === 0 && a.message);
      html += `<span>${escape(
        left.length === 0
          ? this._t('Nothing worth another pass is left from the last mow.')
          : this._t('{m2} m² left in {n} passes: {areas}.', {
              m2: m2(found.m2),
              n: found.passes,
              areas: left.map((a) => `${name(a.id)} (${m2(a.m2)} m²)`).join(', '),
            }),
      )}${notes.length ? `<small>${escape(notes.map((a) => `${name(a.id)}: ${a.message}`).join(' · '))}</small>` : ''}</span>`;
      if (left.length > 0 && !state.started)
        html += `<button class="leftoversButton" data-button="mow_leftovers"${!live || state.busy ? ' disabled' : ''}>${escape(
          state.busy ? this._t('Starting…') : this._t('Mow just the leftovers'),
        )}</button>`;
      if (state.started) html += `<small>${escape(this._t('Started. The mower drives only those passes and skips the areas with nothing left.'))}</small>`;
      else html += `<button class="leftoversButton" data-button="close_leftovers"${state.busy ? ' disabled' : ''}>${escape(this._t('Close'))}</button>`;
    }
    if (state.error) html += `<span class="error">${escape(state.error)}</span>`;
    this._html(el, html);
  }

  // today: the left out start, maintenance due, what was mowed, the next start and the last runs (the app's "Today")
  _updateToday(el, data) {
    const dash = this._dash;
    const app = this._app;
    const recent = dash?.recent;
    const missed = dash?.missed ?? null;
    const planned = dash?.planned(data.datum) ?? null;
    const due = dash?.due ?? [];
    el.hidden = this._config.today === false || !app || !(recent || planned || missed || due.length > 0);
    if (el.hidden) return;
    const $ = (s) => el.querySelector(s);
    const {dates, events, stats, schedule} = app;
    $('.todayHead h2').textContent = this._t('Today');

    const missedBox = $('.schedMissed');
    missedBox.hidden = !missed;
    if (missed) {
      const today = dates.dayKey(new Date(missed.t * 1000)) === dates.dayKey(new Date());
      missedBox.querySelector('strong').textContent = today
        ? this._t('Scheduled start at {time}', {time: dates.clock(missed.t)})
        : this._t('Scheduled start yesterday at {time}', {time: dates.clock(missed.t)});
      missedBox.querySelector('a span').textContent = this._t(schedule.scheduleLogText(missed), {detail: missed.detail ?? ''});
      missedBox.querySelector('button').title = this._t('Close');
    }
    const dueBox = $('.maintenance');
    dueBox.hidden = !due.length;
    if (due.length) {
      dueBox.querySelector('strong').textContent = this._t('Maintenance due');
      dueBox.querySelector('a span').textContent = due
        .map((d) => `${this._t(stats.PARTS[d.key].label)}: ${this._t('{used} of {due} h', {used: this._fmt(d.used, d.used < 10 ? 1 : 0), due: d.due})}`)
        .join(' · ');
    }

    const numbers = $('.todayNumbers');
    numbers.hidden = !recent;
    const runs = recent?.runs ?? [];
    if (recent) {
      const mowed = runs.reduce((s, r) => s + r.bladeSeconds, 0);
      const problems = runs.reduce((s, r) => s + r.problems, 0);
      $('.mowed').textContent = mowed ? dates.duration(mowed) : '0 min';
      $('.mowedLabel').textContent = this._t('mowed');
      $('.runCount').textContent = runs.length;
      $('.runLabel').textContent = runs.length === 1 ? this._t('run') : this._t('runs');
      $('.problemsBox').classList.toggle('bad', problems > 0);
      $('.problemCount').textContent = problems;
      $('.problemLabel').textContent = problems === 1 ? this._t('problem') : this._t('problems');
    }
    const next = $('.nextRun');
    next.hidden = !planned;
    if (planned) next.textContent = this._t('Next start: {when}', {when: `${dates.dayLabel(planned)}, ${dates.clock(planned.getTime() / 1000)}`});

    // the one under way is the status above
    const finished = (recent?.latest ?? []).filter((r) => r.outcome !== 'running');
    $('.runsLabel').hidden = !finished.length;
    $('.runsLabel').textContent = finished.length > 1 ? this._t('Last runs') : this._t('Last run');
    const list = $('.runList');
    list.hidden = !finished.length;
    const shown = finished.slice(0, this._moreRuns ? 6 : 3).map((run) => {
      const outcome = events.OUTCOMES[run.outcome];
      const day = new Date(run.start * 1000);
      const today = dates.dayKey(day) === dates.dayKey(new Date());
      const where =
        (run.areas.join(', ') || this._t('no area')) +
        (run.bladeSeconds > 0 ? ` · ${this._t('mowed {time}', {time: dates.duration(run.bladeSeconds)})}` : '');
      return (
        `<div class="lastRun run-${outcome.tone}"><div><strong>${escape(`${today ? '' : `${dates.dayLabel(day)}, `}${dates.clock(run.start)} – ${dates.clock(run.end)}`)}</strong>` +
        `<span class="dim">${escape(where)}</span></div><span class="badge">${escape(this._t(outcome.label))}</span></div>`
      );
    });
    if (finished.length > 3)
      shown.push(`<button class="moreRuns" data-button="more_runs">${escape(this._moreRuns ? this._t('Show less') : this._t('Show more'))}</button>`);
    this._html(list, shown.join(''));
  }

  _duration(seconds) {
    return this._app ? this._app.dates.duration(seconds) : `${Math.round(seconds / 60)} min`;
  }
}

// home assistant's frontend swaps window.customElements for a scoped registry while it starts. this file can come
// before that (the start page loads it early), and an element defined then is missing from the registry the dashboard
// asks: "configuration error". so the card waits for the frontend's own elements before it defines itself
function defineCard() {
  if (customElements.get('mowbite-card')) return;
  customElements.define('mowbite-card', MowbiteCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'mowbite-card',
    name: 'MowBite for OpenMower',
    description: 'Your OpenMower the way the MowBite app shows it',
    preview: true,
    documentationURL: 'https://github.com/mkaaaaaay/mowbite-ha',
  });
}

// asked again and again: window.customElements is looked up each time, so this sees the registry once it's swapped
const startedAt = Date.now();
(function waitForFrontend() {
  if (customElements.get('ha-card') || Date.now() - startedAt > 30000) defineCard();
  else setTimeout(waitForFrontend, 100);
})();
