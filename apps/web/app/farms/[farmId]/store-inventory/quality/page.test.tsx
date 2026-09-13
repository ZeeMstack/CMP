import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { queryKeys } from "@/lib/query/keys";
import { DEFAULT_TEST_BOOTSTRAP, TEST_TENANT_ID, withQueryClient } from "@/lib/test-utils";

import StoreInventoryQualityPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function queueRow(overrides: Record<string, unknown> = {}) {
  return {
    inventory_quantity_cohort_id: "coh-1", inventory_item_id: "item-1", item_name: "Calcium Nitrate",
    base_uom_id: "uom-1", inventory_lot_id: "lot-1", manufacturer_lot_reference: "LOT-1", expiry_date: null,
    received_at_farm_id: "farm-1", source_goods_receipt_line_id: "line-1", receipt_code: "GR-F1-20260907-001",
    receipt_received_at: "2026-09-07T08:00:00Z", balance: "500.000", current_state: "RECEIVED_QUARANTINED",
    current_event_id: "evt-1", last_actor_user_id: null, last_effective_time: null,
    ...overrides,
  };
}

function stubFetch(
  queue: unknown[],
  postHandler?: (url: string, body: unknown) => Response,
  breakdown?: unknown,
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!init || init.method === undefined) {
      if (url.endsWith("/quality-work-queue")) return jsonResponse(queue);
      if (url.includes("/storage-breakdown")) {
        return jsonResponse(
          breakdown ?? { inventory_quantity_cohort_id: "coh-1", not_put_away_quantity: "500.000", buckets: [] },
        );
      }
      return jsonResponse([]);
    }
    const body = init.body ? JSON.parse(String(init.body)) : {};
    if (postHandler) return postHandler(url, body);
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Like `withQueryClient`, but also hands back the `QueryClient` so a test
 * can directly manipulate the cache (e.g. simulate a background refetch
 * landing fresher data) without needing a real second network round trip. */
function renderWithClient(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.authBootstrap(), DEFAULT_TEST_BOOTSTRAP);
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
    </QueryClientProvider>,
  );
  return { ...utils, queryClient };
}

