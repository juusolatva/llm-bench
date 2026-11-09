A server pushes state updates to many clients, some of them on slow connections. Every update carries the full state, so a client that falls behind only ever needs the latest one. Write TypeScript code with:

```ts
export interface Client {
  /** Queues chunk for sending. Returns false when the client's buffer is full; drained() is called once it has emptied. */
  write(chunk: string): boolean;
  /** Bytes queued but not yet sent. */
  readonly bufferedBytes: number;
  /** Closes the connection at once, discarding queued output. */
  destroy(): void;
}

export interface BroadcasterOptions {
  maxBufferedBytes: number;
  drainTimeoutMs: number;
  onCount?: (count: number) => void;
}

export class Broadcaster {
  constructor(options: BroadcasterOptions);
  /** The number of registered clients. */
  get size(): number;
  add(client: Client, snapshot: string, now: number): void;
  remove(client: Client): void;
  broadcast(update: string, now: number): void;
  ping(now: number): void;
  drained(client: Client, now: number): void;
  tick(now: number): void;
}
```

Times (`now`) are in milliseconds. All chunks are ASCII, so a chunk's size in bytes is its length.

Writing a chunk to a registered client: if `client.bufferedBytes + chunk.length > maxBufferedBytes`, destroy the client instead (call `client.destroy()` and unregister it). Otherwise call `client.write(chunk)`; if it returns `false`, the client is blocked since `now`.

- `add(client, snapshot, now)` registers the client and writes `snapshot` to it. Adding a client that is already registered does nothing: no snapshot, and its state doesn't change. A client that was removed or destroyed can be added again as a new client.
- `broadcast(update, now)` writes `update` to every registered client that isn't blocked. A blocked client gets nothing, but remembers that it missed an update.
- `ping(now)` writes `": ping\n\n"` to every registered client that isn't blocked. Blocked clients skip it, and it isn't remembered.
- `drained(client, now)` unblocks a blocked client. If the client missed an update while blocked, the latest update passed to `broadcast` is written to it once, following the writing rule above (so the client can be destroyed or blocked again). For a client that isn't registered or isn't blocked, it does nothing.
- `tick(now)` destroys every client that has been blocked for `drainTimeoutMs` or longer (`now - blockedSince >= drainTimeoutMs`).
- `remove(client)` unregisters a client that closed by itself, without calling `destroy()`. For a client that isn't registered, it does nothing.
- `onCount`, if given, is called with the new `size` each time `size` changes (once per change), and never otherwise.

Write the code in `solution.ts`. It is compiled with `tsc --strict` (target ES2023, libraries ES2023 and DOM) and run on Node.js as an ES module. Use only the ECMAScript standard library and web-standard globals such as `console`, `URL` and `setTimeout`: no Node.js modules (`node:*`), no Node globals such as `process` or `Buffer`, no packages. Export the names given above. No tests.
