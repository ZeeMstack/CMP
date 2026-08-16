import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SeedlingDispositionEventRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { CorrectDispositionForm } from "./CorrectDispositionForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const REASONS = [
  { code: "WEAK_SEEDLING", name: "Weak seedling" },
  { code: "DISEASE", name: "Disease" },
  { code: "OTHER", name: "Other" },
];

const TARGET: SeedlingDispositionEventRead = {
  id: "evt-1", command_id: "cmd-1", seedling_entry_id: "se-1", event_kind: "REDUCTION",
  reason_code: "WEAK_SEEDLING", quantity_delta: -4, effective_time: "2026-08-10T09:00:00Z",
  note: null, reverses_event_id: null, corrects_event_id: null, actor_user_id: "user-1",
  recorded_at: "2026-08-10T09:00:01Z",
};

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/nursery/seedling/disposition-reasons")) return jsonResponse(REASONS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CorrectDispositionForm", () => {
  it("defaults to Void and submits corrected: null with no replacement fields", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <CorrectDispositionForm farmId="farm-1" target={TARGET} onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />,
      ),
    );
    expect(screen.getByRole("radio", { name: /never have been recorded/i })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Confirm void" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual({ client_command_id: expect.any(String), corrected: null });
  });

  it("Replace mode requires quantity/reason/date/time and submits a corrected replacement payload", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(
      withQueryClient(
        <CorrectDispositionForm farmId="farm-1" target={TARGET} onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />,
      ),
    );
    fireEvent.click(screen.getByRole("radio", { name: /recorded incorrectly/i }));
    await waitFor(() => expect(screen.getByRole("option", { name: "Disease" })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "DISEASE" } });
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-08-11" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.corrected.quantity).toBe(3);
    expect(payload.corrected.reason_code).toBe("DISEASE");
    expect(payload.corrected.effective_time).toBe(new Date("2026-08-11T10:00").toISOString());
  });

  it("shows a server error and calls onCancel without submitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(
      withQueryClient(
        <CorrectDispositionForm
          farmId="farm-1" target={TARGET} onSubmit={onSubmit} onCancel={onCancel} isSubmitting={false}
          serverError="This entry has already been corrected."
        />,
      ),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/already been corrected/i);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
