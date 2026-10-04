// Mock-build handshake (NEXT_PUBLIC_API_MOCK=1 only). The MSW worker starts in a
// MockProvider effect, but children's mount effects run first — so a view's first
// fetch can race the worker, pass through to a nonexistent backend, and render an
// error state. lib/api awaits this deferred before any request in mock builds;
// MockProvider resolves it once worker.start() completes. Real builds never call
// either side (the inlined env check is false).

type MswWindow = Window & {
  __mswReady?: Promise<void>;
  __mswReadyResolve?: () => void;
};

/** The deferred "worker is intercepting" promise (created on first access). */
export function mswReady(): Promise<void> {
  const w = window as MswWindow;
  if (!w.__mswReady) {
    w.__mswReady = new Promise<void>((resolve) => {
      w.__mswReadyResolve = resolve;
    });
  }
  return w.__mswReady;
}

/** Resolve the deferred (called by MockProvider after worker.start()). */
export function resolveMswReady(): void {
  const w = window as MswWindow;
  void mswReady(); // ensure the deferred exists even if no request ran yet
  w.__mswReadyResolve?.();
}
