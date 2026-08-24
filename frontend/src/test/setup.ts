import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { server } from './msw-handlers';

// MSW lifecycle
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom stubs for browser APIs the app touches
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}
// The Web Audio engine is not available in jsdom; make it a harmless no-op.
class FakeAudioContext {
  currentTime = 0;
  destination = {};
  createOscillator() {
    return {
      connect() {},
      start() {},
      stop() {},
      type: '',
      frequency: {
        setValueAtTime() {},
        exponentialRampToValueAtTime() {},
        linearRampToValueAtTime() {},
      },
    };
  }
  createGain() {
    return {
      connect() {},
      gain: {
        setValueAtTime() {},
        exponentialRampToValueAtTime() {},
        linearRampToValueAtTime() {},
      },
    };
  }
}
// @ts-expect-error test stub
window.AudioContext = window.AudioContext || FakeAudioContext;
// @ts-expect-error test stub
window.webkitAudioContext = window.webkitAudioContext || FakeAudioContext;

if (!('IntersectionObserver' in window)) {
  // @ts-expect-error test stub
  window.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
