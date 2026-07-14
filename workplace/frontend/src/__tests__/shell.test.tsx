import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Shell } from "@/components/Shell";

describe("Shell", () => {
  it("renders children inside a responsive, centered container", () => {
    render(
      <Shell>
        <p>hello</p>
      </Shell>,
    );
    const child = screen.getByText("hello");
    const container = child.parentElement as HTMLElement;
    // mobile-first padding that grows at the sm breakpoint = responsive
    expect(container.className).toContain("max-w-3xl");
    expect(container.className).toContain("px-4");
    expect(container.className).toContain("sm:px-6");
  });

  it("matches the layout snapshot", () => {
    const { container } = render(
      <Shell>
        <p>content</p>
      </Shell>,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
