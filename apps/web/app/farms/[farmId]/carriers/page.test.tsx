import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import CarriersPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const carrierTypes = [
  { id: "ct-1", code: "NURSERY_PLATE", name: "Nursery Cultivation Plate", requires_specification: true, biological_position_label: "Cells" },
];

function spec(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "spec-1",
    tenant_id: "t1",
    carrier_type_id: "ct-1",
    carrier_type_code: "NURSERY_PLATE",
    biological_position_label: "Cells",
    code: "PLATE-200",
    name: "200-hole nursery plate",
    length_mm: 500,
    width_mm: 300,
    height_mm: null,
    biological_position_count: 200,
    status: "active",
    is_structurally_locked: false,
    ...overrides,
  };
}

function carrier(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "carrier-1",
    tenant_id: "t1",
    farm_id: "farm-1",
    carrier_type_id: "ct-1",
    code: "PLATE-200-0001",
    status: "active",
    issued_date: null,
    retired_date: null,
    specification_id: "spec-1",
    specification: { id: "spec-1", code: "PLATE-200", name: "200-hole nursery plate", biological_position_count: 200 },
    ...overrides,
  };
}

type FetchCall = { url: string; init?: RequestInit };

function stubFetch(carriers: unknown[], specs: unknown[] = [spec()], onPost?: (call: FetchCall) => Response | undefined) {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (init?.method === "POST") {
        const overridden = onPost?.({ url, init });
        if (overridden) return overridden;
      }
      if (url.includes("/carrier-types")) return jsonResponse(carrierTypes);
      if (url.includes("/carrier-specifications")) return jsonResponse(specs);
      if (url.includes("/carriers")) return jsonResponse(carriers);
      return jsonResponse({});
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CarriersPage", () => {
  it("renders an honest empty state when no carriers are registered yet", async () => {
    stubFetch([]);
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
  });

  it("lists registered carriers with their type and specification", async () => {
    stubFetch([carrier()]);
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("PLATE-200-0001")).toBeInTheDocument());
    expect(screen.getByText("Nursery Cultivation Plate")).toBeInTheDocument();
    expect(screen.getByText("PLATE-200 — 200-hole nursery plate")).toBeInTheDocument();
  });

  it("links back to Carrier Specifications for managing specs, never editing them here", async () => {
    stubFetch([]);
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /manage carrier specifications/i })).toHaveAttribute(
      "href",
      "/carrier-specifications",
    );
  });

  it("excludes the legacy generic cultivation_plate specification from the register picker, while both distinct plate specifications remain selectable", async () => {
    stubFetch(
      [],
      [
        spec({ id: "spec-legacy", code: "PLATE-LEGACY", carrier_type_code: "cultivation_plate", status: "active" }),
        spec({ id: "spec-nursery", code: "PLATE-NURSERY", carrier_type_code: "nursery_cultivation_plate", status: "active" }),
        spec({ id: "spec-production", code: "PLATE-PRODUCTION", carrier_type_code: "production_cultivation_plate", status: "active" }),
      ],
    );
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));

    expect(screen.queryByRole("option", { name: /PLATE-LEGACY/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /PLATE-NURSERY/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /PLATE-PRODUCTION/ })).toBeInTheDocument();
  });

  it("opens the register form with only an active CarrierSpecification selectable", async () => {
    stubFetch([], [spec({ id: "spec-1", status: "active" }), spec({ id: "spec-2", code: "OLD-100", status: "inactive" })]);
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));

    expect(screen.getByRole("option", { name: /PLATE-200/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /OLD-100/ })).not.toBeInTheDocument();
  });

  it("shows read-only specification context and never lets the carrier type be edited directly", async () => {
    stubFetch([]);
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));
    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-1" } });

    expect(screen.getByText("NURSERY_PLATE")).toBeInTheDocument();
    expect(screen.getByText("500 × 300 × –")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /carrier type/i })).not.toBeInTheDocument();
  });

  it("never shows a Location, Crop Batch, plant-count, or production-stage field", async () => {
    stubFetch([]);
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));

    expect(screen.queryByText(/location/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/crop batch/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/plant count/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/production stage/i)).not.toBeInTheDocument();
  });

  it("submits a valid single registration as exactly one mutation and refreshes the list", async () => {
    let postCount = 0;
    const calls = stubFetch([], [spec()], (call) => {
      if (call.url.endsWith("/farms/farm-1/carriers")) {
        postCount += 1;
        return jsonResponse(carrier({ code: "PLATE-200-0099" }), 201);
      }
      return undefined;
    });
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));
    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-1" } });
    fireEvent.change(screen.getByLabelText("Carrier code"), { target: { value: "PLATE-200-0099" } });
    fireEvent.click(screen.getByRole("button", { name: /^register carrier$/i }));

    await waitFor(() => expect(postCount).toBe(1));
    await waitFor(() => expect(screen.queryByText("Carrier specification")).not.toBeInTheDocument());
    expect(calls.some((c) => c.url.endsWith("/farms/farm-1/carriers"))).toBe(true);
  });

  it("shows a friendly message on a duplicate carrier-code 409 conflict", async () => {
    stubFetch([], [spec()], (call) =>
      call.url.endsWith("/farms/farm-1/carriers")
        ? jsonResponse({ detail: "Carrier code already exists in this tenant" }, 409)
        : undefined,
    );
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));
    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-1" } });
    fireEvent.change(screen.getByLabelText("Carrier code"), { target: { value: "PLATE-200-0099" } });
    fireEvent.click(screen.getByRole("button", { name: /^register carrier$/i }));

    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());
  });

  it("shows a friendly message on a 403 and never claims success", async () => {
    stubFetch([], [spec()], (call) =>
      call.url.endsWith("/farms/farm-1/carriers") ? jsonResponse({ detail: "Forbidden" }, 403) : undefined,
    );
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));
    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-1" } });
    fireEvent.change(screen.getByLabelText("Carrier code"), { target: { value: "PLATE-200-0099" } });
    fireEvent.click(screen.getByRole("button", { name: /^register carrier$/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Carrier specification")).toBeInTheDocument();
  });

  it("switches to bulk mode, previews deterministic codes, and uses the real bulk endpoint", async () => {
    let bulkUrl: string | null = null;
    stubFetch([], [spec()], (call) => {
      if (call.url.endsWith("/farms/farm-1/carriers/bulk")) {
        bulkUrl = call.url;
        return jsonResponse([], 201);
      }
      return undefined;
    });
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));
    fireEvent.click(screen.getByRole("radio", { name: /a range of carriers/i }));

    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-1" } });
    fireEvent.change(screen.getByLabelText("Code prefix"), { target: { value: "PLATE-" } });
    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("End"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Pad width"), { target: { value: "4" } });

    expect(screen.getByText("PLATE-0001, PLATE-0002, PLATE-0003")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^register carriers$/i }));
    await waitFor(() => expect(bulkUrl).toBe("/api/farms/farm-1/carriers/bulk"));
  });

  it("never calls a Location, Occupancy, Movement, or Transformation endpoint from this registration flow", async () => {
    const calls = stubFetch([], [spec()], (call) =>
      call.url.endsWith("/farms/farm-1/carriers") ? jsonResponse(carrier(), 201) : undefined,
    );
    render(withQueryClient(<CarriersPage />));
    await waitFor(() => expect(screen.getByText("No physical carriers registered yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /register carriers/i }));
    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-1" } });
    fireEvent.change(screen.getByLabelText("Carrier code"), { target: { value: "PLATE-200-0099" } });
    fireEvent.click(screen.getByRole("button", { name: /^register carrier$/i }));

    await waitFor(() => expect(screen.queryByText("Carrier specification")).not.toBeInTheDocument());
    expect(calls.some((c) => /\/locations|\/occupanc|\/movements|\/transformations/i.test(c.url))).toBe(false);
  });
});
