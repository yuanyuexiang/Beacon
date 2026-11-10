/** Schedule external initialization after the commit, cancelling abandoned setups.
 *
 * React Strict Mode may clean an effect up before its async initialization starts.
 * In that case neither the request/timer setup nor its state writes should run.
 * Existing effect cleanups still run when initialization has already started.
 */
export function afterCommit(setup: () => void | (() => void)): () => void {
  let disposed = false;
  let cleanup: void | (() => void);
  queueMicrotask(() => {
    if (!disposed) cleanup = setup();
  });
  return () => {
    disposed = true;
    cleanup?.();
  };
}
