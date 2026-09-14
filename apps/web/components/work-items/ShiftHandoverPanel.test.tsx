import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ShiftHandoverRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import { ShiftHandoverPanel } from "./ShiftHandoverPanel";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ShiftHandoverPanel", () => {
  it("shows the latest handover's note without offering to close or edit any Work Item", () => {
    const latest: ShiftHandoverRead = {
      id: "h1", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
      effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:05Z",
      note: "GC-02 pump still needs a look.", work_item_ids: ["wi-1"],
    };
    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={latest} openWorkItems={[]} />));

    expect(screen.getByText("GC-02 pump still needs a look.")).toBeInTheDocument();
    expect(screen.getByText(/1 item\(s\) flagged/)).toBeInTheDocument();
    // No status/complete/close control is rendered by this panel at all --
    // it is a read display plus a note form, nothing else.
    expect(screen.queryByRole("button", { name: /complete/i })).not.toBeInTheDocument();
  });

  it("shows a truthful 'no handover yet' state rather than an empty note", () => {
    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    expect(screen.getByText("No handover recorded yet.")).toBeInTheDocument();
  });

  it("submitting a note posts to the shift-handovers endpoint and never touches a work-item endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/shift-handovers") && !url.includes("work-items")) {
        return jsonResponse({
          id: "h2", tenant_id: "t1", farm_id: "farm-1", author_user_id: "u1",
          effective_time: "2026-09-14T18:00:00Z", recorded_at: "2026-09-14T18:00:00Z",
          note: "Handover note", work_item_ids: [],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<ShiftHandoverPanel farmId="farm-1" latest={null} openWorkItems={[]} />));
    fireEvent.click(screen.getByRole("button", { name: "Leave a note" }));
    fireEvent.change(screen.getByPlaceholderText("What should the next shift know?"), {
      target: { value: "Handover note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save handover" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/farms/farm-1/shift-handovers"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const calledPaths = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledPaths.some((p) => /\/work-items\/.+\/(start|block|complete|cancel)/.test(p))).toBe(false);
  });
});
