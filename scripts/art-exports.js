// what the card uses, the app's pictures as SVG strings

// which version of this interface the file has, counted up when a signature changes
export const ART_API = 1;
const mapIcons = require('@/components/mapIcons');
const gardenLook = require('@/components/gardenLook');
const gardenPictures = require('@/components/gardenPictures');
const mowStripes = require('@/lib/mowStripes');
const mowerBody = require('@/lib/mowerBody');

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
