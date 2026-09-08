import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import StoreInventoryIssuePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ITEM = {
  id: "item-1", tenant_id: "t", code: "CALCIUM-NITRATE", name: "Calcium Nitrate", inventory_category_id: "cat-1",
  base_uom_id: "uom-1", lot_tracking_required: true, expiry_tracking_required: false, qc_release_required: false,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};

const UOM = { id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "mass" };

// Exactly one usable source -- the "Issue now" / drawer source picker must
// auto-default it (compact UX rule) rather than force an extra tap.
const SOURCE = {
  inventory_quantity_cohort_id: "cohort-1", inventory_lot_id: "lot-1", lot_label: "LOT-1",
  source_location_id: "bin-1", bin_label: "Bin 01", balance: "20.000",
};

const RESERVATION = {
  id: "res-1", tenant_id: "t", farm_id: "farm-1", code: "RES-0001", purpose: "Seeding WO-1",
  requested_by_user_id: "u1", effective_time: "2026-09-01T00:00:00Z", recorded_time: "2026-09-01T00:00:00Z",
  lines: [
    {
      id: "line-1", inventory_item_id: "item-1", requested_quantity_base: "8.000", remaining_quantity_base: "8.000",
      blocked_by_quality: false,
    },
  ],
};

const OUTSTANDING_ROW = {
  issue_line_id: "line-9", issue_id: "iss-9", issue_code: "ISS-0009", purpose: "Fertigation prep",
  inventory_item_id: "item-1", item_name: "Calcium Nitrate", base_uom_id: "uom-1", inventory_lot_id: "lot-1",
  manufacturer_lot_reference: "LOT-1", source_location_id: "bin-1", issued_quantity: "10.000",
  outstanding_quantity: "6.000",
};

type PostHandler = (url: string, body: Record<string, unknown>) => Response;

