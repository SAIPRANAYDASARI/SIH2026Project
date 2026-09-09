import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView (used by ChatWindow/CitationPanel
// to auto-scroll to new messages/citations) — a harmless no-op in tests.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}

// jsdom doesn't implement ResizeObserver (used by Recharts' ResponsiveContainer
// on the Step 11 officer dashboard) — a harmless no-op stub in tests.
if (!("ResizeObserver" in window)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).ResizeObserver = ResizeObserverStub;
}
