/**
 * Routes one HTTP request for a server that serves exactly two paths, GET /stream and GET /healthz,
 * and returns the status code: 200 for those two, 405 for any method other than GET (whatever the
 * target), 404 for everything else. A proxy in front has already authorized this exact target, so the
 * path is the raw request-target before the first "?", compared exactly: no decoding or normalization.
 * It must never throw.
 */
export function route(method: string, target: string): number {
  if (method !== "GET") return 405;
  // The raw path: a URL parser throws on some targets ("//") and resolves "..", "\" and "//host"
  // in ways the proxy that authorized the target need not share.
  const path = target.split("?", 1)[0];
  if (path === "/stream" || path === "/healthz") return 200;
  return 404;
}
