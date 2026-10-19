// what the card uses, the app's pictures as SVG strings

// which version of this interface the file has, counted up when a signature changes (2: the garden's life)
export const ART_API = 2;
const mapIcons = require('@/components/mapIcons');
const gardenLook = require('@/components/gardenLook');
const gardenPictures = require('@/components/gardenPictures');
const mowStripes = require('@/lib/mowStripes');
const mowerBody = require('@/lib/mowerBody');
const life = require('@/components/gardenLife');
const sun = require('@/lib/sun');

// the mower's icon by its key (the app's first one for an unknown key): fit is a real mower's width over its length,
// side a side view, upright a figure. draw takes {speed, emergency, blades}
export function mowerIcon(key) {
  const icon = mapIcons.mowerIcon(key);
  return {
    key: icon.key,
    fit: icon.fit ?? null,
    side: !!icon.side,
    upright: !!icon.upright,
    draw: (o) => render(icon.draw(o ?? {})),
  };
}

// the dock's icon: real is a real station's size (m), drawn at its size under the docked mower
export function dockIcon(key) {
  const icon = mapIcons.dockIcon(key);
  return {key: icon.key, real: icon.real ?? null, draw: () => render(icon.draw())};
}

export const MOWER_KEYS = mapIcons.MOWER_ICONS.map((icon) => icon.key);
export const DOCK_KEYS = mapIcons.DOCK_ICONS.map((icon) => icon.key);

// the garden map style
export const areaLook = gardenLook.areaLook;
export const isThing = gardenLook.isThing;
export const groundOf = gardenLook.groundOf;
export const placeThing = gardenLook.placeThing;
export const autoMowAngle = mowStripes.autoMowAngle;
export const PICTURE_KEYS = gardenPictures.PICTURE_KEYS;
export const drawThing = (look, box) => render(gardenLook.drawThing(look, box));
// the lawns' stripes, the grounds' textures and the things' clip paths, m: svg units per meter
export const gardenDefs = (uid, m, lawns, clips) => render(gardenLook.GardenDefs({uid, m, lawns, clips}));

// the mower's body from the sizes set in the app (with a measured model's outline when its sizes are exactly one's),
// its shape at a pose, and the real edges: the mowing areas grown and the obstacles shrunk by half its width
export const sizesBody = (sizes, keepRectangle) => mowerBody.sizesBody(mowerBody.withModelOutline(sizes, keepRectangle));
export const bodyShape = mowerBody.bodyShape;
export const realEdges = mowerBody.realEdges;
export const insideEdge = mowerBody.insideEdge;

// the garden's life (2): light and shadows after the sun, the season and the weather on the lawn, the lawn growing back
// and cut where the mower goes, a mowing edge of stones. each part on its own (lifeOf: settings.garden), the sun's
// position and the season from the map's place on earth
export const lifeOf = life.lifeOf;
export const heightOf = life.heightOf;
export const shadowOf = life.shadowOf;
export const lightOf = life.lightOf;
export const sprinkles = life.sprinkles;
export const drawSprinkle = (s, m, season) => render(life.drawSprinkle(s, m, season, 0));
export const cutPaths = life.cutPaths;
export const freshness = life.freshness;
export const lifeDefs = (uid, m) => render(life.LifeDefs({uid, m}));
export const sunPosition = sun.sunPosition;
export const seasonOf = sun.seasonOf;

// all of it at once in MapView's layers as svg text, null with none of it on. input: {areas, garden, looks, body, fit,
// uid, now, datum, weather, rain, mower, jobs, track, edgeLine, hidden}, see LifeInput in src/components/gardenLife.tsx.
// defs into the svg's defs, then over the areas in this order: lawn, the real lawn in the obstacles, things (instead of
// the areas' own), stones (instead of the real edges' line), sky. long: the active lawns are filled with url(#{uid}long)
export function gardenLife(input) {
  const scene = life.lifeScene(input);
  if (!scene) return null;
  return {
    parts: scene.parts,
    long: scene.long,
    defs: render(scene.defs),
    lawn: render(scene.lawn),
    things: render(scene.things),
    stones: render(scene.stones),
    sky: render(scene.sky),
  };
}
