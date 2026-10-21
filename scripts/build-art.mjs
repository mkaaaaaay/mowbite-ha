// Builds two files of the card from the MowBite app's own code, so the card looks and words things the way the app
// does. The app's TSX for React is compiled with the app's TypeScript and a tiny runtime that turns JSX into SVG
// strings, its modules are bundled by a small loader.
//
//   node scripts/build-art.mjs <path to the MowBite repo>
//
// - mowbite-art.js: the map's pictures (mowers, docks, the garden style, the real edges). Only drawing, nothing
//   outside of it, the same file the app's container serves (/mowbite-art.js)
// - mowbite-app.js: what the dashboard works out (the runs of a day, why an emergency stop is on, leftovers, the
//   schedule, the texts in the app's languages). It asks the mower and the app through the card (setTransport)
//
// Run it again after the app changed. MowBite is GPL-3.0 like this integration.

import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const app = path.resolve(process.argv[2] ?? '');
if (!fs.existsSync(path.join(app, 'src/components/mapIcons.tsx'))) {
  console.error('usage: node scripts/build-art.mjs <path to the MowBite repo>');
  process.exit(1);
}
const ts = createRequire(path.join(app, 'package.json'))('typescript');
const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.join(here, '..', 'custom_components/mowbite/frontend');

const CLIPPER = 'node_modules/clipper-lib/clipper.js';

// what both need that only the app's pages use
const COMMON_STUBS = {
  react:
    'module.exports = {useId, useEffect() {}, useMemo: (f) => f(), useState: (v) => [v, () => {}], useRef: (v) => ({current: v}), useSyncExternalStore: (s, get) => get()};',
  'react-dom': 'module.exports = {createPortal: () => null};',
  '@/hooks/useMowerMap': 'module.exports = {};',
  '@/lib/native': 'module.exports = {isApp: () => false};',
  '@/lib/settings':
    'module.exports = {saveSettings() {}, syncSettings() {}, settingsStore: {get: () => ({}), snapshot: () => ({}), subscribe: () => () => {}}};',
  // a css module's class names as they are (class="cutThere"), also as its default export, which is how TSX imports it
  css: "module.exports = new Proxy({}, {get: (_, k) => (k === 'default' ? module.exports : k === '__esModule' ? true : String(k))});",
};

const BUNDLES = [
  {
    out: 'mowbite-art.js',
    exports: 'art-exports.js',
    modules: {
      '@/components/mapIcons': 'src/components/mapIcons.tsx',
      '@/components/openmowerArt': 'src/components/openmowerArt.ts',
      '@/components/gardenPictures': 'src/components/gardenPictures.tsx',
      '@/components/gardenLook': 'src/components/gardenLook.tsx',
      '@/components/gardenLife': 'src/components/gardenLife.tsx',
      '@/lib/geometry': 'src/lib/geometry.ts',
      '@/lib/mowStripes': 'src/lib/mowStripes.ts',
      '@/lib/mowerBody': 'src/lib/mowerBody.ts',
      '@/lib/sun': 'src/lib/sun.ts',
      // the real edges' polygon clipping (Boost Software License)
      'clipper-lib': CLIPPER,
    },
    stubs: {
      ...COMMON_STUBS,
      // drawing only: nothing that asks anything
      '@/lib/areaPlan': 'module.exports = {};',
      '@/lib/i18n': 'module.exports = {tr: (s) => s};',
      '@/lib/mowers': 'module.exports = {apiBase: () => ""};',
      '@/lib/openmower': 'module.exports = {RPC: {}};',
      '@/lib/rpc': 'module.exports = {callRpc: async () => null, isMissingMethod: () => true, rpcMethods: async () => []};',
    },
  },
  {
    out: 'mowbite-app.js',
    exports: 'app-exports.js',
    modules: {
      '@/lib/i18n': 'src/lib/i18n/index.ts',
      '@/lib/i18n/de': 'src/lib/i18n/de.ts',
      '@/lib/events': 'src/lib/events.ts',
      '@/lib/history': 'src/lib/history.ts',
      '@/lib/openmower': 'src/lib/openmower.ts',
      '@/lib/dates': 'src/lib/dates.ts',
      '@/lib/sun': 'src/lib/sun.ts',
      '@/lib/status': 'src/lib/status.ts',
      '@/lib/schedule': 'src/lib/schedule.ts',
      '@/lib/fresh': 'src/lib/fresh.ts',
      '@/lib/system': 'src/lib/system.ts',
      '@/lib/roslog': 'src/lib/roslog.ts',
      '@/lib/leftovers': 'src/lib/leftovers.ts',
      '@/lib/areaPlan': 'src/lib/areaPlan.ts',
      '@/lib/planProgress': 'src/lib/planProgress.ts',
      '@/lib/mowerBody': 'src/lib/mowerBody.ts',
      '@/lib/coverage': 'src/lib/coverage.ts',
      '@/lib/stats': 'src/lib/stats.ts',
      '@/hooks/useWeather': 'src/hooks/useWeather.ts',
      'clipper-lib': CLIPPER,
    },
    stubs: {
      ...COMMON_STUBS,
      // the mower's rpc and the app's endpoints, asked through the card (art-runtime.js: transport)
      '@/lib/rpc': 'module.exports = transportRpc;',
      '@/lib/mowers': 'module.exports = transportMowers;',
      '@/lib/mqttClient': 'module.exports = {};',
    },
    css: {from: ['src/app/globals.css', 'src/app/page.module.css', 'src/components/MapView.module.css'], make: dashboardCss},
  },
];

