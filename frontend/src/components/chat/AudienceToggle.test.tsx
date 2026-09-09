import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AudienceToggle } from "@/components/chat/AudienceToggle";

describe("AudienceToggle", () => {
  it("marks the current value as checked", () => {
    render(<AudienceToggle value="industry" onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: "Industry" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Consumer" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("calls onChange with the clicked option", async () => {
    const onChange = vi.fn();
    render(<AudienceToggle value="consumer" onChange={onChange} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Industry" }));

    expect(onChange).toHaveBeenCalledWith("industry");
  });

  it("disables both options when disabled", () => {
    render(<AudienceToggle value="consumer" onChange={vi.fn()} disabled />);

    expect(screen.getByRole("radio", { name: "Consumer" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Industry" })).toBeDisabled();
  });
});
