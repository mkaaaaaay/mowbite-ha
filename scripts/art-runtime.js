// what JSX turns into here: SVG markup as a string, wrapped so it isn't escaped again
class Markup {
  constructor(html) {
    this.html = html;
  }
  toString() {
    return this.html;
  }
}

const __Fragment = Symbol('fragment');

// svg attributes that are written in camel case, React passes these on as they are
const CAMEL = new Set(
  (
    'viewBox preserveAspectRatio patternUnits patternContentUnits patternTransform gradientUnits gradientTransform ' +
    'spreadMethod stdDeviation clipPathUnits maskUnits maskContentUnits primitiveUnits filterUnits markerWidth ' +
    'markerHeight markerUnits refX refY startOffset textLength lengthAdjust baseFrequency numOctaves kernelMatrix ' +
    'tableValues keyTimes keySplines keyPoints calcMode repeatCount repeatDur attributeName attributeType pathLength ' +
    'stitchTiles surfaceScale specularConstant specularExponent diffuseConstant pointsAtX pointsAtY pointsAtZ ' +
    'limitingConeAngle edgeMode targetX targetY xChannelSelector yChannelSelector'
  ).split(' '),
);
const kebab = (name) => name.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
const escapeText = (s) => String(s).replace(/[&<>]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'})[c]);
const escapeAttr = (s) => escapeText(s).replace(/"/g, '&quot;');

function attribute(name, value) {
  if (name === 'className') name = 'class';
  else if (name === 'htmlFor') name = 'for';
  else if (name === 'xlinkHref') name = 'href';
  else if (!CAMEL.has(name) && !name.startsWith('data') && !name.startsWith('aria')) name = kebab(name);
  else if (name.startsWith('data') || name.startsWith('aria')) name = kebab(name);
  if (name === 'style' && typeof value === 'object') {
    value = Object.entries(value)
      .filter(([, v]) => v !== undefined && v !== null && v !== false)
      .map(([k, v]) => `${k.startsWith('--') ? k : kebab(k)}:${v}`)
      .join(';');
  }
  return ` ${name}="${escapeAttr(value)}"`;
}

function render(child) {
  if (child === null || child === undefined || child === false || child === true) return '';
  if (Array.isArray(child)) return child.map(render).join('');
  if (child instanceof Markup) return child.html;
  return escapeText(child);
}

function __jsx(type, props, ...children) {
  props = props ?? {};
  const kids = children.length ? children : props.children !== undefined ? [props.children] : [];
  if (type === __Fragment) return new Markup(render(kids));
  if (typeof type === 'function') return new Markup(render(type({...props, children: kids.length === 1 ? kids[0] : kids})));
  let attrs = '';
  for (const [name, value] of Object.entries(props)) {
    if (name === 'children' || name === 'key' || name === 'ref' || value === undefined || value === null || value === false) continue;
    if (typeof value === 'function') continue;
    attrs += attribute(name, value === true ? '' : value);
  }
  const inner = render(kids);
  return new Markup(inner ? `<${type}${attrs}>${inner}</${type}>` : `<${type}${attrs}/>`);
}

// React's useId, unique on the page: gradients inside the icons need ids of their own
let ids = 0;
const useId = () => `:mb${(ids++).toString(36)}:`;

// what the app's code would keep in the browser or set on the page, each bundle its own
function memoryStorage() {
  const items = new Map();
  return {
    getItem: (k) => (items.has(k) ? items.get(k) : null),
    setItem: (k, v) => void items.set(k, String(v)),
    removeItem: (k) => void items.delete(k),
    clear: () => items.clear(),
  };
}
const env = {
  localStorage: memoryStorage(),
  sessionStorage: memoryStorage(),
  document: {documentElement: {lang: ''}, visibilityState: 'visible', addEventListener() {}, removeEventListener() {}},
  navigator: {language: 'en'},
  window: undefined,
  location: {href: '', search: '', hostname: ''},
};

// how the app's code asks the mower (its rpc) and the app's container (GET only), set by the card
const transport = {
  rpc: async () => {
    throw new Error('not connected');
  },
  get: async () => ({status: 503, body: ''}),
};

class RpcError extends Error {
  constructor(method, code, message) {
    super(message);
    this.method = method;
    this.code = code;
  }
}
let knownMethods = null;
const transportRpc = {
  RpcError,
  isMissingMethod: (e) => e instanceof RpcError && e.code === -32601,
  rpcMethods: () =>
    (knownMethods ??= transport.rpc('rpc.methods', []).then(
      (list) => (Array.isArray(list) ? new Set(list) : null),
      () => {
        knownMethods = null;
        return null;
      },
    )),
  methodsUnknown: () => false,
  unavailable: (known, method) => !!known && method !== 'rpc.methods' && !method.startsWith('meta.') && !known.has(method),
  async callRpc(method, params = [], timeoutMs = 10000) {
    if (transportRpc.unavailable(await transportRpc.rpcMethods(), method)) throw new RpcError(method, -32601, 'Method not found');
    try {
      return await transport.rpc(method, params, timeoutMs);
    } catch (e) {
      throw new RpcError(method, e?.code ?? 'timeout', e?.message ?? String(e));
    }
  },
};
const transportMowers = {
  DEMO_ID: 'demo',
  isDemo: () => false,
  apiBase: () => '',
  appMowers: () => [],
  mowerList: () => [],
  selectedMowerId: () => '',
  selectedMower: () => null,
  async mowerFetch(url, init) {
    if (init?.method && init.method !== 'GET') return new Response('', {status: 405});
    const answer = await transport.get(url);
    return new Response(answer.body ?? '', {status: answer.status});
  },
};

// the app's modules, each run once when first required
const modules = {};
const loaded = {};
function define(name, factory) {
  modules[name] = factory;
}
function require(name) {
  if (!(name in loaded)) {
    const module = {exports: {}};
    loaded[name] = module.exports;
    modules[name](module, module.exports, require, env.localStorage, env.sessionStorage, env.document, env.navigator, env.window, env.location);
    loaded[name] = module.exports;
  }
  return loaded[name];
}
