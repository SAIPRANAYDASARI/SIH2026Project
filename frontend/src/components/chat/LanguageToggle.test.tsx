import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LanguageToggle } from "@/components/chat/LanguageToggle";

describe("LanguageToggle", () => {
  it("marks the current value as checked", () => {
    render(<LanguageToggle value="hi" onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: "हिंदी" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "English" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("calls onChange with the clicked option", async () => {
    const onChange = vi.fn();
    render(<LanguageToggle value="en" onChange={onChange} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "हिंदी" }));

    expect(onChange).toHaveBeenCalledWith("hi");
  });

  it("disables both options when disabled", () => {
    render(<LanguageToggle value="en" onChange={vi.fn()} disabled />);

    expect(screen.getByRole("radio", { name: "English" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "हिंदी" })).toBeDisabled();
  });
});
