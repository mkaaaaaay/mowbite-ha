// what the card uses: the app's own logic for the dashboard

// which version of this interface the file has
export const APP_API = 1;

// how the app's code reaches the mower and the app: rpc(method, params, timeout) -> result, get(path) -> {status, body}
export function setTransport({rpc, get}) {
  transport.rpc = rpc;
  transport.get = get;
  knownMethods = null;
}

// the rpcs the mower has (a Set), null while it doesn't answer
export const rpcMethods = () => transportRpc.rpcMethods();

const i18n = require('@/lib/i18n');
// 'de' or 'en', the app has no other
export function setLanguage(lang) {
  env.navigator.language = lang;
  i18n.setLangChoice(lang === 'de' ? 'de' : 'en');
}

export const tr = i18n.tr;
export const fmt = i18n.fmt;
export const events = require('@/lib/events');
export const history = require('@/lib/history');
export const dates = require('@/lib/dates');
export const sun = require('@/lib/sun');
export const status = require('@/lib/status');
export const schedule = require('@/lib/schedule');
export const system = require('@/lib/system');
export const roslog = require('@/lib/roslog');
export const leftovers = require('@/lib/leftovers');
export const areaPlan = require('@/lib/areaPlan');
export const planProgress = require('@/lib/planProgress');
export const coverage = require('@/lib/coverage');
export const stats = require('@/lib/stats');
export const openmower = require('@/lib/openmower');
