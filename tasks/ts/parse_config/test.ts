import { parseConfig, type Config, type ParseResult } from "./solution.js";

const harness_failures: string[] = [];

function harness_describe(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

/** A single-quoted TypeScript string literal for s, so JSON input stays readable in messages. */
function harness_quote(s: string): string {
  return `'${JSON.stringify(s).slice(1, -1).replace(/\\"/g, '"').replace(/'/g, "\\'")}'`;
}

type harness_Expected = { value: Config } | { error: string };

const harness_valid = '"name":"a","port":1,"mode":"dev"';

// [JSON text, expected value or error]
const harness_cases: [string, harness_Expected][] = [
  ['{"name":"api","port":8080,"mode":"prod"}', { value: { name: "api", port: 8080, mode: "prod", tags: [] } }],
  ['{"name":"api","port":1e3,"mode":"dev","tags":["a","b"]}', { value: { name: "api", port: 1000, mode: "dev", tags: ["a", "b"] } }],
  ['{"tags":[],"mode":"dev","port":65535,"name":"x"}', { value: { name: "x", port: 65535, mode: "dev", tags: [] } }],
  ['{"tags":[],"mode":"dev","port":1,"name":"x"}', { value: { name: "x", port: 1, mode: "dev", tags: [] } }],
  ["not json", { error: "invalid JSON" }],
  ["", { error: "invalid JSON" }],
  ['{"name":', { error: "invalid JSON" }],
  ["null", { error: "config: expected object" }],
  ["[]", { error: "config: expected object" }],
  ['"x"', { error: "config: expected object" }],
  ["3", { error: "config: expected object" }],
  ["true", { error: "config: expected object" }],
  ["{}", { error: "name: missing" }],
  ['{"port":0,"name":""}', { error: "name: expected non-empty string" }],
  ['{"name":5}', { error: "name: expected non-empty string" }],
  ['{"name":null,"port":1,"mode":"dev"}', { error: "name: expected non-empty string" }],
  ['{"name":"a"}', { error: "port: missing" }],
  ['{"name":"a","port":"8080","mode":"dev"}', { error: "port: expected integer 1-65535" }],
  ['{"name":"a","port":8080.5,"mode":"dev"}', { error: "port: expected integer 1-65535" }],
  ['{"name":"a","port":0,"mode":"dev"}', { error: "port: expected integer 1-65535" }],
  ['{"name":"a","port":65536,"mode":"dev"}', { error: "port: expected integer 1-65535" }],
  ['{"name":"a","port":-1,"mode":"dev"}', { error: "port: expected integer 1-65535" }],
  ['{"name":"a","port":1}', { error: "mode: missing" }],
  ['{"name":"a","port":1,"mode":"test"}', { error: 'mode: expected "dev" or "prod"' }],
  ['{"name":"a","port":1,"mode":"Prod"}', { error: 'mode: expected "dev" or "prod"' }],
  [`{${harness_valid},"tags":null}`, { error: "tags: expected array" }],
  [`{${harness_valid},"tags":"a"}`, { error: "tags: expected array" }],
  [`{${harness_valid},"tags":["a",2]}`, { error: "tags[1]: expected string" }],
  [`{${harness_valid},"tags":[null]}`, { error: "tags[0]: expected string" }],
  [`{${harness_valid},"zeta":1,"alpha":2}`, { error: "zeta: unknown key" }],
  [`{"zeta":1,${harness_valid},"tags":[1]}`, { error: "tags[0]: expected string" }],
  [`{${harness_valid},"__proto__":{}}`, { error: "__proto__: unknown key" }],
  ['{"zeta":1}', { error: "name: missing" }],
];

function harness_check(input: string, expected: harness_Expected): void {
  const call = `parseConfig(${harness_quote(input)})`;
  const want = JSON.stringify("error" in expected ? { ok: false, error: expected.error } : { ok: true, value: expected.value });
  let result: ParseResult;
  try {
    result = parseConfig(input);
  } catch (error) {
    harness_failures.push(`${call} threw ${harness_describe(error)}, expected ${want}`);
    return;
  }
  const got = JSON.stringify(result);
  if (typeof result !== "object" || result === null) {
    harness_failures.push(`${call} returned ${String(got)}, expected ${want}`);
    return;
  }
  if ("error" in expected) {
    if (result.ok) {
      harness_failures.push(`${call} returned ${got}, expected ${want}`);
    } else {
      const error: string = result.error;
      if (error !== expected.error) harness_failures.push(`${call} returned ${got}, expected ${want}`);
    }
    return;
  }
  if (!result.ok) {
    harness_failures.push(`${call} returned ${got}, expected ${want}`);
    return;
  }
  const value: Config = result.value;
  const name: string = value.name;
  const port: number = value.port;
  const mode: "dev" | "prod" = value.mode;
  const tags: string[] = value.tags;
  const keys = Object.keys(value).sort().join(", ");
  if (keys !== "mode, name, port, tags") {
    harness_failures.push(`${call} returned ${got}: value has the keys ${keys}, expected exactly mode, name, port, tags`);
  } else if (JSON.stringify({ name, port, mode, tags }) !== JSON.stringify(expected.value)) {
    harness_failures.push(`${call} returned ${got}, expected ${want}`);
  }
}

for (const [input, expected] of harness_cases) {
  try {
    harness_check(input, expected);
  } catch (error) {
    harness_failures.push(`checking parseConfig(${harness_quote(input)}) threw ${harness_describe(error)}`);
  }
}

if (harness_failures.length > 0) {
  for (const failure of harness_failures) console.log(failure);
  throw new Error(`harness: ${harness_failures.length} check(s) failed`);
}
console.log("harness: all checks passed");
