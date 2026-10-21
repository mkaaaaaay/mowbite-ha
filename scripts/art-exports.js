// what the home assistant card uses (mowbite-art.js), the app's pictures as svg strings

// which version of this interface the file has, counted up when a signature changes or something's added (2: the
// garden's life, 3: the pictures drawn anew with gradients, drawThing takes an id, seed, color and m, placeThings at their
// real size, new pictures, the whole garden at once in gardenAreas)
export const ART_API = 3;
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
// where a thing goes as big as it really is: placeThings(look, outline, m, seed, size, turn) with the outline in svg
// units, m svg units per meter, seed the area's id, size picked for the area (settings.lookSizes, m across), turn the way a
// cantilever parasol reaches (settings.lookTurns, else facing(area, areas, looks, toSvg)). gives the places {cx, cy, deg,
// w, h, over, loose, seed}, one or several, none where nothing fits (under a centimeter wide or deep): over and loose not
// cut to the area (a crown, a parasol, one made bigger by hand), seed for drawThing when there
export const placeThings = gardenLook.placeThings;
export const facing = gardenLook.facing;
export const autoMowAngle = mowStripes.autoMowAngle;
export const PICTURE_KEYS = gardenPictures.PICTURE_KEYS;
// id starts the ids of the picture's gradients and clips: one of its own for every picture in a page. seed varies the picture
// (the area's id), variant is the color picked for it (settings.lookVariants of the area), m svg units per meter (steps,
// chairs at their real size, left out it's worked out from the box), edge a bed's real edge as [x, y] in the box's units
// (the herb garden's border goes along it), closed a parasol folded up (settings.lookClosed)
export const drawThing = (look, box, id, seed, variant, m, edge, closed) => render(gardenLook.drawThing(look, box, id, {seed, variant, m, edge, closed}));
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
// uid, now, datum, weather, rain, mower, jobs, track, edgeLine, hidden, lookVariants, lookSizes, lookTurns, lookClosed, lookGrounds}, see LifeInput in src/components/gardenLife.tsx.
// defs into the svg's defs, then over the areas in this order: lawn, the real lawn in the obstacles, things (instead of
// the areas' own), stones (along the lawns, instead of their real edges' line), sky. long: the active lawns are filled with
// url(#{uid}long). canopies: the crowns and parasols, they go over the mower, and covers the circles {cx, cy, r} where
// they hide it (the app draws the mower's outline there)
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
    canopies: render(scene.canopies),
    covers: scene.covers,
  };
}

// the garden without its life as MapView draws it, svg text in its square of 400 (fit: {minX, minY, m, padX, padY}, m svg
// units per meter, the map's corner minX, minY at padX, padY from the square's bottom left, see Fit in gardenLook.tsx).
// input: {areas, looks, lookVariants, lookSizes, lookTurns, lookClosed, lookGrounds, body, uid, fit}, see GardenInput in
// src/components/gardenLife.tsx. defs into the svg's defs (the lawns' stripes, the grounds, the clips and the beds'
// tiles, instead of gardenDefs). fills: each area's polygon filled with url(#{uid}{fill}) (the long lawn of the garden's
// life is the card's). things: by area id what stands on its ground, over its polygon (gardenLife's things instead with
// the life on). over: by area id the crowns and parasols, they go over the mower, and covers the circles {cx, cy, r, rim}
// where they hide it (gardenLife's canopies and covers instead with the life on). edges: the real edges' paths {line, lawnLine, obstacleLine, grassOutside, grassObstacles}, the lawn
// outside the mowing areas under the areas and the one in the obstacles over them, null without a body
export function gardenAreas(input) {
  const scene = life.gardenScene(input);
  const each = (byArea) => Object.fromEntries(Object.entries(byArea).map(([id, svg]) => [id, render(svg)]));
  return {
    defs: render(scene.defs),
    fills: scene.fills,
    things: each(scene.things),
    over: each(scene.over),
    covers: scene.covers,
    edges: scene.edges,
  };
}
