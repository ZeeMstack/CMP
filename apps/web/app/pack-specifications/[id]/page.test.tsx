import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "ps-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import PackSpecificationDetailPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const SPEC = {
  id: "ps-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "ICE-5KG", name: "Iceberg 5kg",
  customer_reference: null, created_at: "2026-08-29T00:00:00Z",
};
const CROP = { id: "crop-1", tenant_id: "t", code: "ICE", common_name: "Iceberg Lettuce", scientific_name: null, crop_category: "leafy_green", status: "active" };
const ACTIVE_UNIT = { id: "pu-1", tenant_id: "t", code: "CARTON-5KG", name: "5kg Carton", status: "active", created_at: "2026-08-29T00:00:00Z" };
const RETIRED_UNIT = { id: "pu-2", tenant_id: "t", code: "OLD-BAG", name: "Old Bag", status: "retired", created_at: "2026-08-29T00:00:00Z" };
const GRADE_DEFINITION = { id: "gd-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "CLASS-1", name: "Class 1", description: null, created_at: "2026-08-29T00:00:00Z" };
const GRADE_VERSION = {
  id: "gdv-1", tenant_id: "t", grade_definition_id: "gd-1", version_number: 1, status: "active",
  effective_from: "2026-08-29T00:00:00Z", effective_until: null, spec_notes: null, created_by: null, created_at: "2026-08-29T00:00:00Z",
};

function version(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "psv-1", tenant_id: "t", pack_specification_id: "ps-1", version_number: 1, status: "draft",
    grade_definition_version_id: null as string | null, packaging_unit_id: "pu-1",
    nominal_net_weight_kg: null as string | null, whole_units_per_pack: null as number | null, spec_notes: null,
    effective_from: null as string | null, effective_until: null as string | null,
    created_by: null, created_at: "2026-08-29T00:00:00Z", ...overrides,
  };
}

