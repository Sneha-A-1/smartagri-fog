import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { type JsonSchema, SchemaForm } from "./SchemaForm";

const schema: JsonSchema = {
  properties: {
    days: { type: "integer", title: "Days", minimum: 1, maximum: 365, "x-unit": "days", description: "Length." },
    noise_std: { type: "number", title: "Noise Std", "x-advanced": true },
    enabled: { type: "boolean", title: "Enabled" },
  },
};

describe("SchemaForm", () => {
  it("renders essential fields and hides advanced ones in beginner mode", () => {
    render(<SchemaForm schema={schema} values={{ days: 30 }} onChange={() => {}} showAdvanced={false} />);
    expect(screen.getByLabelText(/Days/)).toHaveProperty("value", "30");
    expect(screen.queryByLabelText(/Noise std/)).toBeNull();
    expect(screen.getByText(/1 advanced setting is hidden/)).toBeTruthy();
    expect(screen.getByText(/Range 1 to 365 days/)).toBeTruthy();
  });

  it("shows advanced fields in researcher mode", () => {
    render(<SchemaForm schema={schema} values={{}} onChange={() => {}} showAdvanced />);
    expect(screen.getByLabelText(/Noise std/)).toBeTruthy();
  });

  it("emits typed values", () => {
    const onChange = vi.fn();
    render(<SchemaForm schema={schema} values={{ days: 30 }} onChange={onChange} showAdvanced={false} />);
    fireEvent.change(screen.getByLabelText(/Days/), { target: { value: "12" } });
    expect(onChange).toHaveBeenCalledWith({ days: 12 });
  });

  it("shows a field error instead of help text", () => {
    render(<SchemaForm schema={schema} values={{ days: 0 }} onChange={() => {}} errors={{ days: "Too small" }} showAdvanced={false} />);
    expect(screen.getByText("Too small")).toBeTruthy();
  });
});
