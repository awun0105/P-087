/** Run CPU steps in short slices so input and paint can run between slices. */
export async function runCooperatively<T>(steps: Generator<void, T>, signal?: AbortSignal): Promise<T> {
  let deadline = performance.now() + 8;
  try {
    while (true) {
      signal?.throwIfAborted();
      const next = steps.next();
      if (next.done) return next.value;
      if (performance.now() >= deadline) {
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
        deadline = performance.now() + 8;
      }
    }
  } finally {
    steps.return(undefined as T);
  }
}