function stubFetch(versions: ReturnType<typeof version>[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method;
    if (url.includes("/pack-specifications/ps-1/versions") && url.includes("/activate")) {
      const target = versions.find((v) => url.includes(v.id as string));
      if (target) {
        target.status = "active";
        target.effective_from = "2026-08-29T00:00:00Z";
      }
      return jsonResponse(target);
    }
    if (url.includes("/pack-specifications/ps-1/versions") && url.includes("/retire")) {
      const target = versions.find((v) => url.includes(v.id as string));
      if (target) {
        target.status = "retired";
        target.effective_until = "2026-08-29T01:00:00Z";
      }
      return jsonResponse(target);
    }
    if (url.includes("/pack-specifications/ps-1/versions") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      const created = version({
        id: `psv-${versions.length + 1}`, version_number: versions.length + 1,
        grade_definition_version_id: body.grade_definition_version_id, packaging_unit_id: body.packaging_unit_id,
        nominal_net_weight_kg: body.nominal_net_weight_kg != null ? String(body.nominal_net_weight_kg) : null,
        whole_units_per_pack: body.whole_units_per_pack, spec_notes: body.spec_notes,
      });
      versions.push(created);
      return jsonResponse(created, 201);
    }
    if (url.includes("/pack-specifications/ps-1/versions")) return jsonResponse(versions);
    if (url.includes("/pack-specifications")) return jsonResponse([SPEC]);
    if (url.includes("/grade-definitions/gd-1/versions")) return jsonResponse([GRADE_VERSION]);
    if (url.includes("/grade-definitions")) return jsonResponse([GRADE_DEFINITION]);
    if (url.includes("/packaging-units")) return jsonResponse([ACTIVE_UNIT, RETIRED_UNIT]);
    if (url.includes("/crops")) return jsonResponse([CROP]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PackSpecificationDetailPage", () => {
  it("shows the spec's identity and its version catalog", async () => {
    stubFetch([version({ status: "active", effective_from: "2026-08-29T00:00:00Z", nominal_net_weight_kg: "5.000" })]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("ICE-5KG")).toBeInTheDocument());
    expect(screen.getByText("Iceberg Lettuce (ICE)")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("5.000 kg")).toBeInTheDocument();
  });

  it("offers only ACTIVE Packaging Units for a new draft version, never a retired one", async () => {
    stubFetch([]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "5kg Carton (CARTON-5KG)" })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: /old bag/i })).not.toBeInTheDocument();
  });

  it("offers real Grade Definition Versions (never a free-typed id) as an optional link", async () => {
    stubFetch([]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    await waitFor(() => expect(screen.getByText(/class 1 v1/i)).toBeInTheDocument());
  });

  it("creates a draft version with nominal weight only", async () => {
    const fetchMock = stubFetch([]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "5kg Carton (CARTON-5KG)" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Packaging unit"), { target: { value: "pu-1" } });
    fireEvent.change(screen.getByLabelText("Nominal net weight (kg, optional)"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /^create draft version$/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).includes("/versions") && (c[1] as RequestInit)?.method === "POST",
    );
    const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
    expect(body.nominal_net_weight_kg).toBe(5);
    expect(body.whole_units_per_pack).toBeNull();
  });

  it("creates a draft version with whole units per pack only", async () => {
    stubFetch([]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "5kg Carton (CARTON-5KG)" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Packaging unit"), { target: { value: "pu-1" } });
    fireEvent.change(screen.getByLabelText("Whole units per pack (optional)"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /^create draft version$/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());
  });

  it("rejects a draft version with neither measure present", async () => {
    stubFetch([]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "5kg Carton (CARTON-5KG)" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Packaging unit"), { target: { value: "pu-1" } });
    fireEvent.click(screen.getByRole("button", { name: /^create draft version$/i }));

    await waitFor(() =>
      expect(screen.getByText("Enter a nominal net weight, whole units per pack, or both")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Packaging unit")).toBeInTheDocument();
  });

  it("creates a draft version with both measures", async () => {
    stubFetch([]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("No versions yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create draft version" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "5kg Carton (CARTON-5KG)" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Packaging unit"), { target: { value: "pu-1" } });
    fireEvent.change(screen.getByLabelText("Nominal net weight (kg, optional)"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Whole units per pack (optional)"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /^create draft version$/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());
  });

  it("activation is explicit and shows the packaging unit and grade in the review", async () => {
    const fetchMock = stubFetch([version({ id: "psv-1", status: "draft", grade_definition_version_id: "gdv-1", nominal_net_weight_kg: "5.000" })]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review & activate" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Review & activate" }));
    await waitFor(() => expect(screen.getByText(/class 1 v1/i)).toBeInTheDocument());
    expect(screen.getByText("5kg Carton (CARTON-5KG)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Effective date"), { target: { value: "2026-08-29" } });
    fireEvent.change(screen.getByLabelText("Effective time"), { target: { value: "10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate version" }));

    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    const activateCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/versions/psv-1/activate"));
    expect(activateCall).toBeDefined();
  });

  it("an active version offers Retire; a retired version offers no action", async () => {
    stubFetch([version({ status: "active", effective_from: "2026-08-29T00:00:00Z" })]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Retire" }));
    fireEvent.change(screen.getByLabelText("Effective date"), { target: { value: "2026-08-29" } });
    fireEvent.change(screen.getByLabelText("Effective time"), { target: { value: "11:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Retire version" }));

    await waitFor(() => expect(screen.getByText("Retired")).toBeInTheDocument());
    const row = screen.getByText("v1").closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("never calls a packing, harvest, or finished-goods operational endpoint", async () => {
    const fetchMock = stubFetch([version({ status: "active", effective_from: "2026-08-29T00:00:00Z" })]);
    render(withQueryClient(<PackSpecificationDetailPage />));
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => /packing-events|finished-goods|dispatch|harvest|cold-storage/.test(u))).toBe(false);
  });
});
