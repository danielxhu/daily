import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { HelpButton } from "@/components/HelpButton";
import { Onboarding } from "@/components/Onboarding";
import { LocaleProvider } from "@/lib/i18n";

function renderGuide() {
  return render(
    <LocaleProvider>
      <HelpButton />
      <Onboarding />
    </LocaleProvider>,
  );
}

describe("first-run guide (M11.2)", () => {
  beforeEach(() => window.localStorage.clear());

  it("shows on first visit, with the honest boundaries in the copy (v0.13)", () => {
    renderGuide();
    expect(screen.getByText("Welcome to daily")).toBeInTheDocument();
    // the three steps guide the core loop: sources → reading items → knowledge
    // (M16.1: the check surface is retired — no score/verdict language anywhere)
    expect(screen.getByRole("link", { name: "Add your sources" })).toHaveAttribute(
      "href",
      "/tracking",
    );
    expect(screen.getByText("Read each item in context")).toBeInTheDocument();
    expect(screen.getByText(/only restates what the source says/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask Knowledge" })).toHaveAttribute(
      "href",
      "/knowledge",
    );
    // honesty: not real time; daily never judges content for the user
    expect(screen.getByText(/not in real time/)).toBeInTheDocument();
    expect(screen.getByText(/never judges content for you/)).toBeInTheDocument();
    // the retired check-era language must not come back
    const guide = screen.getByRole("region", { name: "Welcome to daily" });
    expect(guide.textContent).not.toMatch(/score|credibility|verdict|deep check/i);
  });

  it("dismisses, persists the choice, and stays hidden for returning users", () => {
    renderGuide();
    fireEvent.click(screen.getByRole("button", { name: "Got it — take me to daily" }));
    expect(screen.queryByText("Welcome to daily")).toBeNull();
    expect(window.localStorage.getItem("daily.onboarded")).toBe("1");

    // a returning user (flag already set) never sees it
    renderGuide();
    expect(screen.queryByText("Welcome to daily")).toBeNull();
  });

  it("reopens any time from the labeled header Guide button (M16.1: no cryptic ?)", () => {
    window.localStorage.setItem("daily.onboarded", "1");
    renderGuide();
    expect(screen.queryByText("Welcome to daily")).toBeNull();
    const guideBtn = screen.getByRole("button", { name: "Open the guide" });
    expect(guideBtn).toHaveTextContent("Guide");
    fireEvent.click(guideBtn);
    expect(screen.getByText("Welcome to daily")).toBeInTheDocument();
  });

  it("renders in Chinese when the zh locale is saved", () => {
    window.localStorage.setItem("daily.locale", "zh");
    renderGuide();
    expect(screen.getByText("欢迎使用 daily")).toBeInTheDocument();
    expect(screen.getByText(/只转述来源的说法/)).toBeInTheDocument();
    expect(screen.getByText(/不是实时推送/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开指引" })).toHaveTextContent("指引");
    expect(screen.getByRole("button", { name: "知道了，开始使用" })).toBeInTheDocument();
  });
});
