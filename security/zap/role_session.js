// E42-X03 (#1026), #3991: the synthetic role's session on one ZAP profile's surface and on /me,
// the liveness check. ZAP expands no ${VAR} inside a replacer rule (its rules skip the plan's
// variable step), so this httpsender script reads the bearer and SR-041 CSRF pair
// security/zap/mint_sessions.py minted from the environment once, when ZAP loads it, and adds them
// to each request to the surface: no plan, report or log line carries them. A request to any other
// host or path, such as a logout, carries no session to end; with any value missing, nothing is
// added and the liveness check fails the run.
var System = Java.type("java.lang.System");
var TARGET = System.getenv("ZAP_TARGET");
var BEARER = System.getenv("ZAP_AUTH_TOKEN");
var CSRF = System.getenv("ZAP_CSRF_TOKEN");
// Each profile's surface: the whole path and query after the target (test_zap_admin.py and
// test_zap_nightly.py, in scripts/tests/, read these lines). ZAP_PROFILE names the profile; unset
// is the admin profile, and any other name has no surface, so nothing is added and the liveness
// check fails the run.
var ADMIN = /^\/((admin|users)(\/[^?]*)?|me)([?].*)?$/;
var RULES = /^\/(rules(\/[^?]*)?|schemas\/rule-ir\.json|me)([?].*)?$/;
var MARKET = /^\/(market\/(klines|bars)(\/[^?]*)?|me)([?].*)?$/;
var DRAWINGS = /^\/(drawings(\/[^?]*)?|me)([?].*)?$/;
var SURFACES = { admin: ADMIN, rules: RULES, market: MARKET, drawings: DRAWINGS };
var PROFILE = System.getenv("ZAP_PROFILE") || "admin";
var SURFACE = Object.prototype.hasOwnProperty.call(SURFACES, PROFILE) ? SURFACES[PROFILE] : null;
// A dot segment in the path, `.` or `..` (a URI may also write a dot as `%2e`), never in the
// query: a server or proxy that resolved it would send the request off the surface above, so no
// session goes along it. A separator around it may also be written `%2f`, `%5c` or `\`, and a `;`
// may follow it, as some servers read a path (scripts/tests/test_zap_admin.py reads this line too).
var DOT_SEGMENT = /^[^?]*(\/|%2[fF]|%5[cC]|\\)(\.|%2[eE]){1,2}(\/|%2[fF]|%5[cC]|\\|;|[?]|$)/;

function sendingRequest(msg, initiator, helper) {
  var url = String(msg.getRequestHeader().getURI().toString());
  if (!SURFACE || !TARGET || !BEARER || !CSRF || url.indexOf(TARGET + "/") !== 0) return;
  var rest = url.substring(TARGET.length);
  if (!SURFACE.test(rest) || DOT_SEGMENT.test(rest)) return;
  var header = msg.getRequestHeader();
  header.setHeader("Authorization", "Bearer " + BEARER);
  header.setHeader("X-CSRF-Token", CSRF);
  header.setHeader("Cookie", "__Host-cv_csrf=" + CSRF);
}

function responseReceived(msg, initiator, helper) {}
