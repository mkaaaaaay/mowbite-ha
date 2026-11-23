// What the card writes into the page from the mower, its planner and its own pictures, tried in a real browser:
// node scripts/check-card.mjs (needs Chrome or Chromium, CHROME=<path> for another one)
import {execFile} from 'node:child_process';
import {existsSync, readFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const card = readFileSync(join(root, 'custom_components/mowbite/frontend/mowbite-card.js'), 'utf8');

// runs in the page, with the card's own functions
const checks = `
const results = [];
const check = (name, ok, detail = '') => results.push({name, ok: !!ok, detail: String(detail)});
const HIT = 'window.hit = (window.hit ?? 0) + 1';
const evil = \`0)"><img src=x onerror="\${HIT}"><g x="\`;

// svg from the mower's pictures, put into the page the way the card does
const host = document.body.appendChild(document.createElementNS(svgNS, 'svg'));
const put = (text) => {
  const clean = cleanSvgText(text);
  host.innerHTML = clean;
  return clean;
};
const foreign = () => [...host.querySelectorAll('*')].filter((el) => el.namespaceURI !== svgNS).map((el) => el.localName);
for (const [name, text] of [
  ['comment in desc', \`<desc><!--><img src="x" onerror="\${HIT}"/>--></desc>\`],
  ['comment in title', \`<title><!--><img src="x" onerror="\${HIT}"/>--></title>\`],
  ['comment in g', \`<g><!--><img src="x" onerror="\${HIT}"/>--></g>\`],
  ['text in desc', \`<desc>&lt;img src="x" onerror="\${HIT}"&gt;</desc>\`],
  ['cdata', \`<text><![CDATA[<img src="x" onerror="\${HIT}">]]></text>\`],
  ['cdata in desc', \`<desc><![CDATA[<img src="x" onerror="\${HIT}">]]></desc>\`],
  ['processing instruction', \`<?xml-stylesheet href="javascript:\${HIT}"?><path d="M0 0"/>\`],
  ['html by prefix', \`<h:img xmlns:h="http://www.w3.org/1999/xhtml" src="x" onerror="\${HIT}"/>\`],
  ['svg by prefix', \`<s:script xmlns:s="\${svgNS}">\${HIT}</s:script><s:path xmlns:s="\${svgNS}" onclick="\${HIT}" d="M0 0"/>\`],
  ['script', \`<script>\${HIT}</script>\`],
  ['foreignObject', \`<foreignObject><img xmlns="http://www.w3.org/1999/xhtml" src="x" onerror="\${HIT}"/></foreignObject>\`],
  ['handler', \`<path d="M0 0" onload="\${HIT}" onclick="\${HIT}"/>\`],
  ['link', \`<use href="javascript:\${HIT}"/><use xlink:href="data:image/svg+xml,x"/>\`],
  ['animated link', \`<use><animate attributeName="href" to="javascript:\${HIT}"/></use>\`],
]) {
  const clean = put(text);
  const left = foreign();
  check('svg: ' + name, !left.length && !/<!|<\\?|onerror|onload|onclick|javascript:|script/i.test(clean), clean + ' ' + left);
}
const kept = put('<g transform="rotate(5)"><path d="M0 0L1 1" fill="#fff"/><text x="1">A &amp; B</text><animateTransform attributeName="transform" type="rotate" from="0" to="9" dur="1s"/><!-- note --></g>');
check('svg: what draws stays', host.querySelector('g > path') && host.querySelector('text')?.textContent === 'A & B' && host.querySelector('animateTransform') && !kept.includes('note'), kept);

// what comes next to the svg
const mower = cleanArt('mower', {key: evil, fit: evil, side: evil, upright: 1, svg: '<path d="M0 0"/>'});
check('art: mower', mower.fit === null && mower.side === false && mower.upright === false && !JSON.stringify(mower).includes('onerror'), JSON.stringify(mower));
const real = cleanArt('mower', {fit: 0.72, side: true, upright: false, svg: '<path d="M0 0"/>'});
check('art: a real mower', real.fit === 0.72 && real.side === true && real.svg.includes('<path'), JSON.stringify(real));
const dock = cleanArt('dock', {key: evil, real: {length: evil, pins: 0.09}, svg: '<circle r="1"/>'});
check('art: dock', dock.real === null && !JSON.stringify(dock).includes('onerror'), JSON.stringify(dock));
check('art: a real dock', cleanArt('dock', {real: {length: 0.62, width: 0.46, pins: 0.09}, svg: ''}).real?.length === 0.62);
const body = cleanArt('body', {width: 0.4, front: 0.4, rear: 0.2, blade: evil, bladeAhead: evil, outline: [[evil, 0], [1, 1], [0, 1]]});
check('art: body', body && body.blade === 0 && body.bladeAhead === 0 && !body.outline, JSON.stringify(body));
check('art: no body', cleanArt('body', {width: evil, front: 1, rear: 1}) === null && cleanArt('body', evil) === null);
check('art: no object', cleanArt('mower', evil) === null);
const life = cleanArt('life', {lawn: \`<desc><!--><img src="x" onerror="\${HIT}"/>--></desc><path d="M0 0"/>\`, covers: [{cx: evil, cy: 1, r: 1}]});
check('art: life', !/img|<!/.test(life.lawn) && life.covers.length === 0, JSON.stringify(life));

// the map's layers that take the mower's and the planner's numbers
const section = document.body.appendChild(document.createElement('div'));
section.style.cssText = 'width:400px;height:300px';
const map = new MowbiteMap(section);
map.view = {x: -10, y: -10, w: 20, h: 20};
const drawn = (layer) => [...layer.children].map((el) => el.localName + ':' + (el.getAttribute('points') ?? el.getAttribute('transform') ?? el.getAttribute('cx')));
const html = () => section.querySelectorAll('img, foreignObject, script').length;

map.setLeftovers([[[0, 0], [1, 1]], [[evil, 0], [2, 2], [3, 3]], evil, [evil], null]);
check('leftovers', map.leftoverLayer.children.length === 5 && drawn(map.leftoverLayer)[0] === 'polyline:0,0 1,-1' && drawn(map.leftoverLayer)[1] === 'polyline:2,-2 3,-3' && !html(), drawn(map.leftoverLayer));
map.setLeftovers(evil);
check('leftovers: no list', map.leftoverLayer.children.length === 0);

map.setTight([[1, 2, 0.03], [evil, 2, 0.03], [1, evil], evil, null]);
check('tight places', map.tightLayer.children.length === 1 && map.tightLayer.firstElementChild.getAttribute('cy') === '-2' && !html(), drawn(map.tightLayer));
map.setTight(evil);
check('tight places: no list', map.tightLayer.children.length === 0);

const docks = (stations) => {
  map.setMap({areas: [], docking_stations: stations});
  return drawn(map.docks);
};
let stations = docks([
  {position: {x: 1, y: 2}, heading: 0},
  {position: {x: evil, y: 2}, heading: 0},
  {position: {x: 1, y: 2}, heading: evil},
  {position: evil},
  evil,
  null,
]);
check('docks', stations.length === 1 && stations[0].startsWith('g:translate(1 -2)') && !html(), stations);
map.dockIcon = {asked: '', svg: '<circle r="1"/>', real: {length: 0.62, pins: 0.09}};
stations = docks([{position: {x: 1, y: 2}, heading: 0}, {position: {x: evil, y: 2}, heading: 0}]);
check('docks: a real station', stations.length === 1 && stations[0].includes('rotate(0)') && map.docks.querySelector('circle') && !html(), stations);
map.dockIcon = {asked: '', svg: '<circle r="1"/>', real: {length: evil, pins: 0.09}};
stations = docks([{position: {x: 1, y: 2}, heading: 0}]);
check('docks: sizes that are no numbers', stations.length === 1 && !stations[0].includes('rotate') && !html(), stations);
docks(evil);
check('docks: no list', map.docks.children.length === 0);

// a mower icon whose fit is no number
map.mowerIcons.set('', {meta: {fit: evil, side: evil, upright: false}, drawings: new Map()});
map.pose = {x: 0, y: 0, heading: 0};
map.drawMower();
check('mower icon', map.mower.querySelector('.mower') && !html(), map.mower.innerHTML);

// handlers run when the browser gets to them
await new Promise((resolve) => setTimeout(resolve, 300));
check('nothing ran', window.hit === undefined, window.hit);
document.title = 'done';
document.body.textContent = JSON.stringify(results);
`;

const page = '<!doctype html><meta charset="utf-8"><title>running</title><body><script type="module" src="/card.js"></script>';
const server = createServer((request, response) => {
  if (request.url === '/') {
    response.writeHead(200, {'content-type': 'text/html'}).end(page);
  } else if (request.url === '/card.js') {
    response.writeHead(200, {'content-type': 'text/javascript'}).end(`${card}\n${checks}`);
  } else {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

const chrome =
  process.env.CHROME ??
  ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']
    .map((name) => ['/usr/bin', '/usr/local/bin', '/snap/bin'].map((dir) => join(dir, name)).find(existsSync))
    .find(Boolean);
if (!chrome) {
  console.error('no Chrome found, set CHROME');
  process.exit(2);
}
// not the blocking kind: the page is served from here while the browser runs
const run = await new Promise((resolve) =>
  execFile(
    chrome,
    ['--headless=new', '--enable-logging=stderr', '--no-sandbox', '--disable-gpu', '--virtual-time-budget=10000', '--dump-dom', `http://127.0.0.1:${server.address().port}/`],
    {encoding: 'utf8', timeout: 60000},
    (error, stdout, stderr) => resolve({error, stdout, stderr}),
  ),
);
server.close();

const found = /<body>(\[.*\])<\/body>/s.exec(run.stdout ?? '');
if (!found) {
  console.error('the page did not finish', run.error ?? '', run.stderr, run.stdout);
  process.exit(1);
}
const unescape = (text) => text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const results = JSON.parse(unescape(found[1]));
for (const {name, ok, detail} of results) console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : `: ${detail}`}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
