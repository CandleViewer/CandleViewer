import { THEME_STORAGE_KEY } from "./store.js";

/**
 * Synchronous pre-paint snippet: restores the persisted theme, density, motion and text scale onto
 * `document.documentElement` before first paint, so a reload never flashes the wrong theme.
 * It resolves exactly like `createThemeStore` (a parity test enforces it, hostile shapes included):
 * corrupt or missing storage falls back to the defaults, and it never throws. Only strict comparisons,
 * so a crafted value (an array, an object with a throwing `toString`) can neither coerce nor throw.
 *
 * REQUIRED SHELL CONTRACT (E10): embed this string byte-for-byte as the only inline script in the
 * document `<head>`, and allow it in the CSP by hash, never `'unsafe-inline'`:
 * `script-src 'self' 'sha256-<THEME_PREPAINT_SCRIPT_SHA256>'`. Any edit to the script changes the hash;
 * the unit test pins it so the CSP and the script cannot drift apart silently.
 */
export const THEME_PREPAINT_SCRIPT = [
  "(function(){var d=document.documentElement,s={},",
  'q=function(x){return typeof matchMedia==="function"?matchMedia(x).matches:null};',
  `try{s=JSON.parse(localStorage.getItem("${THEME_STORAGE_KEY}"))||{}}catch(e){}`,
  'var o=s.motionOverride,t=s.highContrast===true?"high-contrast":',
  '(s.matchSystem===true?q("(prefers-color-scheme: dark)")!==false:s.baseTheme!=="light")?"dark":"light";',
  'd.setAttribute("data-theme",t);',
  'd.setAttribute("data-density",s.density==="comfortable"?"comfortable":"compact");',
  'd.setAttribute("data-motion",o==="on"||(o!=="off"&&q("(prefers-reduced-motion: reduce)")===true)?"reduce":"safe");',
  'd.setAttribute("data-text-scale",[100,112,125,150].indexOf(s.textScale)>-1?s.textScale:100)})();',
].join("");

/** Base64 SHA-256 of `THEME_PREPAINT_SCRIPT`, i.e. the value of the CSP `'sha256-…'` source. */
export const THEME_PREPAINT_SCRIPT_SHA256 = "XNHtTswngI1vTDLKg6/GRLzdzdnDrHCvFQZkoTwyEME=";
