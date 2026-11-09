export function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (!Number.isInteger(limit) || limit < 1) {
    return Promise.reject(new RangeError(`limit must be a positive integer, got ${limit}`));
  }
  // The executor runs synchronously, so the first calls start before mapLimit returns.
  return new Promise<R[]>((resolve, reject) => {
    const results: R[] = new Array<R>(items.length);
    let next = 0;
    let running = 0;
    let done = 0;
    let failed = false;

    const fail = (error: unknown) => {
      if (failed) return;
      failed = true;
      reject(error);
    };

    const launch = () => {
      while (!failed && running < limit && next < items.length) {
        const index = next++;
        running++;
        let call: Promise<R>;
        try {
          call = fn(items[index], index);
        } catch (error) {
          fail(error);
          return;
        }
        call.then(
          (value) => {
            running--;
            results[index] = value;
            done++;
            if (done === items.length) resolve(results);
            else launch();
          },
          (error: unknown) => {
            running--;
            fail(error);
          },
        );
      }
    };

    if (items.length === 0) resolve([]);
    else launch();
  });
}
