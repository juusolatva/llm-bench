Write TypeScript code with:

```ts
export function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]>;
```

It calls `fn(item, index)` once for each item, with at most `limit` calls pending at a time, and resolves with the results in the order of `items`:
- If `limit` isn't a positive integer (for example 0, -1, 1.5, `NaN` or `Infinity`), the returned promise rejects with a `RangeError` and `fn` is never called. `mapLimit` itself doesn't throw.
- The calls for the first `min(limit, items.length)` items start before `mapLimit` returns.
- Whenever a pending call settles, the call for the next item that hasn't started yet starts. So items start in index order, and `limit` calls are pending as long as items remain.
- If a call rejects, the returned promise rejects with that same error at once, without waiting for the calls still pending, and no further calls start.
- For an empty `items` it resolves to `[]` without calling `fn`.

Write the code in `solution.ts`. It is compiled with `tsc --strict` (target ES2023, libraries ES2023 and DOM) and run on Node.js as an ES module. Use only the ECMAScript standard library and web-standard globals such as `console`, `URL` and `setTimeout`: no Node.js modules (`node:*`), no Node globals such as `process` or `Buffer`, no packages. Export the names given above. No tests.
