import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WelcomeGate } from "@/components/WelcomeGate";
import { WelcomeHero } from "@/components/WelcomeHero";
import { LocaleProvider } from "@/lib/i18n";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
// motion libraries are exercised in the browser (e2e); unit tests cover content
vi.mock("gsap", () => ({
  default: { registerPlugin: vi.fn(), from: vi.fn(), ticker: { add: vi.fn(), remove: vi.fn(), lagSmoothing: vi.fn() } },
}));
vi.mock("gsap/ScrollTrigger", () => ({
  ScrollTrigger: { create: vi.fn(() => ({ kill: vi.fn() })), update: vi.fn() },
}));
vi.mock("lenis", () => ({ default: vi.fn(() => ({ on: vi.fn(), raf: vi.fn(), destroy: vi.fn() })) }));

function renderHero() {
  return render(
    <LocaleProvider>
      <WelcomeHero />
    </LocaleProvider>,
  );
}

describe("welcome page (hero · guide · boundaries)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    push.mockClear();
  });

  it("carries all three movements with the honest v0.13 boundaries", () => {
    renderHero();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /Everything you follow,\s*one page a day\./,
    );
    // guide steps (the old onboarding panel's job lives here now)
    expect(screen.getByText("Add your sources")).toBeInTheDocument();
    expect(screen.getByText("Read in context")).toBeInTheDocument();
    expect(screen.getByText("Ask your knowledge")).toBeInTheDocument();
    // the boundaries movement keeps honesty first-class
    expect(screen.getByText("Polling, not real-time")).toBeInTheDocument();
    expect(screen.getByText("Restating, not judging")).toBeInTheDocument();
    expect(screen.getByText(/labeled honestly/)).toBeInTheDocument();
    expect(screen.getByText(/No account\. No cloud\./)).toBeInTheDocument();
    // no check-era language anywhere
    expect(document.body.textContent).not.toMatch(/credibility|verdict|\/100|deep check/i);
  });

  it("Enter daily marks the visit and navigates home", () => {
    renderHero();
    fireEvent.click(screen.getAllByRole("button", { name: "Enter daily" })[0]);
    expect(window.localStorage.getItem("daily.onboarded")).toBe("1");
    expect(push).toHaveBeenCalledWith("/");
  });

  it("switches language in place — English-primary, 中文 one click away", () => {
    renderHero();
    fireEvent.click(screen.getByRole("button", { name: "Switch language" }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("你关注的一切");
    expect(screen.getByText("轮询,不是实时")).toBeInTheDocument();
  });
});

describe("first-visit gate", () => {
  beforeEach(() => window.localStorage.clear());

  it("sends a first visit to /welcome", () => {
    const navigate = vi.fn();
    render(<WelcomeGate navigate={navigate} />);
    expect(navigate).toHaveBeenCalledWith("/welcome");
  });

  it("leaves returning users on the page", () => {
    window.localStorage.setItem("daily.onboarded", "1");
    const navigate = vi.fn();
    render(<WelcomeGate navigate={navigate} />);
    expect(navigate).not.toHaveBeenCalled();
  });
});
