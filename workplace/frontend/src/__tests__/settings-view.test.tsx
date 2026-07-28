import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsView } from "@/components/SettingsView";
import type { getApiSettings } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n";
import type { ApiSlotView } from "@/types/contract";

const ENV_TEXT: ApiSlotView = {
  slot: "text",
  source: "env",
  base_url: "https://api.deepseek.com",
  model: "deepseek-v4-flash",
  key_last4: null,
};
const EMPTY_VISION: ApiSlotView = {
  slot: "vision",
  source: "empty",
  base_url: null,
  model: null,
  key_last4: null,
};

describe("SettingsView (model API credentials, 2026-07-23)", () => {
  it("shows both slots: env-backed text and empty vision", async () => {
    const getFn = vi.fn(async () => ({ slots: [ENV_TEXT, EMPTY_VISION] }));
    render(<SettingsView getFn={getFn} />);
    expect(await screen.findByText("Text model (required)")).toBeInTheDocument();
    expect(screen.getByText("Vision model (optional)")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    // honest local-only note, and no key material anywhere
    expect(screen.getByText(/stored only in the local database/)).toBeInTheDocument();
  });

  it("offers the language choice, marking the current one", async () => {
    const getFn = vi.fn(async () => ({ slots: [ENV_TEXT, EMPTY_VISION] }));
    render(
      <LocaleProvider>
        <SettingsView getFn={getFn} />
      </LocaleProvider>,
    );
    // client-side setting — present immediately, not gated on the API load
    const zh = screen.getByRole("button", { name: "中文" });
    const en = screen.getByRole("button", { name: "English" });
    expect(en).toHaveAttribute("aria-pressed", "true"); // tests render in English
    fireEvent.click(zh);
    expect(zh).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("文本模型(必填)")).toBeInTheDocument();
  });

  it("switches the theme and writes it where the token layer reads it", async () => {
    window.localStorage.clear(); // no locale/theme choice left over from another test
    const getFn = vi.fn(async () => ({ slots: [ENV_TEXT, EMPTY_VISION] }));
    render(
      <LocaleProvider>
        <SettingsView getFn={getFn} />
      </LocaleProvider>,
    );
    const light = screen.getByRole("button", { name: "Light" });
    const dark = screen.getByRole("button", { name: "Dark" });
    expect(light).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(dark);
    expect(dark).toHaveAttribute("aria-pressed", "true");
    // the whole token layer keys off this attribute, so it must reach the root
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("daily.theme")).toBe("dark");

    fireEvent.click(light);
    expect(document.documentElement.dataset.theme).toBe("light");
    await screen.findByText("Text model (required)");
  });

  it("saves a custom text endpoint and shows the masked key", async () => {
    let slots: ApiSlotView[] = [ENV_TEXT, EMPTY_VISION];
    const getFn = vi.fn(async () => ({ slots })) as unknown as typeof getApiSettings;
    const saveFn = vi.fn(
      async (slot: string, input: { base_url: string; model: string; api_key: string }) => {
        const view: ApiSlotView = {
          slot: slot as "text" | "vision",
          source: "custom",
          base_url: input.base_url,
          model: input.model,
          key_last4: input.api_key.slice(-4),
        };
        slots = [view, EMPTY_VISION];
        return view;
      },
    );
    render(<SettingsView getFn={getFn} saveFn={saveFn} />);
    await screen.findByText("Text model (required)");

    fireEvent.change(screen.getAllByLabelText(/Base URL/)[0], {
      target: { value: "https://api.example.cn/v1" },
    });
    fireEvent.change(screen.getAllByLabelText(/^Model$/)[0], {
      target: { value: "their-model" },
    });
    fireEvent.change(screen.getAllByLabelText(/API key/)[0], {
      target: { value: "sk-secret9876" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() =>
      expect(saveFn).toHaveBeenCalledWith("text", {
        base_url: "https://api.example.cn/v1",
        model: "their-model",
        api_key: "sk-secret9876",
      }),
    );
    // the re-loaded view shows the custom endpoint with ONLY the last 4 key chars
    expect(await screen.findByText(/····9876/)).toBeInTheDocument();
    expect(screen.queryByText(/sk-secret9876/)).not.toBeInTheDocument();
  });

  it("save stays disabled until all three fields are filled", async () => {
    const getFn = vi.fn(async () => ({ slots: [ENV_TEXT, EMPTY_VISION] }));
    render(<SettingsView getFn={getFn} />);
    await screen.findByText("Text model (required)");
    const save = screen.getAllByRole("button", { name: "Save" })[0];
    expect(save).toBeDisabled();
    fireEvent.change(screen.getAllByLabelText(/Base URL/)[0], {
      target: { value: "https://x/v1" },
    });
    expect(save).toBeDisabled();
  });
});