describe("StoreInventoryQualityPage", () => {
  it("offers Release / Hold / Reject for a RECEIVED_QUARANTINED row, but no correction actions", async () => {
    stubFetch([queueRow()]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Release" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hold" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct decision" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct decision for part of quantity" })).not.toBeInTheDocument();
  });

  it("offers only Correct decision(s) for a REJECTED row -- no ordinary Release", async () => {
    stubFetch([queueRow({ current_state: "REJECTED" })]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hold" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct decision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct decision for part of quantity" })).toBeInTheDocument();
  });

  it("offers Hold Release for a HELD row", async () => {
    stubFetch([queueRow({ current_state: "HELD" })]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Hold Release" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("offers 'Apply to part of quantity' for an actionable row", async () => {
    stubFetch([queueRow()]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Apply to part of quantity" })).toBeInTheDocument();
  });

  it("never offers correction actions for implicit RELEASED with no current event", async () => {
    stubFetch([queueRow({ current_state: "RELEASED", current_event_id: null })]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Correct decision" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct decision for part of quantity" })).not.toBeInTheDocument();
  });

  it("submits the row's current_event_id as target_event_id on a correction", async () => {
    let posted: unknown = null;
    stubFetch([queueRow({ current_state: "HELD", current_event_id: "evt-held-42" })], (url, body) => {
      if (url.endsWith("/quality-disposition-corrections")) {
        posted = body;
        return jsonResponse({
          reversal: { id: "rev-1", inventory_quantity_cohort_id: "coh-1", event_kind: "REVERSAL", reverses_event_id: "evt-held-42", effective_time: "2026-09-07T09:00:00Z", recorded_time: "2026-09-07T09:00:00Z", actor_user_id: "u1", reason: "fixed" },
          replacement: null,
        });
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision" }));
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "fixed" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as { target_event_id: string }).target_event_id).toBe("evt-held-42");
  });

  it("submits a 'Correct decision for part of quantity' command with quantity and corrected disposition", async () => {
    let posted: unknown = null;
    stubFetch([queueRow({ current_state: "REJECTED", current_event_id: "evt-rejected-7", balance: "100.000" })], (url, body) => {
      if (url.endsWith("/quality-partial-corrections")) {
        posted = body;
        return jsonResponse({
          child_cohort_id: "coh-child", source_cohort_id: "coh-1", target_event_id: "evt-rejected-7",
          quantity: "20", corrected_disposition: "RELEASED",
        });
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision for part of quantity" }));
    fireEvent.change(screen.getByLabelText(/Quantity/), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "wrongly rejected" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted).not.toBeNull());
    const body = posted as { target_event_id: string; quantity: string; corrected_disposition: string };
    expect(body.target_event_id).toBe("evt-rejected-7");
    expect(body.quantity).toBe("20");
    expect(body.corrected_disposition).toBe("RELEASED");
  });

  it("surfaces a segregation-of-duty conflict with the specific backend message, not a generic denial", async () => {
    stubFetch([queueRow()], (url) => {
      if (url.endsWith("/quality-dispositions")) {
        return jsonResponse(
          { detail: "you received this delivery -- another authorized user must release this quantity" },
          409,
        );
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    const confirmButtons = screen.getAllByRole("button", { name: "Confirm" });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);
    await waitFor(() =>
      expect(screen.getByText(/another authorized user must release this quantity/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/you don't have permission/i)).not.toBeInTheDocument();
    // PILOT-BLOCKER-005 CTO correction point 5: a 409 without the
    // stale-target `code` is a definitive rejection, not a stale-target
    // conflict -- Confirm must still be offered (the operator may retry,
    // e.g. once a different actor is available), never forced into a
    // "Close and reopen" state meant only for an actually-superseded target.
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  });

  it("surfaces a stale-target correction conflict verbatim", async () => {
    stubFetch([queueRow({ current_state: "HELD" })], (url) => {
      if (url.endsWith("/quality-disposition-corrections")) {
        return jsonResponse(
          {
            detail: {
              message: "Quality decision changed since you opened this action. Refresh and review the current decision.",
              code: "QUALITY_CORRECTION_TARGET_STALE",
            },
          },
          409,
        );
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision" }));
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "attempt" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText(/changed since you opened this action/i)).toBeInTheDocument());
  });

  it("STORE-INV-002B: offers an 'Affected location' bucket picker for a partial action with multiple buckets, and threads custody_location_id", async () => {
    let posted: unknown = null;
    stubFetch(
      [queueRow()],
      (url, body) => {
        if (url.endsWith("/quality-partial-dispositions")) {
          posted = body;
          return jsonResponse({ child_cohort_id: "coh-child", source_cohort_id: "coh-1", quantity: "30", disposition: "HELD" });
        }
        return jsonResponse({});
      },
      {
        inventory_quantity_cohort_id: "coh-1", not_put_away_quantity: "200.000",
        buckets: [
          { location_id: null, label: "Not put away", balance: "200.000" },
          { location_id: "bin-1", label: "Main Store / Bin 01", balance: "300.000" },
        ],
      },
    );
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Apply to part of quantity" }));

    await waitFor(() => expect(screen.getByText(/affected location/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/affected location/i), { target: { value: "bin-1" } });
    fireEvent.change(screen.getByLabelText(/^Quantity/), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as { custody_location_id: string | null }).custody_location_id).toBe("bin-1");
  });

  it("shows nothing-to-do message when the queue is empty", async () => {
    stubFetch([]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() =>
      expect(screen.getByText(/nothing currently needs quality attention/i)).toBeInTheDocument(),
    );
  });

  // --- PILOT-BLOCKER-005 -------------------------------------------------

  it("F04: opens the first Hold action for implicit RELEASED material with no current_event_id", async () => {
    let posted: unknown = null;
    stubFetch(
      [queueRow({ current_state: "RELEASED", current_event_id: null })],
      (url, body) => {
        if (url.endsWith("/quality-dispositions")) {
          posted = body;
          return jsonResponse({
            id: "evt-new", inventory_quantity_cohort_id: "coh-1", event_kind: "HELD", reverses_event_id: null,
            effective_time: "2026-09-07T09:00:00Z", recorded_time: "2026-09-07T09:00:00Z", actor_user_id: "u1",
            reason: null,
          });
        }
        return jsonResponse({});
      },
    );
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    // No correction actions are offered (nothing to correct yet)...
    expect(screen.queryByRole("button", { name: "Correct decision" })).not.toBeInTheDocument();
    // ...but the ordinary Hold action must still open, even with no prior event.
    fireEvent.click(screen.getByRole("button", { name: "Hold" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as { disposition: string }).disposition).toBe("HELD");
  });

  it("F06: a later queue refetch never retargets an already-open correction", async () => {
    let posted: unknown = null;
    stubFetch(
      [queueRow({ current_state: "HELD", current_event_id: "evt-held-original" })],
      (url, body) => {
        if (url.endsWith("/quality-disposition-corrections")) {
          posted = body;
          return jsonResponse({
            reversal: {
              id: "rev-1", inventory_quantity_cohort_id: "coh-1", event_kind: "REVERSAL",
              reverses_event_id: "evt-held-original", effective_time: "2026-09-07T09:00:00Z",
              recorded_time: "2026-09-07T09:00:00Z", actor_user_id: "u1", reason: "fixed",
            },
            replacement: null,
          });
        }
        return jsonResponse({});
      },
    );
    const { queryClient } = renderWithClient(<StoreInventoryQualityPage />);
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision" }));
    await waitFor(() => expect(screen.getByLabelText(/Reason \(required\)/)).toBeInTheDocument());

    // Simulate a background refetch landing fresher queue data -- as if
    // another operator recorded a newer decision -- while this correction
    // is still open.
    queryClient.setQueryData(
      queryKeys.qualityWorkQueue(TEST_TENANT_ID),
      [queueRow({ current_state: "REJECTED", current_event_id: "evt-rejected-newer" })],
    );

    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "fixed" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as { target_event_id: string }).target_event_id).toBe("evt-held-original");
  });

  it("F05: Retry after an uncertain (network) failure resends the same client_command_id and payload", async () => {
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    let callCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init || init.method === undefined) {
        if (url.endsWith("/quality-work-queue")) {
          return jsonResponse([queueRow({ current_state: "RELEASED", current_event_id: null })]);
        }
        return jsonResponse([]);
      }
      const body = init.body ? JSON.parse(String(init.body)) : {};
      if (url.endsWith("/quality-dispositions")) {
        callCount += 1;
        posts.push({ url, body });
        if (callCount === 1) throw new TypeError("Failed to fetch");
        return jsonResponse({
          id: "evt-new", inventory_quantity_cohort_id: "coh-1", event_kind: "HELD", reverses_event_id: null,
          effective_time: "2026-09-07T09:00:00Z", recorded_time: "2026-09-07T09:00:00Z", actor_user_id: "u1",
          reason: null,
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Hold" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    // The transport failure must never look like a definitive rejection --
    // it offers Retry, not a re-editable Confirm.
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].body.client_command_id).toBe(posts[0].body.client_command_id);
    expect(posts[1].body).toEqual(posts[0].body);
  });

  it("F08: a queue load failure never renders as the successful-empty state", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/quality-work-queue")) return jsonResponse({ detail: "boom" }, 500);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/nothing currently needs quality attention/i)).not.toBeInTheDocument();
  });

  it("F08: stale queue data stays visible with an error banner when a refresh fails", async () => {
    let queueCallCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/quality-work-queue")) {
        queueCallCount += 1;
        if (queueCallCount === 1) return jsonResponse([queueRow()]);
        return jsonResponse({ detail: "boom" }, 500);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { queryClient } = renderWithClient(<StoreInventoryQualityPage />);
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());

    await queryClient.refetchQueries({ queryKey: queryKeys.qualityWorkQueue(TEST_TENANT_ID) });

    await waitFor(() => expect(screen.getByText(/could not refresh the quality queue/i)).toBeInTheDocument());
    // The previously loaded row must still be visible, never replaced by
    // the empty-safe message.
    expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument();
    expect(screen.queryByText(/nothing currently needs quality attention/i)).not.toBeInTheDocument();
  });

  it("A6: a refresh failure against a genuinely EMPTY cached queue still shows the stale/error banner, never the successful-empty message", async () => {
    let queueCallCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/quality-work-queue")) {
        queueCallCount += 1;
        if (queueCallCount === 1) return jsonResponse([]);
        return jsonResponse({ detail: "boom" }, 500);
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { queryClient } = renderWithClient(<StoreInventoryQualityPage />);
    await waitFor(() =>
      expect(screen.getByText(/nothing currently needs quality attention/i)).toBeInTheDocument(),
    );

    await queryClient.refetchQueries({ queryKey: queryKeys.qualityWorkQueue(TEST_TENANT_ID) });

    // The cached list was (and still is) empty, but the refresh itself
    // failed -- this must render as stale/error, never silently fall back
    // to the successful-empty message just because rows.length === 0.
    await waitFor(() => expect(screen.getByText(/could not refresh the quality queue/i)).toBeInTheDocument());
    expect(screen.queryByText(/nothing currently needs quality attention/i)).not.toBeInTheDocument();
  });

  it("A2: opening a new Quality action is disabled while another command's outcome is uncertain", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init || init.method === undefined) {
        if (url.endsWith("/quality-work-queue")) {
          return jsonResponse([
            queueRow({ inventory_quantity_cohort_id: "coh-1", current_state: "RELEASED", current_event_id: null }),
            queueRow({ inventory_quantity_cohort_id: "coh-2", item_name: "Other Item", current_state: "RELEASED", current_event_id: null }),
          ]);
        }
        return jsonResponse([]);
      }
      if (url.endsWith("/quality-dispositions")) throw new TypeError("Failed to fetch");
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: "Hold" })[0]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    // Outcome is now "uncertain" (transport failure) -- every other
    // "open a new action" trigger, including on a completely different
    // row, must be disabled so a late response can never land on a
    // silently-abandoned draft.
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    const holdButtons = screen.getAllByRole("button", { name: "Hold" });
    expect(holdButtons[1]).toBeDisabled();
  });

  it("A2: Cancel is disabled for the whole uncertain state, not just while a retry is in flight", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init || init.method === undefined) {
        if (url.endsWith("/quality-work-queue")) {
          return jsonResponse([queueRow({ current_state: "RELEASED", current_event_id: null })]);
        }
        return jsonResponse([]);
      }
      if (url.endsWith("/quality-dispositions")) throw new TypeError("Failed to fetch");
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Hold" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByText(/result not confirmed/i)).toBeInTheDocument();
  });

  it("a stale-target conflict shows the conflict and never auto-retargets a retry", async () => {
    stubFetch([queueRow({ current_state: "HELD" })], (url) => {
      if (url.endsWith("/quality-disposition-corrections")) {
        return jsonResponse(
          {
            detail: {
              message: "Quality decision changed since you opened this action. Refresh and review the current decision.",
              code: "QUALITY_CORRECTION_TARGET_STALE",
            },
          },
          409,
        );
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision" }));
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "attempt" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText(/changed since you opened this action/i)).toBeInTheDocument());
    // Only a deliberate Close is offered -- never a Retry/Confirm that
    // would resubmit against the stale target.
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
