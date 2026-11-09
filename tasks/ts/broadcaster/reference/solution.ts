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

interface ClientState {
  /** When write() last returned false, or null while the client accepts writes. */
  blockedSince: number | null;
  /** A broadcast was skipped while blocked; the latest update is sent on drain. */
  missed: boolean;
}

const PING = ": ping\n\n";

export class Broadcaster {
  private readonly options: BroadcasterOptions;
  private readonly clients = new Map<Client, ClientState>();
  /** Every update carries full state, so only the latest one is kept, shared by all blocked clients. */
  private latest: string | null = null;

  constructor(options: BroadcasterOptions) {
    this.options = options;
  }

  get size(): number {
    return this.clients.size;
  }

  add(client: Client, snapshot: string, now: number): void {
    if (this.clients.has(client)) return;
    const state: ClientState = { blockedSince: null, missed: false };
    this.clients.set(client, state);
    this.report();
    this.write(client, state, snapshot, now);
  }

  remove(client: Client): void {
    if (this.clients.delete(client)) this.report();
  }

  broadcast(update: string, now: number): void {
    this.latest = update;
    for (const [client, state] of [...this.clients]) {
      if (state.blockedSince === null) this.write(client, state, update, now);
      else state.missed = true;
    }
  }

  ping(now: number): void {
    for (const [client, state] of [...this.clients]) {
      if (state.blockedSince === null) this.write(client, state, PING, now);
    }
  }

  drained(client: Client, now: number): void {
    const state = this.clients.get(client);
    if (state === undefined || state.blockedSince === null) return;
    state.blockedSince = null;
    if (state.missed && this.latest !== null) {
      state.missed = false;
      this.write(client, state, this.latest, now);
    }
  }

  tick(now: number): void {
    for (const [client, state] of [...this.clients]) {
      if (state.blockedSince !== null && now - state.blockedSince >= this.options.drainTimeoutMs) this.drop(client);
    }
  }

  private write(client: Client, state: ClientState, chunk: string, now: number): void {
    if (client.bufferedBytes + chunk.length > this.options.maxBufferedBytes) {
      this.drop(client);
      return;
    }
    if (!client.write(chunk)) state.blockedSince = now;
  }

  /** Unregisters first, so a close event that destroy() triggers finds the client gone. */
  private drop(client: Client): void {
    if (!this.clients.delete(client)) return;
    this.report();
    client.destroy();
  }

  private report(): void {
    this.options.onCount?.(this.clients.size);
  }
}
