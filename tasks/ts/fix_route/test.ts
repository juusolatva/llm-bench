import { route } from "./solution.js";

const harness_failures: string[] = [];

function harness_describe(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

// [method, request-target, expected status]
const harness_cases: [string, string, number][] = [
  ["GET", "/stream", 200],
  ["GET", "/healthz", 200],
  ["GET", "/stream?x=1", 200],
  ["GET", "/healthz?probe=1", 200],
  ["GET", "/", 404],
  ["GET", "/streams", 404],
  ["GET", "/stream/", 404],
  ["GET", "//", 404],
  ["GET", "//:/x", 404],
  ["GET", "//x:abc/../stream", 404],
  ["GET", "//x/stream", 404],
  ["GET", "/x/../stream", 404],
  ["GET", "/./stream", 404],
  ["GET", "http://localhost/stream", 404],
  ["GET", "/stream/..\\healthz\\x/..", 404],
  ["GET", "/%73tream", 404],
  ["POST", "/stream", 405],
  ["HEAD", "/healthz", 405],
  ["POST", "//", 405],
  ["DELETE", "/x/../stream", 405],
];

for (const [method, target, expected] of harness_cases) {
  const call = `route(${JSON.stringify(method)}, ${JSON.stringify(target)})`;
  let actual: number;
  try {
    actual = route(method, target);
  } catch (error) {
    harness_failures.push(`${call} threw ${harness_describe(error)}, expected ${expected}`);
    continue;
  }
  if (actual !== expected) harness_failures.push(`${call} returned ${JSON.stringify(actual)}, expected ${expected}`);
}

if (harness_failures.length > 0) {
  for (const failure of harness_failures) console.log(failure);
  throw new Error(`harness: ${harness_failures.length} check(s) failed`);
}
console.log("harness: all checks passed");
