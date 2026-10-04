import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MockProvider } from "@/components/MockProvider";

// vitest runs WITHOUT NEXT_PUBLIC_API_MOCK — i.e. the real-mode branch (M13.6).

describe("MockProvider in real mode (M13.6 mock-leak hygiene)", () => {
  afterEach(() => {
    // jsdom has no navigator.serviceWorker by default; clean up what we defined
    delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  });

  it("unregisters a leftover MSW service worker, leaving others alone", async () => {
    // the beta P2 scenario: a previous `dev:mock` session registered MSW on this
    // origin — a real session must not keep serving Acme/Beta fixture data
    const unregisterMsw = vi.fn();
    const unregisterOther = vi.fn();
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: {
        getRegistrations: async () => [
          {
            active: { scriptURL: "http://localhost:3000/mockServiceWorker.js" },
            unregister: unregisterMsw,
          },
          {
            active: { scriptURL: "http://localhost:3000/some-other-sw.js" },
            unregister: unregisterOther,
          },
        ],
      },
    });

    render(
      <MockProvider>
        <div />
      </MockProvider>,
    );
    await waitFor(() => expect(unregisterMsw).toHaveBeenCalled());
    expect(unregisterOther).not.toHaveBeenCalled();
  });

  it("tolerates browsers without service-worker support", async () => {
    // no navigator.serviceWorker at all (non-secure origin) — must not throw
    expect(() =>
      render(
        <MockProvider>
          <div data-testid="child" />
        </MockProvider>,
      ),
    ).not.toThrow();
  });
});
