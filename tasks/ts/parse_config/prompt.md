Write TypeScript code with:

```ts
export interface Config {
  name: string;
  port: number;
  mode: "dev" | "prod";
  tags: string[];
}

export type ParseResult = { ok: true; value: Config } | { ok: false; error: string };

export function parseConfig(json: string): ParseResult;
```

`parseConfig` parses and validates a configuration given as JSON text from an untrusted source. It never throws: every problem is returned as `{ ok: false, error }`, with `error` set to exactly one of the messages below.

- If `json` isn't valid JSON, the error is `invalid JSON`.
- If the parsed value isn't an object (it is `null`, an array, a string, a number or a boolean), the error is `config: expected object`.
- Otherwise the first problem is reported, checking in this order:
  1. `name` must be a non-empty string: `name: missing` if the key is absent, otherwise `name: expected non-empty string`.
  2. `port` must be an integer from 1 to 65535: `port: missing` or `port: expected integer 1-65535`.
  3. `mode` must be `"dev"` or `"prod"`: `mode: missing` or `mode: expected "dev" or "prod"`.
  4. `tags` is optional. If present, it must be an array (`tags: expected array`) whose elements are all strings; the first element that isn't gives `tags[<index>]: expected string`, for example `tags[1]: expected string`.
  5. Any other key is an error `<key>: unknown key`, for example `debug: unknown key`. If there are several, report the first in the order `Object.keys` returns them for the parsed object.
- On success, `value` has exactly the keys `name`, `port`, `mode` and `tags`, with `tags` set to `[]` if it was absent.

Write the code in `solution.ts`. It is compiled with `tsc --strict` (target ES2023, libraries ES2023 and DOM) and run on Node.js as an ES module. Use only the ECMAScript standard library and web-standard globals such as `console`, `URL` and `setTimeout`: no Node.js modules (`node:*`), no Node globals such as `process` or `Buffer`, no packages. Export the names given above. No tests.