function stubFetch(
  opts: { reservations?: unknown[]; outstanding?: unknown[]; locationsTree?: unknown[]; postHandler?: PostHandler } = {},
) {
  const reservations = opts.reservations ?? [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = init.body ? JSON.parse(String(init.body)) : {};
      if (opts.postHandler) return opts.postHandler(url, body);
      return jsonResponse({});
    }
    if (url.includes("/inventory-items?") || url.endsWith("/inventory-items")) return jsonResponse([ITEM]);
    if (url.endsWith("/uoms")) return jsonResponse([UOM]);
    if (url.includes("/issuable-sources")) return jsonResponse([SOURCE]);
    if (url.includes("/outstanding-issued-material")) return jsonResponse(opts.outstanding ?? []);
    if (url.includes("/locations/tree")) return jsonResponse(opts.locationsTree ?? []);
    if (url.includes("/inventory-reservations")) return jsonResponse(reservations);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventoryIssuePage", () => {
  it("Issue now: defaults the single usable source and submits a direct issue", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch({
      postHandler: (url, body) => {
        if (url.includes("/inventory-issues")) {
          capturedBody = body;
          return jsonResponse({
            id: "iss-1", tenant_id: "t", farm_id: "farm-1", code: "ISS-0001", purpose: body.purpose,
            issued_by_user_id: "u1", effective_time: "2026-09-01T00:00:00Z", recorded_time: "2026-09-01T00:00:00Z",
            reservation_id: null, lines: [],
          }, 201);
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryIssuePage />));

    await waitFor(() => expect(screen.getByText("Issue now")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/fertigation prep/i), { target: { value: "Nutrient mix" } });
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "item-1" } });

    await waitFor(() => expect(screen.getByText(/LOT-1 @ Bin 01/)).toBeInTheDocument());

    const qtyInputs = screen.getAllByRole("spinbutton");
    fireEvent.change(qtyInputs[0], { target: { value: "5" } });

    fireEvent.click(screen.getByRole("button", { name: /issue material/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({
      purpose: "Nutrient mix", reservation_id: null,
      lines: [
        {
          inventory_item_id: "item-1", inventory_quantity_cohort_id: "cohort-1", source_location_id: "bin-1",
          quantity: "5", reservation_line_id: null,
        },
      ],
    });
    await waitFor(() => expect(screen.getByText(/issued as ISS-0001/i)).toBeInTheDocument());
  });

  it("Reservations: creates a reservation with the compact form", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch({
      postHandler: (url, body) => {
        if (url.includes("/inventory-reservations")) {
          capturedBody = body;
          return jsonResponse({ ...RESERVATION, purpose: body.purpose }, 201);
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryIssuePage />));
    await waitFor(() => expect(screen.getByText("Issue now")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Reservations" }));
    fireEvent.click(await screen.findByRole("button", { name: /new reservation/i }));

    fireEvent.change(screen.getByPlaceholderText(/seeding wo-1/i), { target: { value: "Seeding WO-2" } });
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "item-1" } });
    fireEvent.change(screen.getByPlaceholderText("Qty"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: /^reserve$/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({
      purpose: "Seeding WO-2", lines: [{ inventory_item_id: "item-1", quantity: "8" }],
    });
  });

  it("Reservations: issues against a reservation line and releases remaining quantity", async () => {
    let issueBody: Record<string, unknown> | null = null;
    let releaseBody: Record<string, unknown> | null = null;
    stubFetch({
      reservations: [RESERVATION],
      postHandler: (url, body) => {
        if (url.includes("/inventory-issues")) {
          issueBody = body;
          return jsonResponse({ id: "iss-2", code: "ISS-0002" }, 201);
        }
        if (url.includes("/releases")) {
          releaseBody = body;
          return jsonResponse(
            {
              id: "entry-1", reservation_line_id: "line-1", entry_kind: "release", quantity_base: body.quantity,
              effective_time: "2026-09-01T00:00:00Z", actor_user_id: "u1", reason: null, issue_id: null,
            },
            201,
          );
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryIssuePage />));
    await waitFor(() => expect(screen.getByText("Issue now")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Reservations" }));
    await waitFor(() => expect(screen.getByText(/RES-0001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /issue \/ release/i }));
    await waitFor(() => expect(screen.getByText(/LOT-1 @ Bin 01/)).toBeInTheDocument());

    const issueQtyInput = screen.getByPlaceholderText(/qty to issue/i);
    fireEvent.change(issueQtyInput, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /^issue$/i }));

    await waitFor(() => expect(issueBody).not.toBeNull());
    expect(issueBody).toMatchObject({
      reservation_id: "res-1",
      lines: [
        {
          inventory_item_id: "item-1", inventory_quantity_cohort_id: "cohort-1", source_location_id: "bin-1",
          quantity: "5", reservation_line_id: "line-1",
        },
      ],
    });

    const releaseQtyInput = screen.getByPlaceholderText(/qty to release/i);
    fireEvent.change(releaseQtyInput, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /^release$/i }));

    await waitFor(() => expect(releaseBody).not.toBeNull());
    expect(releaseBody).toMatchObject({ quantity: "3" });
  });

  it("Issued material: records a Consumption against an outstanding Issue line", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch({
      outstanding: [OUTSTANDING_ROW],
      postHandler: (url, body) => {
        if (url.includes("/inventory-consumptions")) {
          capturedBody = body;
          return jsonResponse({
            id: "evt-1", event_kind: "consumption", source_kind: "issued", issue_line_id: "line-9",
            inventory_quantity_cohort_id: "cohort-1", source_location_id: null, destination_location_id: null,
            quantity_base: body.quantity, reason: null, effective_time: "2026-09-01T00:00:00Z",
            recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1",
          }, 201);
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryIssuePage />));
    await waitFor(() => expect(screen.getByText("Issue now")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Issued material" }));
    await waitFor(() => expect(screen.getByText(/ISS-0009/)).toBeInTheDocument());
    expect(screen.getByText(/Outstanding: 6.000 kg/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Consume" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm consumption/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({ issue_line_id: "line-9", quantity: "4" });
  });

  it("Issued material: records a Return to a Store Bin", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch({
      outstanding: [OUTSTANDING_ROW],
      locationsTree: [
        {
          id: "bin-1", code: "BIN-01", name: "Bin 01", location_type_id: "lt-1", location_type_code: "store_bin",
          status: "active", occupiable: false, capacity: null, children: [],
        },
      ],
      postHandler: (url, body) => {
        if (url.includes("/inventory-returns")) {
          capturedBody = body;
          return jsonResponse({
            id: "evt-2", event_kind: "return", source_kind: "issued", issue_line_id: "line-9",
            inventory_quantity_cohort_id: "cohort-1", source_location_id: null, destination_location_id: "bin-1",
            quantity_base: body.quantity, reason: null, effective_time: "2026-09-01T00:00:00Z",
            recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1",
          }, 201);
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryIssuePage />));
    await waitFor(() => expect(screen.getByText("Issue now")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Issued material" }));
    await waitFor(() => expect(screen.getByText(/ISS-0009/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Return" }));
    await waitFor(() => expect(screen.getByText("Bin 01")).toBeInTheDocument());
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm return/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({ issue_line_id: "line-9", destination_location_id: "bin-1", quantity: "3" });
  });

  it("Issued material: records a Scrap with a mandatory reason", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch({
      outstanding: [OUTSTANDING_ROW],
      postHandler: (url, body) => {
        if (url.includes("/inventory-scraps")) {
          capturedBody = body;
          return jsonResponse({
            id: "evt-3", event_kind: "scrap", source_kind: "issued", issue_line_id: "line-9",
            inventory_quantity_cohort_id: "cohort-1", source_location_id: null, destination_location_id: null,
            quantity_base: body.quantity, reason: body.reason, effective_time: "2026-09-01T00:00:00Z",
            recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1",
          }, 201);
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryIssuePage />));
    await waitFor(() => expect(screen.getByText("Issue now")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "Issued material" }));
    await waitFor(() => expect(screen.getByText(/ISS-0009/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Scrap" }));
    const scrapButton = screen.getByRole("button", { name: /record scrap/i });
    expect(scrapButton).toBeDisabled();

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    fireEvent.change(screen.getByPlaceholderText(/e\.g\. spill/i), { target: { value: "spilled during transfer" } });
    fireEvent.click(screen.getByRole("button", { name: /record scrap/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({
      source_kind: "issued", issue_line_id: "line-9", quantity: "1", reason: "spilled during transfer",
    });
  });
});
