import { Broadcaster, type BroadcasterOptions, type Client } from "./solution.js";

const harness_failures: string[] = [];

function harness_describe(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${JSON.stringify(error.message)}` : String(error);
}

/** A client that records what it receives; `accept` is what write() returns. */
class harness_Client implements Client {
  written: string[] = [];
  bufferedBytes = 0;
  accept = true;
  destroyed = 0;

  constructor(readonly name: string) {}

  write(chunk: string): boolean {
    this.written.push(chunk);
    return this.accept;
  }

  destroy(): void {
    this.destroyed++;
  }
}

/** One Broadcaster and the steps done to it, which every failure message replays. */
class harness_Run {
  readonly counts: number[] = [];
  readonly steps: string[] = ["new Broadcaster({ maxBufferedBytes: 100, drainTimeoutMs: 1000, onCount })"];
  readonly b: Broadcaster;

  constructor() {
    const options: BroadcasterOptions = { maxBufferedBytes: 100, drainTimeoutMs: 1000, onCount: (n) => this.counts.push(n) };
    this.b = new Broadcaster(options);
  }

  where(): string {
    return `after ${this.steps.join(", ")}`;
  }

  step(description: string, action: () => void): void {
    this.steps.push(description);
    try {
      action();
    } catch (error) {
      throw new Error(`${this.where()}: the last call threw ${harness_describe(error)}`);
    }
  }

  set(description: string, action: () => void): void {
    this.steps.push(description);
    action();
  }

  add(c: harness_Client, snapshot: string, now: number): void {
    this.step(`add(${c.name}, ${JSON.stringify(snapshot)}, ${now})`, () => this.b.add(c, snapshot, now));
  }

  remove(c: harness_Client): void {
    this.step(`remove(${c.name})`, () => this.b.remove(c));
  }

  broadcast(update: string, now: number): void {
    this.step(`broadcast(${JSON.stringify(update)}, ${now})`, () => this.b.broadcast(update, now));
  }

  ping(now: number): void {
    this.step(`ping(${now})`, () => this.b.ping(now));
  }

  drained(c: harness_Client, now: number): void {
    this.step(`drained(${c.name}, ${now})`, () => this.b.drained(c, now));
  }

  tick(now: number): void {
    this.step(`tick(${now})`, () => this.b.tick(now));
  }

  accept(c: harness_Client, value: boolean): void {
    this.set(`${c.name}.write returns ${value} from now on`, () => {
      c.accept = value;
    });
  }

  buffered(c: harness_Client, bytes: number): void {
    this.set(`${c.name}.bufferedBytes = ${bytes}`, () => {
      c.bufferedBytes = bytes;
    });
  }

  expectWritten(c: harness_Client, expected: string[]): void {
    const got = JSON.stringify(c.written);
    if (got !== JSON.stringify(expected)) {
      throw new Error(`${this.where()}: ${c.name} received ${got}, expected ${JSON.stringify(expected)}`);
    }
  }

  expectDestroyed(c: harness_Client, expected: number): void {
    if (c.destroyed !== expected) {
      throw new Error(`${this.where()}: ${c.name}.destroy() was called ${c.destroyed} time(s), expected ${expected}`);
    }
  }

  expectCounts(expected: number[]): void {
    const got = JSON.stringify(this.counts);
    if (got !== JSON.stringify(expected)) {
      throw new Error(`${this.where()}: onCount was called with ${got}, expected ${JSON.stringify(expected)}`);
    }
  }

  expectSize(expected: number): void {
    let size: number;
    try {
      size = this.b.size;
    } catch (error) {
      throw new Error(`${this.where()}: size threw ${harness_describe(error)}`);
    }
    if (size !== expected) throw new Error(`${this.where()}: size is ${size}, expected ${expected}`);
  }
}

const harness_PING = ": ping\n\n";

function harness_basics(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  const c2 = new harness_Client("c2");
  r.add(c1, "S", 0);
  r.add(c2, "S", 0);
  r.expectCounts([1, 2]);
  r.expectSize(2);
  r.expectWritten(c1, ["S"]);
  r.expectWritten(c2, ["S"]);
  r.broadcast("U1", 1);
  r.expectWritten(c1, ["S", "U1"]);
  r.expectWritten(c2, ["S", "U1"]);
  r.ping(2);
  r.expectWritten(c1, ["S", "U1", harness_PING]);
  r.expectWritten(c2, ["S", "U1", harness_PING]);
  r.expectDestroyed(c1, 0);
  r.expectDestroyed(c2, 0);
}

function harness_duplicateAdd(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.add(c1, "S", 0);
  r.add(c1, "S2", 5);
  r.expectCounts([1]);
  r.expectSize(1);
  r.expectWritten(c1, ["S"]);
  r.accept(c1, false);
  r.broadcast("U1", 6);
  r.add(c1, "S3", 7);
  r.broadcast("U2", 8);
  r.expectWritten(c1, ["S", "U1"]);
  r.accept(c1, true);
  r.drained(c1, 9);
  r.expectWritten(c1, ["S", "U1", "U2"]);
  r.expectCounts([1]);
}

function harness_cap(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  const c2 = new harness_Client("c2");
  r.add(c1, "S", 0);
  r.add(c2, "S", 0);
  r.buffered(c1, 94);
  r.broadcast("U12345", 1);
  r.expectWritten(c1, ["S", "U12345"]);
  r.expectDestroyed(c1, 0);
  r.buffered(c1, 95);
  r.broadcast("V12345", 2);
  r.expectDestroyed(c1, 1);
  r.expectWritten(c1, ["S", "U12345"]);
  r.expectWritten(c2, ["S", "U12345", "V12345"]);
  r.expectCounts([1, 2, 1]);
  r.expectSize(1);
  r.broadcast("W12345", 3);
  r.expectWritten(c1, ["S", "U12345"]);
  r.remove(c1);
  r.expectCounts([1, 2, 1]);
  r.expectDestroyed(c1, 1);
}

function harness_snapshotOverCap(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.buffered(c1, 99);
  r.add(c1, "SS", 0);
  r.expectDestroyed(c1, 1);
  r.expectWritten(c1, []);
  r.expectCounts([1, 0]);
  r.expectSize(0);
  r.buffered(c1, 0);
  r.add(c1, "S3", 1);
  r.expectWritten(c1, ["S3"]);
  r.expectCounts([1, 0, 1]);
  r.expectSize(1);
}

function harness_blocked(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.accept(c1, false);
  r.add(c1, "S", 0);
  r.accept(c1, true);
  r.ping(1);
  r.broadcast("U1", 2);
  r.broadcast("U2", 3);
  r.expectWritten(c1, ["S"]);
  r.drained(c1, 4);
  r.expectWritten(c1, ["S", "U2"]);
  r.drained(c1, 5);
  r.expectWritten(c1, ["S", "U2"]);
  r.broadcast("U3", 6);
  r.expectWritten(c1, ["S", "U2", "U3"]);
  r.expectDestroyed(c1, 0);
}

function harness_blockedWithoutUpdates(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.accept(c1, false);
  r.add(c1, "S", 0);
  r.accept(c1, true);
  r.ping(1);
  r.drained(c1, 2);
  r.expectWritten(c1, ["S"]);
  r.broadcast("U1", 3);
  r.expectWritten(c1, ["S", "U1"]);
}

function harness_timeout(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  const c2 = new harness_Client("c2");
  r.add(c2, "S", 0);
  r.accept(c1, false);
  r.add(c1, "S", 10);
  r.tick(1009);
  r.expectDestroyed(c1, 0);
  r.expectSize(2);
  r.tick(1010);
  r.expectDestroyed(c1, 1);
  r.expectDestroyed(c2, 0);
  r.expectCounts([1, 2, 1]);
  r.expectSize(1);
}

function harness_reblocked(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.accept(c1, false);
  r.add(c1, "S", 0);
  r.broadcast("U1", 100);
  r.drained(c1, 500);
  r.expectWritten(c1, ["S", "U1"]);
  r.tick(1499);
  r.expectDestroyed(c1, 0);
  r.tick(1500);
  r.expectDestroyed(c1, 1);
  r.expectCounts([1, 0]);
}

function harness_drainedOverCap(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.accept(c1, false);
  r.add(c1, "S", 0);
  r.broadcast("U12345", 1);
  r.accept(c1, true);
  r.buffered(c1, 95);
  r.drained(c1, 2);
  r.expectDestroyed(c1, 1);
  r.expectWritten(c1, ["S"]);
  r.expectCounts([1, 0]);
}

function harness_remove(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  const c2 = new harness_Client("c2");
  const c3 = new harness_Client("c3");
  r.add(c1, "S", 0);
  r.add(c2, "S", 0);
  r.remove(c1);
  r.expectDestroyed(c1, 0);
  r.expectCounts([1, 2, 1]);
  r.expectSize(1);
  r.remove(c1);
  r.remove(c3);
  r.expectCounts([1, 2, 1]);
  r.broadcast("U1", 1);
  r.expectWritten(c1, ["S"]);
  r.expectWritten(c2, ["S", "U1"]);
  r.accept(c2, false);
  r.broadcast("U2", 2);
  r.remove(c2);
  r.expectCounts([1, 2, 1, 0]);
  r.accept(c2, true);
  r.drained(c2, 3);
  r.expectWritten(c2, ["S", "U1", "U2"]);
  r.expectDestroyed(c2, 0);
}

function harness_readd(): void {
  const r = new harness_Run();
  const c1 = new harness_Client("c1");
  r.add(c1, "S", 0);
  r.remove(c1);
  r.add(c1, "S2", 5);
  r.expectCounts([1, 0, 1]);
  r.expectWritten(c1, ["S", "S2"]);
  r.expectSize(1);
}

const harness_scenarios: (() => void)[] = [
  harness_basics,
  harness_duplicateAdd,
  harness_cap,
  harness_snapshotOverCap,
  harness_blocked,
  harness_blockedWithoutUpdates,
  harness_timeout,
  harness_reblocked,
  harness_drainedOverCap,
  harness_remove,
  harness_readd,
];

for (const scenario of harness_scenarios) {
  try {
    scenario();
  } catch (error) {
    harness_failures.push(error instanceof Error ? error.message : String(error));
  }
}

if (harness_failures.length > 0) {
  for (const failure of harness_failures) console.log(failure);
  throw new Error(`harness: ${harness_failures.length} check(s) failed`);
}
console.log("harness: all checks passed");
