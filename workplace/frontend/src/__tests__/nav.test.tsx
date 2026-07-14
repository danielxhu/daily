import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

import { Nav } from "@/components/Nav";

describe("Nav (primary information architecture)", () => {
  it("shows the three user-task items in plain language", () => {
    render(<Nav />);
    for (const label of ["Today", "Sources", "Knowledge"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("keeps internal modules AND the removed Check out of the primary nav", () => {
    render(<Nav />);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const label of ["Check", "Trace", "Digest", "Memory", "Verify", "Boards"]) {
      expect(within(nav).queryByRole("link", { name: label })).toBeNull();
    }
  });

  it("marks the active route", () => {
    render(<Nav />);
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Sources" })).not.toHaveAttribute("aria-current");
  });
});
