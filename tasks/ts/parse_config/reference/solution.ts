export interface Config {
  name: string;
  port: number;
  mode: "dev" | "prod";
  tags: string[];
}

export type ParseResult = { ok: true; value: Config } | { ok: false; error: string };

const KNOWN = new Set(["name", "port", "mode", "tags"]);

function fail(error: string): ParseResult {
  return { ok: false, error };
}

export function parseConfig(json: string): ParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    return fail("invalid JSON");
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return fail("config: expected object");
  const obj = raw as Record<string, unknown>;
  const has = (key: string) => Object.hasOwn(obj, key);

  const { name, port, mode, tags } = obj;
  if (!has("name")) return fail("name: missing");
  if (typeof name !== "string" || name === "") return fail("name: expected non-empty string");
  if (!has("port")) return fail("port: missing");
  if (typeof port !== "number" || !Number.isInteger(port) || port < 1 || port > 65535) {
    return fail("port: expected integer 1-65535");
  }
  if (!has("mode")) return fail("mode: missing");
  if (mode !== "dev" && mode !== "prod") return fail('mode: expected "dev" or "prod"');
  let tagList: string[] = [];
  if (has("tags")) {
    if (!Array.isArray(tags)) return fail("tags: expected array");
    const bad = tags.findIndex((tag) => typeof tag !== "string");
    if (bad !== -1) return fail(`tags[${bad}]: expected string`);
    tagList = tags as string[];
  }
  const unknown = Object.keys(obj).find((key) => !KNOWN.has(key));
  if (unknown !== undefined) return fail(`${unknown}: unknown key`);
  return { ok: true, value: { name, port, mode, tags: [...tagList] } };
}
