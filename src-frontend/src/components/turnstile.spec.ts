import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The loader only touches `window.turnstile`, `document.createElement` and
// `document.head.appendChild`, so under the node environment a stand-in for
// those three is the whole browser.
interface FakeScript {
  src?: string;
  onload?: (() => void) | null;
  onerror?: (() => void) | null;
}

let appended: FakeScript[];

beforeEach(() => {
  appended = [];
  vi.useFakeTimers();
  vi.stubGlobal('window', {});
  vi.stubGlobal('document', {
    createElement: () => ({}),
    head: { appendChild: (script: FakeScript) => appended.push(script) },
  });
  // The load is cached at module level, so each test needs a fresh copy.
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function importLoader() {
  return (await import('./turnstile')).loadTurnstile;
}

describe('loadTurnstile', () => {
  it('injects one explicit-render script and shares it between callers', async () => {
    const loadTurnstile = await importLoader();

    const first = loadTurnstile();
    const second = loadTurnstile();
    expect(second).toBe(first);
    expect(appended).toHaveLength(1);
    expect(appended[0].src).toContain('render=explicit');

    appended[0].onload?.();
    await expect(first).resolves.toBeUndefined();

    // The load timeout must not fire on a script that already arrived.
    vi.runAllTimers();
    expect(loadTurnstile()).toBe(first);
    expect(appended).toHaveLength(1);
  });

  it('skips the script when Turnstile is already on the page', async () => {
    vi.stubGlobal('window', { turnstile: {} });
    const loadTurnstile = await importLoader();

    await expect(loadTurnstile()).resolves.toBeUndefined();
    expect(appended).toHaveLength(0);
  });

  it('loads again after a failure instead of caching the rejection', async () => {
    const loadTurnstile = await importLoader();

    const failed = loadTurnstile();
    appended[0].onerror?.();
    await expect(failed).rejects.toThrow();

    const retried = loadTurnstile();
    expect(retried).not.toBe(failed);
    expect(appended).toHaveLength(2);

    appended[1].onload?.();
    await expect(retried).resolves.toBeUndefined();
  });

  it('gives up on a script that never finishes loading', async () => {
    const loadTurnstile = await importLoader();

    const stalled = loadTurnstile();
    vi.runAllTimers();
    await expect(stalled).rejects.toThrow();

    expect(loadTurnstile()).not.toBe(stalled);
  });

  it('ignores a load it gave up on when that load finally fails', async () => {
    const loadTurnstile = await importLoader();

    const stalled = loadTurnstile();
    vi.runAllTimers();
    await expect(stalled).rejects.toThrow();
    const retried = loadTurnstile();

    appended[0].onerror?.();
    expect(loadTurnstile()).toBe(retried);
  });
});
