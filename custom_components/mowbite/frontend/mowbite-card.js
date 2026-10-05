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
};

// paused counts too, the mower is standing somewhere on the lawn then
const DRIVING = new Set(['MOWING', 'PAUSED', 'DOCKING', 'UNDOCKING']);
// skipping an area drops what's left of it, so it goes out only after a few seconds and a second tap takes it back
const SKIP_DELAY = 4;

// every temperature of the mower in a fixed order, the blade side first, then the wheels, unknown ones after them
const TEMP_ORDER = [
  ['om_mow_motor_temp', 'Mow motor'],
  ['om_mow_esc_temp', 'Mow controller'],
  ['om_left_esc_temp', 'Left drive controller'],
  ['om_right_esc_temp', 'Right drive controller'],
];

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
  'Skip area': 'Überspringen',
  Continue: 'Weiter',
  'Undo ({n} s)': 'Rückgängig ({n} s)',
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

  /* the app's looks, from its globals.css. frost is dark with milky glass cards */
  .mb {
    container: card / inline-size;
    color: var(--foreground);
    font-family: Arial, Helvetica, sans-serif;
    -webkit-font-smoothing: antialiased;
    user-select: none;
    -webkit-user-select: none;
  }

  .mb.light {
    --background: #cdd6cf;
    --foreground: #1c2420;
    --card: rgba(255, 255, 255, 0.42);
    --card-border: rgba(255, 255, 255, 0.6);
    --card-blur: blur(5px) saturate(130%);
    --card-shadow: 0 1px 2px rgba(20, 40, 30, 0.06), 0 6px 20px rgba(20, 40, 30, 0.07);
    --btn-3d: inset 0 1px 0 rgba(255, 255, 255, 0.75), 0 1px 1px rgba(20, 40, 30, 0.1), 0 2px 6px rgba(20, 40, 30, 0.08);
    --btn-3d-hover: inset 0 1px 0 rgba(255, 255, 255, 0.85), 0 2px 2px rgba(20, 40, 30, 0.1), 0 6px 14px rgba(20, 40, 30, 0.12);
    --text-secondary: #4f5b54;
    --accent: #2f6fbd;
    --warning: #a8780f;
    --error: #c93a3e;
    --success: #2e8a47;
  }

  .mb.dark,
  .mb.frost {
    --background: #101114;
    --foreground: #f1f1f1;
    --card: rgba(255, 255, 255, 0.05);
    --card-border: rgba(255, 255, 255, 0.09);
    --card-blur: blur(3px) saturate(140%);
    --card-shadow: none;
    --btn-3d: inset 0 1px 0 rgba(255, 255, 255, 0.1), 0 1px 1px rgba(0, 0, 0, 0.35), 0 2px 6px rgba(0, 0, 0, 0.25);
    --btn-3d-hover: inset 0 1px 0 rgba(255, 255, 255, 0.14), 0 2px 2px rgba(0, 0, 0, 0.35), 0 6px 14px rgba(0, 0, 0, 0.35);
    --text-secondary: #9a9ba0;
    --accent: #5b9df0;
    --warning: #d4ac4a;
    --error: #ff6669;
    --success: #4cbf72;
    color-scheme: dark;
  }

  .mb.dark {
  }

  .mb.frost {
    --background: #1a1c22;
    --card: rgba(235, 240, 255, 0.12);
    --card-border: rgba(255, 255, 255, 0.2);
    --card-blur: blur(18px) saturate(160%);
    --card-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12), 0 6px 24px rgba(0, 0, 0, 0.28);
    --text-secondary: #a9abb2;
  }

  .page {
    display: grid;
    gap: 16px;
  }

  /* the app's name, small and quiet in the glass's bottom edge */
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

  /* a phone has less room than the app gets: a bit less padding so four buttons still fit */
  @container card (max-width: 420px) {
    .status {
      padding: 14px;
    }
  }

  .dim {
    color: var(--text-secondary);
  }

  .message {
    font-size: 14px;
  }

  .status {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 18px;
    border-radius: 18px;
    border: 1px solid var(--card-border);
    /* a thin colored line on top says at a glance whether all is well */
    border-top: 3px solid var(--tone, var(--card-border));
    background: var(--card);
    box-shadow: var(--card-shadow, none);
    backdrop-filter: var(--card-blur, none);
    -webkit-backdrop-filter: var(--card-blur, none);
  }

  .tone-good {
    --tone: var(--success);
  }

  .tone-live {
    --tone: var(--accent);
  }

  .tone-warn {
    --tone: var(--warning);
  }

  .tone-error {
    --tone: var(--error);
  }

  .tone-neutral {
    --tone: var(--card-border);
  }

  /* offline or no fresh state: everything in the card is old, the line under the headline says since when */
  .stale .ring,
  .stale .headline h2,
  .stale .facts {
    opacity: 0.45;
  }

  .offline {
    color: var(--warning);
    font-weight: 600;
  }

  .statusTop {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .headline {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .headline h2 {
    margin: 0;
    font-size: 22px;
    line-height: 1.2;
  }

  .headline span {
    font-size: 13px;
  }

  .ring {
    position: relative;
    flex: none;
    width: 84px;
    height: 84px;
  }

  .ring svg {
    width: 100%;
    height: 100%;
    transform: rotate(-90deg);
  }

  .ring circle {
    fill: none;
    stroke-width: 7;
  }

  .ringBg {
    stroke: rgba(128, 128, 128, 0.2);
  }

  .ringFill {
    stroke: var(--ring);
    stroke-linecap: round;
    transition: stroke-dasharray 0.6s;
  }

  .ring-success {
    --ring: var(--success);
  }

  .ring-warning {
    --ring: var(--warning);
  }

  .ring-error {
    --ring: var(--error);
  }

  .ring > div {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .ring strong {
    font-size: 19px;
  }

  .ring span {
    font-size: 10px;
    color: var(--text-secondary);
  }

  .facts {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .facts:empty {
    display: none;
  }

  .facts div {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 8px;
    background: rgba(128, 128, 128, 0.1);
    font-size: 13px;
  }

  .facts span {
    color: var(--text-secondary);
    font-size: 12px;
  }

  .facts .warn {
    background: color-mix(in srgb, var(--warning) 16%, transparent);
    color: var(--warning);
  }

  .controls {
    container: controls / inline-size;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
  }

  .controls button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px 10px;
    border-radius: 12px;
    border: 1px solid var(--card-border);
    background: rgba(128, 128, 128, 0.08);
    color: var(--foreground);
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.15;
    text-align: center;
    min-width: 0;
    overflow-wrap: anywhere;
    hyphens: auto;
    cursor: pointer;
    box-shadow: var(--btn-3d);
    -webkit-tap-highlight-color: transparent;
    transition:
      transform 0.08s ease-out,
      filter 0.08s ease-out,
      box-shadow 0.08s ease-out;
  }

  .controls button svg {
    flex-shrink: 0;
  }

  .controls button:disabled {
    opacity: 0.35;
    cursor: default;
  }

  /* buttons give way under the finger like a real one */
  .controls button:active:not(:disabled) {
    transform: translateY(1px) scale(0.96);
    filter: brightness(0.85);
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.35);
  }

  @media (hover: hover) and (prefers-reduced-motion: no-preference) {
    .controls button:not(:disabled):hover {
      --btn-3d: var(--btn-3d-hover);
      transform: translateY(-1px);
    }
  }

  .controls .main:not(:disabled) {
    border-color: color-mix(in srgb, var(--accent) 70%, transparent);
    background: color-mix(in srgb, var(--accent) 35%, transparent);
    color: var(--foreground);
  }

  .controls .reset {
    grid-column: 1 / -1;
    border-color: var(--error);
    background: color-mix(in srgb, var(--error) 18%, transparent);
    color: var(--error);
  }

  .controls .resetJobButton {
    grid-column: 1 / -1;
    padding: 8px;
    border-style: dashed;
    font-size: 13px;
    color: var(--text-secondary);
  }

  .controls .resetJob {
    grid-column: 1 / -1;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }

  .controls .resetJob span {
    flex: 1 1 100%;
  }

  .controls .resetJob button {
    flex: 1;
  }

  [hidden] {
    display: none !important;
  }

  /* no blur behind the glass: an old tablet draws that slowly, the glass is then only see-through */
  .mb.noblur {
    --card-blur: none;
  }

  /* by the width of the card, not the screen: four buttons side by side need about 600px for a label next to its icon */
  @container controls (max-width: 640px) {
    .controls button:not(.reset) {
      flex-direction: column;
      gap: 4px;
      padding: 10px 4px;
      font-size: 12px;
    }
  }
`;

// ---- the map, drawn the way the MowBite app draws it (MapView, mapIcons)

// the app's map colours, its settings change them
const MAP_COLORS = {
  mower: '#ff1fa3',
  dock: '#2196f3',
  track: '#ff1fa3',
  transit: '#ff1fa3',
  mow: '#4caf50',
  unmowed: '#ffb300',
  nav: '#29b6f6',
  obstacle: '#ef5350',
  body: '#ff1fa3',
  swath: '#ffffff',
};

// half the mower's length, m, when the app draws it at its real size
const MOWER_SIZE = 0.4;
// icons that don't grow with the map are this many pixels, times the size set in the app
const ICON_PX = 8;

const BLACK = '#262626';
const ORANGE = '#f57c00';
const WHEEL = '#9e9e9e';
const SILVER = '#cfd8dc';
const STOP = '#e53935';
const LINE = 'stroke="#000" stroke-width="0.75" stroke-opacity="0.6"';

// the red stop button, blinking on an emergency stop
const stopButton = (x, w, h, emergency) =>
  `<rect x="${x}" y="${-h / 2}" width="${w}" height="${h}" rx="0.05" fill="${STOP}" ${LINE}>${
    emergency ? `<animate attributeName="fill" values="${STOP};#fff;${STOP}" dur="0.8s" repeatCount="indefinite"/>` : ''
  }</rect>`;
const rearWheels = (x, len, inner) =>
  `<rect x="${x}" y="-1" width="${len}" height="${1 - inner}" rx="0.04" fill="${WHEEL}" ${LINE}/>` +
  `<rect x="${x}" y="${inner}" width="${len}" height="${1 - inner}" rx="0.04" fill="${WHEEL}" ${LINE}/>`;
const mouth = (deg) => {
  const a = (deg * Math.PI) / 180;
  const x = Math.cos(a).toFixed(3);
  const y = Math.sin(a).toFixed(3);
  return `M0,0 L${x},${y} A1,1 0 1,1 ${x},${-y} Z`;
};

// mower icons face +x and span about -1..1. a real mower from above (fit: its width over its length) is drawn that
// much narrower. the app's side views and figures (gardener, OpenMower) aren't here, they get the arrowhead
const MAP_MOWERS = {
  triangle: {draw: () => '<polygon points="1,0 -0.6,0.6 -0.6,-0.6" fill="var(--c-mower)" stroke="#fff" stroke-width="0.5"/>'},
  arrow: {
    draw: () =>
      '<path d="M1,0 L-0.2,-0.8 L-0.2,-0.3 L-1,-0.3 L-1,0.3 L-0.2,0.3 L-0.2,0.8 Z" fill="var(--c-mower)" stroke="#fff" stroke-width="0.5"/>',
  },
  robot: {
    draw: () =>
      '<rect x="-1" y="-0.95" width="0.55" height="0.3" rx="0.1" fill="#222"/><rect x="-1" y="0.65" width="0.55" height="0.3" rx="0.1" fill="#222"/>' +
      '<rect x="-0.95" y="-0.7" width="1.9" height="1.4" rx="0.45" fill="var(--c-mower)" stroke="#fff" stroke-width="0.5"/>' +
      '<circle cx="0.15" cy="0" r="0.32" fill="rgba(0,0,0,0.35)"/><circle cx="0.62" cy="0" r="0.12" fill="#fff"/>',
  },
  dot: {
    draw: () =>
      '<line x1="0" y1="0" x2="1.1" y2="0" stroke="var(--c-mower)" stroke-width="2" stroke-linecap="round"/><circle r="0.6" fill="var(--c-mower)" stroke="#fff" stroke-width="0.5"/>',
  },
  chomper: {
    draw: () =>
      `<path d="${mouth(35)}" fill="var(--c-mower)" stroke="#000" stroke-width="0.5"><animate attributeName="d" values="${mouth(35)};${mouth(3)};${mouth(35)}" dur="0.4s" repeatCount="indefinite"/></path><circle cx="0.05" cy="-0.5" r="0.12" fill="#000"/>`,
  },
  rocket: {
    draw: () =>
      '<path d="M-0.75,-0.18 L-1.25,0 L-0.75,0.18 Z" fill="#ffb300"><animate attributeName="d" values="M-0.75,-0.18 L-1.25,0 L-0.75,0.18 Z;M-0.75,-0.2 L-1.45,0 L-0.75,0.2 Z;M-0.75,-0.18 L-1.25,0 L-0.75,0.18 Z" dur="0.25s" repeatCount="indefinite"/></path>' +
      '<path d="M-0.55,-0.3 L-0.95,-0.65 L-0.95,-0.2 Z M-0.55,0.3 L-0.95,0.65 L-0.95,0.2 Z" fill="#555"/>' +
      '<path d="M1,0 C0.6,-0.45 -0.2,-0.4 -0.8,-0.3 L-0.8,0.3 C-0.2,0.4 0.6,0.45 1,0 Z" fill="var(--c-mower)" stroke="#fff" stroke-width="0.5"/>' +
      '<circle cx="0.25" cy="0" r="0.15" fill="#9be7ff" stroke="#fff" stroke-width="0.3"/>',
  },
  yf500: {
    fit: 42 / 57,
    draw: (emergency) =>
      rearWheels(-0.96, 0.52, 0.84) +
      `<rect x="-1" y="-0.86" width="2" height="1.72" rx="0.14" fill="${BLACK}" ${LINE}/>` +
      `<path d="M-0.9,-0.74 L0.7,-0.74 Q0.92,-0.72 0.94,-0.5 L0.94,0.5 Q0.92,0.72 0.7,0.74 L-0.9,0.74 Q-0.96,0.74 -0.96,0.66 L-0.96,-0.66 Q-0.96,-0.74 -0.9,-0.74 Z" fill="${ORANGE}" ${LINE}/>` +
      `<rect x="0.08" y="-0.36" width="0.5" height="0.72" rx="0.08" fill="#ef6c00" ${LINE}/>` +
      `<circle cx="-0.32" cy="0" r="0.17" fill="${BLACK}" ${LINE}/><circle cx="-0.32" cy="0" r="0.07" fill="${WHEEL}"/>` +
      (emergency
        ? `<circle cx="-0.32" cy="0" r="0.17" fill="none" stroke="${STOP}" stroke-width="2"><animate attributeName="stroke-opacity" values="1;0;1" dur="0.8s" repeatCount="indefinite"/></circle>`
        : '') +
      `<rect x="0.95" y="-0.32" width="0.05" height="0.18" fill="${WHEEL}"/><rect x="0.95" y="0.14" width="0.05" height="0.18" fill="${WHEEL}"/>`,
  },
  sa650: {
    fit: 39 / 57,
    draw: (emergency) =>
      rearWheels(-0.9, 0.5, 0.9) +
      `<path d="M-0.98,-0.7 Q-1,-0.96 -0.8,-0.97 L-0.45,-0.97 Q-0.3,-0.96 -0.25,-0.8 L0.55,-0.76 Q0.95,-0.7 1,-0.3 L1,0.3 Q0.95,0.7 0.55,0.76 L-0.25,0.8 Q-0.3,0.96 -0.45,0.97 L-0.8,0.97 Q-1,0.96 -0.98,0.7 Z" fill="${BLACK}" ${LINE}/>` +
      `<path d="M-0.5,-0.44 L0.38,-0.38 Q0.5,-0.36 0.5,-0.24 L0.5,0.24 Q0.5,0.36 0.38,0.38 L-0.5,0.44 Q-0.58,0.44 -0.58,0.36 L-0.58,-0.36 Q-0.58,-0.44 -0.5,-0.44 Z" fill="${ORANGE}" ${LINE}/>` +
      `<rect x="-0.18" y="-0.22" width="0.46" height="0.44" rx="0.05" fill="#3a3a3a" ${LINE}/>` +
      stopButton(-0.78, 0.18, 0.5, emergency) +
      `<path d="M0.68,-0.4 Q0.94,-0.36 0.97,-0.12 L0.97,0.12 Q0.94,0.36 0.68,0.4 Z" fill="${ORANGE}" ${LINE}/>` +
      `<rect x="0.8" y="-0.24" width="0.1" height="0.14" fill="${BLACK}"/><rect x="0.8" y="0.1" width="0.1" height="0.14" fill="${BLACK}"/>`,
  },
  nx100: {
    fit: 0.72,
    draw: (emergency) =>
      rearWheels(-0.94, 0.56, 0.86) +
      `<path d="M-0.98,-0.84 L0.55,-0.84 Q0.98,-0.8 1,-0.35 L1,0.35 Q0.98,0.8 0.55,0.84 L-0.98,0.84 Q-1,0.84 -1,0.78 L-1,-0.78 Q-1,-0.84 -0.98,-0.84 Z" fill="${ORANGE}" ${LINE}/>` +
      `<path d="M-0.92,-0.78 L0.5,-0.78 Q0.92,-0.74 0.94,-0.32 L0.94,0.32 Q0.92,0.74 0.5,0.78 L-0.92,0.78 Q-0.95,0.78 -0.95,0.72 L-0.95,-0.72 Q-0.95,-0.78 -0.92,-0.78 Z" fill="${BLACK}" ${LINE}/>` +
      `<path d="M-0.5,-0.42 L0.3,-0.36 Q0.42,-0.34 0.42,-0.22 L0.42,0.22 Q0.42,0.34 0.3,0.36 L-0.5,0.42 Q-0.56,0.42 -0.56,0.36 L-0.56,-0.36 Q-0.56,-0.42 -0.5,-0.42 Z" fill="${ORANGE}" ${LINE}/>` +
      `<rect x="-0.2" y="-0.2" width="0.4" height="0.4" rx="0.05" fill="#3a3a3a" ${LINE}/>` +
      stopButton(-0.76, 0.18, 0.46, emergency) +
      `<path d="M0.42,-0.3 L0.62,-0.24 L0.62,0.24 L0.42,0.3 Z" fill="${SILVER}" ${LINE}/>` +
      `<path d="M0.3,-0.62 L0.66,-0.5 L0.6,-0.42 L0.28,-0.5 Z" fill="${SILVER}" ${LINE}/>` +
      `<path d="M0.3,0.62 L0.66,0.5 L0.6,0.42 L0.28,0.5 Z" fill="${SILVER}" ${LINE}/>` +
      `<rect x="0.9" y="-0.3" width="0.08" height="0.2" rx="0.02" fill="${ORANGE}"/><rect x="0.9" y="0.1" width="0.08" height="0.2" rx="0.02" fill="${ORANGE}"/>`,
  },
};

// the yard force charging station from above, the tower at +x. -1..1 from the entry to the tower
const yfDots = [-1, 1]
  .flatMap((side) =>
    Array.from({length: 18}, (_, i) => {
      const row = i % 3;
      const col = Math.floor(i / 3);
      return `<rect x="${-0.92 + row * 0.12}" y="${side * (0.16 + col * 0.08) - 0.015}" width="0.03" height="0.03" fill="#111"/>`;
    }),
  )
  .join('');

// dock icons are drawn upright in the same unit box, a real station (real: its sizes in m) at its real size
const MAP_DOCKS = {
  dot: {draw: () => '<circle r="0.65" fill="var(--c-dock)"/>'},
  yardforce: {
    real: {length: 0.64, width: 0.44, pins: 0.09},
    draw: () =>
      '<path d="M-0.94,-0.69 L0.48,-0.69 L0.69,-0.6 L0.69,0.6 L0.48,0.69 L-0.94,0.69 Q-1,0.69 -1,0.63 L-1,-0.63 Q-1,-0.69 -0.94,-0.69 Z" fill="#2b2b2b" stroke="#000" stroke-width="0.75"/>' +
      '<path d="M0.66,-0.43 L-0.39,-0.64 M0.66,0.43 L-0.39,0.64" stroke="#111" stroke-width="1.5" stroke-linecap="round"/>' +
      yfDots +
      '<rect x="0.38" y="-0.22" width="0.08" height="0.04" fill="#bdbdbd"/><rect x="0.38" y="0.18" width="0.08" height="0.04" fill="#bdbdbd"/>' +
      '<path d="M0.45,-0.45 L0.95,-0.42 Q1,-0.41 1,-0.36 L1,0.36 Q1,0.41 0.95,0.42 L0.45,0.45 Q0.42,0.45 0.42,0.41 L0.42,-0.41 Q0.42,-0.45 0.45,-0.45 Z" fill="#f4612b" stroke="#000" stroke-width="0.75"/>' +
      '<rect x="0.57" y="-0.23" width="0.27" height="0.46" rx="0.05" fill="#1e1e1e"/>',
  },
  bolt: {
    draw: () =>
      '<rect x="-0.9" y="-0.9" width="1.8" height="1.8" rx="0.4" fill="var(--c-dock)" stroke="#fff" stroke-width="0.5"/><path d="M0.15,-0.7 L-0.4,0.1 L-0.02,0.1 L-0.15,0.7 L0.4,-0.1 L0.02,-0.1 Z" fill="#fff"/>',
  },
  house: {
    draw: () =>
      '<path d="M0,-1 L1,-0.1 L0.75,-0.1 L0.75,0.9 L-0.75,0.9 L-0.75,-0.1 L-1,-0.1 Z" fill="var(--c-dock)" stroke="#fff" stroke-width="0.5"/><rect x="-0.22" y="0.3" width="0.44" height="0.6" fill="#fff"/>',
  },
  plug: {
    draw: () =>
      '<circle r="0.9" fill="var(--c-dock)" stroke="#fff" stroke-width="0.5"/><rect x="-0.4" y="-0.35" width="0.2" height="0.7" rx="0.08" fill="#fff"/><rect x="0.2" y="-0.35" width="0.2" height="0.7" rx="0.08" fill="#fff"/>',
  },
  ghost: {
    draw: () =>
      '<path d="M-0.85,0.9 L-0.85,-0.1 C-0.85,-1.05 0.85,-1.05 0.85,-0.1 L0.85,0.9 L0.57,0.65 L0.28,0.9 L0,0.65 L-0.28,0.9 L-0.57,0.65 Z" fill="var(--c-dock)" stroke="#fff" stroke-width="0.5"/>' +
      '<circle cx="-0.3" cy="-0.2" r="0.22" fill="#fff"/><circle cx="0.3" cy="-0.2" r="0.22" fill="#fff"/><circle cx="-0.24" cy="-0.18" r="0.1" fill="#1a237e"/><circle cx="0.36" cy="-0.18" r="0.1" fill="#1a237e"/>',
  },
  flag: {
    draw: () =>
      '<line x1="-0.6" y1="1" x2="-0.6" y2="-1" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M-0.55,-0.95 L0.9,-0.6 L-0.55,-0.2 Z" fill="var(--c-dock)" stroke="#fff" stroke-width="0.4"/>',
  },
  shed: {
    draw: () =>
      '<rect x="-0.78" y="-0.2" width="1.56" height="1.12" fill="#a1714a" stroke="#fff" stroke-width="0.06"/>' +
      '<path d="M-0.78,0.08 L0.78,0.08 M-0.78,0.36 L0.78,0.36 M-0.78,0.64 L0.78,0.64" stroke="#7b5233" stroke-width="0.05"/>' +
      '<path d="M-1,-0.12 L0,-1 L1,-0.12 L0.82,-0.12 L0,-0.82 L-0.82,-0.12 Z" fill="var(--c-dock)" stroke="#fff" stroke-width="0.06"/>' +
      '<path d="M-0.82,-0.12 L0,-0.82 L0.82,-0.12 Z" fill="var(--c-dock)" opacity="0.7"/>' +
      '<rect x="-0.22" y="0.22" width="0.44" height="0.7" fill="#5d3b22"/><circle cx="0.13" cy="0.58" r="0.04" fill="#ffd54f"/>' +
      '<rect x="0.36" y="0.02" width="0.3" height="0.26" fill="#bbdefb" stroke="#5d3b22" stroke-width="0.05"/><rect x="-0.66" y="0.02" width="0.3" height="0.26" fill="#bbdefb" stroke="#5d3b22" stroke-width="0.05"/>',
  },
};

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
  }
`;

// The mower's body and blade from its sizes, in metres: a rectangle around the point OpenMower follows (the middle
// between the rear drive wheels), front ahead of it, rear behind, width wide, and the blade bladeAhead ahead of it and
// bladeOffset to the left. Nothing without them
const MAX_BLADE = 0.4;
function bodyFrom(s) {
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
  };
}

// the corners of the body and the blade's centre in the map, for the mower at x, y facing heading (rad, ccw)
function bodyShape(b, x, y, heading) {
  const c = Math.cos(heading);
  const s = Math.sin(heading);
  const at = (ahead, left) => ({x: x + c * ahead - s * left, y: y + s * ahead + c * left});
  return {
    corners: [at(b.front, b.width / 2), at(-b.rear, b.width / 2), at(-b.rear, -b.width / 2), at(b.front, -b.width / 2)],
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
      <svg xmlns="${svgNS}" preserveAspectRatio="xMidYMid meet">
        <g class="areas"></g>
        <g class="docks"></g>
        <g class="swath"></g>
        <g class="tracks"></g>
        <g class="mowerBodyLayer"></g>
        <g class="mowerIcon"></g>
        <g class="mowerTop"></g>
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
    this.tracks = section.querySelector('.tracks');
    this.swath = section.querySelector('.swath');
    this.bodyLayer = section.querySelector('.mowerBodyLayer');
    this.mower = section.querySelector('.mowerIcon');
    this.top = section.querySelector('.mowerTop');
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
    const order = {nav: 0, mow: 1, obstacle: 2};
    const areas = [...(map?.areas ?? [])].sort((a, b) => (order[a.properties?.type] ?? 1) - (order[b.properties?.type] ?? 1));
    this.areas.innerHTML = areas
      .map((area) => {
        const p = area.properties ?? {};
        const cls = [
          p.type === 'nav' ? 'navArea' : p.type === 'obstacle' ? 'obstacleArea' : 'mowArea',
          p.active === false ? 'inactive' : '',
          p.mowable === false ? 'skipMowing' : '',
        ].join(' ');
        const points = (area.outline ?? []).map((c) => `${c.x},${-c.y}`).join(' ');
        return `<polygon class="${cls}" points="${points}"/>`;
      })
      .join('');
    if (!this.view) this.fit();
    this.drawDocks();
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

  // the mower's sizes, from the app or the integration, null without them
  setBody(body) {
    if (JSON.stringify(body) === JSON.stringify(this.body)) return;
    this.body = body;
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
    if (!body?.blade) return;
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
    // at most every other frame on an old tablet's light card
    const last = this.pose;
    let draw = true;
    if (moving && last && pose) {
      const k = this.k;
      const step = Math.max(Math.hypot(pose.x - last.x, pose.y - last.y) * k, Math.abs(turned(pose.heading, last.heading)) * 0.3 * k);
      draw = step >= 1 && (!this.light || now - this.drawnAt >= 30);
    }
    if (draw) {
      this.drawnAt = now;
      this.pose = pose;
      this.drawMower();
      if (this.follow && pose) this.followMower();
    }
    if (moving) this.wake();
  }

  setFollow(on) {
    this.follow = on;
    this.windowed = false;
    this.section.querySelector('[data-zoom="follow"]').classList.toggle('on', on);
    if (on && this.pose) this.followMower();
  }

  // like the app: the mower in the middle of a window a few metres wide, as big as it was zoomed to the last time
  followMower() {
    if (!this.view) return;
    const w = this.windowed ? this.view.w : this.followSpan;
    const h = this.windowed ? this.view.h : this.followSpan;
    this.windowed = true;
    this.setView({x: this.pose.x - w / 2, y: -this.pose.y - h / 2, w, h});
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
    const icon = MAP_DOCKS[this.icons.dock] ?? MAP_DOCKS.dot;
    const size = this.icons.dockSize ?? 1;
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
          return `<g transform="translate(${x} ${-y}) rotate(${deg}) scale(${half})">${icon.draw()}</g>`;
        }
        return `<g transform="translate(${station.position.x} ${-station.position.y}) scale(${(ICON_PX * size) / k})">${icon.draw()}</g>`;
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
    const icon = MAP_MOWERS[this.icons.mower] ?? MAP_MOWERS.triangle;
    const shape = body ? bodyShape(body, pose.x, pose.y, pose.heading) : null;
    // svg y points down, so the map's ccw heading becomes a cw rotation
    const deg = (-pose.heading * 180) / Math.PI;

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
    const key = `${this.icons.mower}|${this.emergency}|${onBody}`;
    if (this.mower.dataset.key !== key) {
      const drawn = icon.draw(this.emergency);
      this.mower.innerHTML = `<g>${icon.fit && !onBody ? `<g transform="scale(1 ${icon.fit})">${drawn}</g>` : drawn}</g>`;
      this.mower.dataset.key = key;
    }
    let transform;
    if (onBody) {
      transform = `translate(${shape.middle.x} ${-shape.middle.y}) rotate(${deg}) scale(${(body.front + body.rear) / 2} ${body.width / 2})`;
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
        {name: 'blur', selector: {boolean: {}}},
      ],
      computeLabel: (schema) =>
        ({
          entity: 'Mower',
          theme: 'Look',
          map: 'Map',
          map_height: 'Map height (empty: square like in the app)',
          status: 'Status and buttons',
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
    this._skipLeft = null;
    this._skipTimer = null;
    this._confirmReset = false;
    this._pose = null;
    this._speed = 0;
    this._built = false;
    this._mapData = null;
    this._settings = {};
    this._track = null;
    this._map = null;
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error('entity: the MowBite lawn mower, e.g. lawn_mower.openmower');
    const changed = this._config && this._config.entity !== config.entity;
    this._config = {theme: 'frost', map: 'integration', status: true, blur: true, ...config};
    if (changed) {
      this._unsubscribe();
      this._data = null;
      this._mapData = null;
      this._track = null;
    }
    this._built = false;
    this._render();
    this._subscribe();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._applyLook();
    if (first) {
      // the waiting text was drawn before the language was known
      this._update();
      this._subscribe();
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    if (!this._built && this._config) this._render();
    this._subscribe();
  }

  disconnectedCallback() {
    this._map?.destroy();
    this._map = null;
    this._built = false;
    this._unsubscribe();
    clearTimeout(this._retry);
    clearInterval(this._skipTimer);
    this._skipTimer = null;
    this._skipLeft = null;
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
    }
    this._body = bodyFrom(this._settings?.mower) ?? bodyFrom(data.mower_sizes);
    this._map?.setBody(this._body);
    if (data.track) {
      // the whole track again after a reset, otherwise only the new points
      if (data.track.reset || !this._track) this._track = {reset: true, points: [...data.track.points]};
      else for (const point of data.track.points) this._track.points.push(point);
      this._map?.setTrack(data.track);
    }
    this._update();
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

  _t(text, values) {
    let s = (this._lang === 'de' && DE[text]) || text;
    for (const [k, v] of Object.entries(values ?? {})) s = s.replace(`{${k}}`, v);
    return s;
  }

  _fmt(n, digits = 0) {
    return new Intl.NumberFormat(this._lang, {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(n);
  }

  _clock(seconds, withSeconds = false) {
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
    for (const t of ['frost', 'dark', 'light']) root.classList.toggle(t, t === theme);
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
      <style>${STYLE}${MAP_STYLE}</style>
      <ha-card>
        <div class="mb frost">
          <div class="page">
            <p class="message dim" hidden></p>
            <section class="status" hidden>
              <div class="statusTop">
                <div class="ring">
                  <svg viewBox="0 0 80 80"><circle cx="40" cy="40" r="34" class="ringBg"/><circle cx="40" cy="40" r="34" class="ringFill"/></svg>
                  <div><strong class="percent"></strong><span class="charging"></span></div>
                </div>
                <div class="headline"><h2></h2><span class="sub dim"></span></div>
              </div>
              <div class="facts info"></div>
              <div class="facts temps"></div>
              <div class="controls">
                <button class="main" data-button="start"></button>
                <button data-button="pause"></button>
                <button data-button="home"></button>
                <button data-button="skip"></button>
                <button class="resetJobButton" data-button="ask_reset_job" hidden></button>
                <div class="resetJob" hidden>
                  <span></span>
                  <button class="reset" data-button="reset_job"></button>
                  <button data-button="cancel_reset_job"></button>
                </div>
                <button class="reset" data-button="reset_emergency" hidden></button>
              </div>
              <div class="wordmark"><strong>mow</strong>bite</div>
            </section>
            <section class="map" hidden></section>
          </div>
        </div>
      </ha-card>`;
    this.shadowRoot.querySelector('.controls').addEventListener('click', (ev) => {
      const button = ev.target.closest('button');
      if (button && !button.disabled) this._press(button.dataset.button);
    });
    this._built = true;
    this._map?.destroy();
    this._map = new MowbiteMap(this.shadowRoot.querySelector('.map'));
    this._map.setIcons(this._settings?.icons);
    this._map.setBody(this._body ?? null);
    if (this._mapData) this._map.setMap(this._mapData);
    if (this._track) this._map.setTrack(this._track);
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
        if (this._skipLeft === null) this._startSkip();
        else this._stopSkip();
        return this._update();
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
    }
  }

  _startSkip() {
    this._skipLeft = SKIP_DELAY;
    this._skipTimer = setInterval(() => {
      if (this._skipLeft > 1) {
        this._skipLeft--;
        this._update();
        return;
      }
      this._stopSkip();
      this._update();
      this._action('skip_area');
    }, 1000);
  }

  _stopSkip() {
    clearInterval(this._skipTimer);
    this._skipTimer = null;
    this._skipLeft = null;
  }

  _has(name) {
    return this._data?.actions?.[ACTION_IDS[name]] === true;
  }

  _headline(state, docked, chargeState, area) {
    if (state.emergency) return {title: this._t('Emergency stop'), tone: 'error'};
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
      case 'AREA_RECORDING':
        return {title: this._t('Recording an area'), tone: 'live'};
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

  _facts(el, facts) {
    const html = facts
      .map((f) => `<div${f.warn ? ' class="warn"' : ''}><span>${escape(f.label)}</span><strong>${escape(f.value)}</strong></div>`)
      .join('');
    // only when something changed, so nothing flickers twice a second
    if (el.dataset.html !== html) {
      el.innerHTML = html;
      el.dataset.html = html;
    }
  }

  _button(button, {icon, label, disabled}) {
    const html = `${ICONS[icon]}${escape(label)}`;
    if (button.dataset.html !== html) {
      button.innerHTML = html;
      button.dataset.html = html;
    }
    button.disabled = disabled;
  }

  _update() {
    if (!this._built) return;
    const $ = (s) => this.shadowRoot.querySelector(s);
    const data = this._data;
    const state = data?.state;
    const message = $('.message');
    const status = $('.status');

    if (this._error || !state) {
      message.hidden = false;
      message.textContent = this._error ?? (data?.connected ? this._t('waiting for the mower…') : this._t('connecting…'));
      status.hidden = true;
      $('.map').hidden = true;
      return;
    }
    message.hidden = true;
    status.hidden = this._config.status === false;

    const sensors = data.sensors ?? {};
    const live = !!data.available;
    const current = state.current_state ?? '';
    const driving = DRIVING.has(current);
    const docked = current === 'IDLE' && (!!state.is_charging || Number(sensors.om_v_charge) > 20);
    const battery = Math.round((state.battery_percentage ?? 0) * 100);
    const chargeState = sensors.om_charge_state;
    const charging = docked && chargeState !== 'Done';
    const head = this._headline(state, docked, chargeState, data.area);

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
    if (this._map) {
      if (appeared) this._map.refresh();
      // it follows the mower while it drives, like the app
      if (driving !== this._wasDriving) this._map.setFollow(driving);
      this._wasDriving = driving;
      this._map.setLight(this._config.blur === false);
      this._map.setPose(data.position ?? state.pose, !!state.emergency);
    }

    // a waiting skip is dropped when there's nothing to skip anymore or the connection went
    if (this._skipLeft !== null && (!live || current !== 'MOWING' || !this._has('skip_area'))) this._stopSkip();

    const ring = $('.ring');
    ring.className = `ring ring-${batteryColor(battery)}`;
    const c = 2 * Math.PI * 34;
    $('.ringFill').setAttribute('stroke-dasharray', `${(c * battery) / 100} ${c}`);
    $('.percent').textContent = `${battery}%`;
    $('.charging').textContent = charging ? this._t('charging') : '';
    $('.headline h2').textContent = head.title;

    const sub = $('.sub');
    if (live) {
      sub.className = 'sub dim';
      sub.textContent = state.emergency
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
    const gps = gpsQuality(acc);
    const facts = [
      {
        label: 'GPS',
        value: gps === 'none' ? this._t(driving ? 'no fix' : 'off') : `${this._fmt(acc * 100, 1)} cm · ${this._t(GPS_QUALITY_LABEL[gps])}`,
        // only an rtk fix is good while driving
        warn: driving && gps !== 'fix',
      },
    ];
    const num = (id) => (sensors[id] !== undefined && sensors[id] !== '' ? Number(sensors[id]) : undefined);
    if (driving) facts.push({label: this._t('Speed'), value: `${this._fmt(this._speed, 2)} m/s`});
    if (charging && num('om_charge_current') !== undefined)
      facts.push({label: this._t('Charging'), value: `${this._fmt(num('om_charge_current'), 1)} A`});
    if (num('om_v_battery') !== undefined) facts.push({label: this._t('Battery'), value: `${this._fmt(num('om_v_battery'), 1)} V`});
    if (state.rain_detected) facts.push({label: this._t('Rain'), value: this._t('detected'), warn: true});
    this._facts($('.facts.info'), facts);
    this._facts($('.facts.temps'), this._temperatures(data.sensor_infos ?? {}, sensors));

    const emergency = !!state.emergency;
    // the mower still offers start while the emergency stop is active, it has to be reset first
    const off = (name) => !live || !this._has(name) || emergency;
    const button = (name) => $(`[data-button="${name}"]`);
    this._button(button('start'), {icon: 'play', label: this._t('Start'), disabled: off('start')});
    const paused = current === 'PAUSED' && this._has('continue');
    this._button(
      button('pause'),
      paused
        ? {icon: 'play', label: this._t('Continue'), disabled: off('continue')}
        : {icon: 'pause', label: this._t('Pause'), disabled: off('pause')},
    );
    this._button(button('home'), {icon: 'home', label: this._t('Go home'), disabled: off('home')});
    this._button(button('skip'), {
      icon: 'skip',
      label: this._skipLeft !== null ? this._t('Undo ({n} s)', {n: this._skipLeft}) : this._t('Skip area'),
      disabled: off('skip_area'),
    });

    const canResetJob = live && this._has('reset_job') && !emergency;
    if (!canResetJob) this._confirmReset = false;
    button('ask_reset_job').hidden = !canResetJob || this._confirmReset;
    button('ask_reset_job').textContent = this._t('Drop the interrupted job');
    const confirm = $('.resetJob');
    confirm.hidden = !canResetJob || !this._confirmReset;
    confirm.querySelector('span').textContent = this._t('Drop the interrupted job? The next start mows from the beginning.');
    button('reset_job').textContent = this._t('Drop it');
    button('cancel_reset_job').textContent = this._t('Cancel');

    const reset = button('reset_emergency');
    reset.hidden = !emergency;
    this._button(reset, {icon: 'warning', label: this._t('Reset emergency'), disabled: !live});
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
