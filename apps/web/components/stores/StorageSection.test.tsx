import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { StorageSection } from "./StorageSection";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function conflictResponse(message: string, code: string) {
  return jsonResponse({ detail: { message, code } }, 409);
}

function buildTree() {
  return [
    {
      id: "store-1", code: "MAIN-STORE", name: "Main Store", location_type_id: "type-store", location_type_code: "store",
      status: "active", occupiable: false, capacity: null,
      children: [
        {
          id: "rack-1", code: "RACK-1", name: "Rack 1", location_type_id: "type-rack", location_type_code: "store_rack",
          status: "active", occupiable: false, capacity: null,
          children: [
            {
              id: "bin-1", code: "BIN-1", name: "Bin 1", location_type_id: "type-bin", location_type_code: "store_bin",
              status: "active", occupiable: true, capacity: null, children: [],
            },
          ],
        },
        {
          id: "area-inactive", code: "AREA-OLD", name: "Old Area", location_type_id: "type-area", location_type_code: "store_area",
          status: "inactive", occupiable: false, capacity: null, children: [],
        },
      ],
    },
  ];
}

function stubFetch(onPost?: (url: string, body: unknown) => Response | undefined) {
  const tree = buildTree();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = JSON.parse(String(init?.body));
      const overridden = onPost?.(url, body);
      if (overridden) return overridden;
      return jsonResponse({ ...body, id: "x" }, 200);
    }
    if (url.endsWith("/locations/tree")) return jsonResponse(tree);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StorageSection maintenance", () => {
  it("shows Active/Inactive status per row", async () => {
    stubFetch();
    render(withQueryClient(<StorageSection farmId="farm-1" />));
    await waitFor(() => expect(screen.getByText("Main Store")).toBeInTheDocument());
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });

  it("renames a Location via Edit, without exposing code as editable", async () => {
    const fetchMock = stubFetch();
    render(withQueryClient(<StorageSection farmId="farm-1" />));
    await waitFor(() => expect(screen.getByText("Rack 1")).toBeInTheDocument());

    const rackRow = screen.getByText("Rack 1").closest("div") as HTMLElement;
    fireEvent.click(within(rackRow).getByRole("button", { name: "Edit" }));

    expect(screen.getByText(/locked/i)).toBeInTheDocument();
    const input = screen.getByLabelText("Rename RACK-1") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Renamed Rack" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes("rack-1/update") && (c[1] as RequestInit)?.method === "POST",
      );
      expect(postCall).toBeDefined();
      const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
      expect(body).toMatchObject({ name: "Renamed Rack" });
      expect(body).not.toHaveProperty("code");
    });
  });

  it("shows a friendly message when deactivation is blocked by active children", async () => {
    stubFetch((url) => {
      if (url.includes("rack-1/deactivate")) {
        return conflictResponse("Location has active child locations", "LOCATION_HAS_ACTIVE_CHILDREN");
      }
      return undefined;
    });
    render(withQueryClient(<StorageSection farmId="farm-1" />));
    await waitFor(() => expect(screen.getByText("Rack 1")).toBeInTheDocument());

    const rackRow = screen.getByText("Rack 1").closest("div") as HTMLElement;
    fireEvent.click(within(rackRow).getByRole("button", { name: "Deactivate" }));

    await waitFor(() =>
      expect(
        screen.getByText("Cannot deactivate this Rack because 1 active Bin remains beneath it."),
      ).toBeInTheDocument(),
    );
  });

  it("shows a friendly message when reactivation is blocked by an inactive parent", async () => {
    stubFetch((url) => {
      if (url.includes("area-inactive/reactivate")) {
        return conflictResponse("Parent location is not active", "LOCATION_PARENT_NOT_ACTIVE");
      }
      return undefined;
    });
    render(withQueryClient(<StorageSection farmId="farm-1" />));
    await waitFor(() => expect(screen.getByText("Old Area")).toBeInTheDocument());

    const areaRow = screen.getByText("Old Area").closest("div") as HTMLElement;
    fireEvent.click(within(areaRow).getByRole("button", { name: "Reactivate" }));

    await waitFor(() =>
      expect(
        screen.getByText("Cannot reactivate this Area until its parent Store is active."),
      ).toBeInTheDocument(),
    );
  });

  it("excludes inactive Locations from Add Area/Rack/Bin parent selectors", async () => {
    stubFetch();
    render(withQueryClient(<StorageSection farmId="farm-1" />));
    await waitFor(() => expect(screen.getByText("Main Store")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("tab", { name: "Add Bin(s)" }));

    const select = screen.getByLabelText("Store, Area, or Rack") as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((o) => o.textContent ?? "");
    expect(optionLabels.some((l) => l.includes("Rack 1"))).toBe(true);
    expect(optionLabels.some((l) => l.includes("Old Area"))).toBe(false);
  });
});
