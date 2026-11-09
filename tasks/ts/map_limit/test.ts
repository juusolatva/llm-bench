import { mapLimit } from "./solution.js";

const harness_failures: string[] = [];

function harness_describe(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${JSON.stringify(error.message)}` : String(error);
}

interface harness_Deferred<R> {
  promise: Promise<R>;
  resolve(value: R): void;
  reject(error: unknown): void;
}

function harness_deferred<R>(): harness_Deferred<R> {
  let resolve!: (value: R) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<R>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Lets every pending promise reaction run. */
function harness_flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** Records the calls of fn; each call returns a promise the scenario settles by hand. */
class harness_Recorder<T, R> {
  started: number[] = [];
  args: [T, number][] = [];
  calls: harness_Deferred<R>[] = [];
  pending = 0;
  maxPending = 0;
  fn = (item: T, index: number): Promise<R> => {
    this.started.push(index);
    this.args.push([item, index]);
    const call = harness_deferred<R>();
    this.calls[index] = call;
    this.pending++;
    this.maxPending = Math.max(this.maxPending, this.pending);
    const done = () => {
      this.pending--;
    };
    call.promise.then(done, done);
    return call.promise;
  };
}

type harness_Outcome<R> = { state: "pending" } | { state: "fulfilled"; value: R[] } | { state: "rejected"; error: unknown };

/** Starts mapLimit and tracks its promise; a synchronous throw ends the scenario. */
class harness_Scenario<T, R> {
  readonly rec = new harness_Recorder<T, R>();
  readonly steps: string[] = [];
  outcome: harness_Outcome<R> = { state: "pending" };

  constructor(readonly call: string, items: readonly T[], limit: number) {
    let promise: Promise<R[]>;
    try {
      promise = mapLimit(items, limit, this.rec.fn);
    } catch (error) {
      throw new Error(`${call} threw ${harness_describe(error)} synchronously, expected it to return a promise`);
    }
    promise.then(
      (value) => {
        this.outcome = { state: "fulfilled", value };
      },
      (error: unknown) => {
        this.outcome = { state: "rejected", error };
      },
    );
  }

  where(): string {
    return `${this.call}: after ${this.steps.length > 0 ? this.steps.join(", ") : "it returned"}`;
  }

  expectStarted(expected: number[]): void {
    const got = JSON.stringify(this.rec.started);
    if (got !== JSON.stringify(expected)) {
      throw new Error(`${this.where()}, fn was called for the indexes ${got}, expected ${JSON.stringify(expected)}`);
    }
  }

  expectPending(): void {
    if (this.outcome.state !== "pending") {
      throw new Error(`${this.where()}, the promise is ${this.show()}, expected it to be still pending`);
    }
  }

  show(): string {
    const o = this.outcome;
    if (o.state === "fulfilled") return `fulfilled with ${JSON.stringify(o.value)}`;
    if (o.state === "rejected") return `rejected with ${harness_describe(o.error)}`;
    return "still pending";
  }

  async resolve(index: number, value: R): Promise<void> {
    this.rec.calls[index].resolve(value);
    this.steps.push(`call ${index} resolved with ${JSON.stringify(value)}`);
    await harness_flush();
  }

  async reject(index: number, error: Error): Promise<void> {
    this.rec.calls[index].reject(error);
    this.steps.push(`call ${index} rejected with ${harness_describe(error)}`);
    await harness_flush();
  }
}

async function harness_inOrder(): Promise<void> {
  const items = ["a", "b", "c", "d", "e"];
  const s = new harness_Scenario<string, string>('mapLimit(["a","b","c","d","e"], 2, fn)', items, 2);
  s.expectStarted([0, 1]);
  await s.resolve(1, "B");
  s.expectStarted([0, 1, 2]);
  await s.resolve(0, "A");
  s.expectStarted([0, 1, 2, 3]);
  await s.resolve(3, "D");
  s.expectStarted([0, 1, 2, 3, 4]);
  await s.resolve(4, "E");
  s.expectPending();
  await s.resolve(2, "C");
  const want = '["A","B","C","D","E"]';
  if (s.outcome.state !== "fulfilled" || JSON.stringify(s.outcome.value) !== want) {
    throw new Error(`${s.where()}, the promise is ${s.show()}, expected fulfilled with ${want}`);
  }
  if (s.rec.maxPending > 2) throw new Error(`${s.call}: ${s.rec.maxPending} calls were pending at once, expected at most 2`);
  const args = JSON.stringify(s.rec.args);
  const wantArgs = '[["a",0],["b",1],["c",2],["d",3],["e",4]]';
  if (args !== wantArgs) throw new Error(`${s.call}: fn was called with (item, index) ${args}, expected ${wantArgs}`);
}

async function harness_limitAboveLength(): Promise<void> {
  const s = new harness_Scenario<number, number>("mapLimit([1,2,3], 10, fn)", [1, 2, 3], 10);
  s.expectStarted([0, 1, 2]);
  await s.resolve(2, 30);
  await s.resolve(0, 10);
  await s.resolve(1, 20);
  if (s.outcome.state !== "fulfilled" || JSON.stringify(s.outcome.value) !== "[10,20,30]") {
    throw new Error(`${s.where()}, the promise is ${s.show()}, expected fulfilled with [10,20,30]`);
  }
}

async function harness_sequential(): Promise<void> {
  const s = new harness_Scenario<string, number>('mapLimit(["x","y","z"], 1, fn)', ["x", "y", "z"], 1);
  s.expectStarted([0]);
  await s.resolve(0, 1);
  s.expectStarted([0, 1]);
  await s.resolve(1, 2);
  s.expectStarted([0, 1, 2]);
  await s.resolve(2, 3);
  if (s.outcome.state !== "fulfilled" || JSON.stringify(s.outcome.value) !== "[1,2,3]") {
    throw new Error(`${s.where()}, the promise is ${s.show()}, expected fulfilled with [1,2,3]`);
  }
}

async function harness_rejection(): Promise<void> {
  const s = new harness_Scenario<number, number>("mapLimit([1,2,3,4], 2, fn)", [1, 2, 3, 4], 2);
  s.expectStarted([0, 1]);
  const boom = new Error("boom");
  await s.reject(1, boom);
  if (s.outcome.state !== "rejected") {
    throw new Error(`${s.where()}, the promise is ${s.show()}, expected rejected with the error of call 1 at once`);
  }
  if (s.outcome.error !== boom) {
    throw new Error(`${s.where()}, the promise is ${s.show()}, expected rejected with the same Error object call 1 rejected with`);
  }
  s.expectStarted([0, 1]);
  await s.resolve(0, 10);
  s.expectStarted([0, 1]);
}

async function harness_empty(): Promise<void> {
  const s = new harness_Scenario<number, number>("mapLimit([], 3, fn)", [], 3);
  await harness_flush();
  s.expectStarted([]);
  if (s.outcome.state !== "fulfilled" || JSON.stringify(s.outcome.value) !== "[]") {
    throw new Error(`${s.call}: the promise is ${s.show()}, expected fulfilled with []`);
  }
}

async function harness_badLimit(limit: number): Promise<void> {
  const s = new harness_Scenario<number, number>(`mapLimit([1,2], ${limit}, fn)`, [1, 2], limit);
  await harness_flush();
  if (s.outcome.state !== "rejected" || !(s.outcome.error instanceof RangeError)) {
    throw new Error(`${s.call}: the promise is ${s.show()}, expected rejected with a RangeError`);
  }
  s.expectStarted([]);
}

const harness_scenarios: (() => Promise<void>)[] = [
  harness_inOrder,
  harness_limitAboveLength,
  harness_sequential,
  harness_rejection,
  harness_empty,
  ...[0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY].map((limit) => () => harness_badLimit(limit)),
];

for (const scenario of harness_scenarios) {
  try {
    await scenario();
  } catch (error) {
    harness_failures.push(error instanceof Error ? error.message : String(error));
  }
}

if (harness_failures.length > 0) {
  for (const failure of harness_failures) console.log(failure);
  throw new Error(`harness: ${harness_failures.length} check(s) failed`);
}
console.log("harness: all checks passed");