// the css as its top level rules, at-rules with their insides: [selector or at-rule, whole text]
function cssRules(text) {
  text = text.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}' && --depth === 0) {
      const rule = text.slice(start, i + 1).trim();
      rules.push([rule.slice(0, rule.indexOf('{')).trim(), rule]);
      start = i + 1;
    }
  }
  return rules;
}

// the dashboard's looks for the card: the themes' colors from globals.css on the card (light the default, the others
// as the card's theme option sets them), its buttons, and page.module.css without the page's own layout (the card
// lays itself out in Home Assistant)
function dashboardCss() {
  const globals = cssRules(fs.readFileSync(path.join(app, 'src/app/globals.css'), 'utf8'));
  const theme = [];
  let light = false;
  for (const [selector, rule] of globals) {
    const themes = selector.split(',').map((s) => s.trim());
    if (selector === ':root' && !light && rule.includes('--background')) {
      light = true;
      theme.push(rule.replace(':root', '.mb'));
    } else if (themes.every((s) => /^:root\[data-theme='\w+'\]$/.test(s))) {
      theme.push(themes.map((s) => s.replace(/^:root\[data-theme='(\w+)'\]$/, '.mb.$1')).join(',\n') + rule.slice(rule.indexOf('{') - 1));
    } else if (/^button\b|^\[class|^@media \(hover|^\*$|^a$/.test(selector)) {
      theme.push(rule);
    }
  }
  const page = cssRules(fs.readFileSync(path.join(app, 'src/app/page.module.css'), 'utf8')).filter(
    ([selector]) => !/^(\.page|\.main|\.brand|\.top)\b/.test(selector) && !/^@media \(min-width/.test(selector),
  );
  // the garden's life on the map (MapView.module.css): its layers, cuts, stones and shadows
  const map = cssRules(fs.readFileSync(path.join(app, 'src/components/MapView.module.css'), 'utf8')).filter(([selector]) =>
    /gardenLife|gardenLight|\.stones|\.cuts|cutThere|cutBack|stoneTop|thingShadow|mowerUnder/.test(selector),
  );
  const all = [...theme, ...page.map(([, rule]) => rule), ...map.map(([, rule]) => rule)].join('\n\n');
  return `export const DASHBOARD_CSS = ${JSON.stringify(all)};`;
}

function resolver(bundle) {
  return (from, spec) => {
    if (spec.endsWith('.css')) return 'css';
    if (bundle.stubs[spec]) return spec;
    let name = spec;
    if (spec.startsWith('.')) {
      // from the module's own folder: @/lib for src/lib/x.ts, @/lib/i18n for src/lib/i18n/index.ts
      name = path.posix.join(path.posix.dirname(bundle.modules[from]).replace(/^src\//, '@/'), spec);
    }
    if (bundle.stubs[name]) return name;
    if (!bundle.modules[name]) throw new Error(`${from} imports ${spec}, add it to the bundle's modules or stubs`);
    return name;
  };
}

const commit = process.env.MOWBITE_VERSION ?? (() => {
  try {
    return execFileSync('git', ['-C', app, 'describe', '--tags', '--always'], {encoding: 'utf8'}).trim();
  } catch {
    return 'unknown';
  }
})();
const runtime = fs.readFileSync(path.join(here, 'art-runtime.js'), 'utf8');

for (const bundle of BUNDLES) {
  const resolve = resolver(bundle);
  let body = '';
  for (const [name, file] of Object.entries(bundle.modules)) {
    const source = fs.readFileSync(path.join(app, file), 'utf8');
    const js = file.endsWith('.js')
      ? source
      : ts.transpileModule(source, {
          fileName: file,
          compilerOptions: {
            module: ts.ModuleKind.CommonJS,
            target: ts.ScriptTarget.ES2020,
            jsx: ts.JsxEmit.React,
            jsxFactory: '__jsx',
            jsxFragmentFactory: '__Fragment',
            esModuleInterop: false,
            removeComments: true,
          },
        }).outputText;
    const rewired = js.replace(/require\("([^"]+)"\)/g, (_, spec) => `require(${JSON.stringify(resolve(name, spec))})`);
    body += `define(${JSON.stringify(name)}, ${wrap(rewired)});\n`;
  }
  for (const [name, code] of Object.entries(bundle.stubs)) body += `define(${JSON.stringify(name)}, ${wrap(code)});\n`;
  const css = bundle.css ? `\n// the app's looks (${bundle.css.from.join(', ')})\n${bundle.css.make()}\n` : '';
  const out = path.join(frontend, bundle.out);
  fs.writeFileSync(
    out,
    `// Generated by scripts/build-art.mjs from MowBite ${commit} (GPL-3.0): ${Object.values(bundle.modules).join(', ')}.
// Don't edit, build it again.
/* eslint-disable */
${runtime}
${body}
${fs.readFileSync(path.join(here, bundle.exports), 'utf8')}${css}`,
  );
  console.log(`${path.relative(process.cwd(), out)}: ${(fs.statSync(out).size / 1024).toFixed(0)} KB from MowBite ${commit}`);
}

// each module sees a page of its own: what the app's code keeps in the browser or sets on the page stays in here
function wrap(code) {
  return `function (module, exports, require, localStorage, sessionStorage, document, navigator, window, location) {\n${code}\n}`;
}
