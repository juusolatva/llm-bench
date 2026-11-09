This request router in solution.ts has bugs: some request-targets make it throw, and some targets that are neither `/stream` nor `/healthz` get 200. Fix it and reply with the complete fixed solution.ts.

```ts
/**
 * Routes one HTTP request for a server that serves exactly two paths, GET /stream and GET /healthz,
 * and returns the status code: 200 for those two, 405 for any method other than GET (whatever the
 * target), 404 for everything else. A proxy in front has already authorized this exact target, so the
 * path is the raw request-target before the first "?", compared exactly: no decoding or normalization.
 * It must never throw.
 */
export function route(method: string, target: string): number {
  const path = new URL(target, "http://localhost").pathname;
  if (method !== "GET") return 405;
  if (path === "/stream" || path === "/healthz") return 200;
  return 404;
}
```

Write the code in `solution.ts`. It is compiled with `tsc --strict` (target ES2023, libraries ES2023 and DOM) and run on Node.js as an ES module. Use only the ECMAScript standard library and web-standard globals such as `console`, `URL` and `setTimeout`: no Node.js modules (`node:*`), no Node globals such as `process` or `Buffer`, no packages. Export the names given above. No tests.
