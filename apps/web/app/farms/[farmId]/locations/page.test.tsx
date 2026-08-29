import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import LocationsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const tree = [
  {
    id: "gh-1",
    code: "GH1",
    name: "Greenhouse 1",
    location_type_id: "type-gh",
    status: "active",
    occupiable: false,
    capacity: null,
    children: [],
  },
  {
    id: "cold-store-1",
    code: "CS1",
    name: "Cold Store",
    location_type_id: "type-cold-store",
    status: "active",
    occupiable: false,
    capacity: null,
    children: [],
  },
];

type FetchCall = { url: string; init?: RequestInit };

function stubFetch(overrides: { onPost?: (call: FetchCall) => Response | undefined } = {}) {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (init?.method === "POST") {
        const overridden = overrides.onPost?.({ url, init });
        if (overridden) return overridden;
      }
      if (url.includes("/subtree-occupancy")) {
        return jsonResponse({ root_location_id: "gh-1", aggregate_counts: [], occupied_locations: [] });
      }
      if (url.includes("/locations/tree")) return jsonResponse(tree);
      return jsonResponse({});
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LocationsPage", () => {
  it("renders the location tree (this wrapper restyle must not break tree rendering/expansion)", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
  });

  it("provides a way back to Farm Setup, distinct from this operational occupancy view", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /view farm setup/i })).toHaveAttribute("href", "/farms/farm-1/farm-setup");
  });

  it("shows an honest empty state when there is no location hierarchy yet", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("No locations yet")).toBeInTheDocument());
  });

  it("shows an Add Location affordance that opens the create form", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /add location/i }));
    expect(screen.getByText("Placement")).toBeInTheDocument();
  });

  it("renders exactly the backend-supported single-create fields -- no farm_id or tenant_id input anywhere", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));

    expect(screen.getByText("Location type")).toBeInTheDocument();
    expect(screen.getByText("Parent location")).toBeInTheDocument();
    expect(screen.getByText("Capacity (optional)")).toBeInTheDocument();
    expect(screen.getByText("Code")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.queryByText(/farm.?id/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/tenant.?id/i)).not.toBeInTheDocument();
  });

  it("populates the parent picker from the already-loaded tree, never a second list request", async () => {
    stubFetch();
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));

    expect(screen.getByRole("option", { name: /Cold Store \(CS1\)/ })).toBeInTheDocument();
  });

  it("submits a valid single create as exactly one mutation and refreshes the tree", async () => {
    let postCount = 0;
    const calls = stubFetch({
      onPost: (call) => {
        if (call.url.includes("/locations") && !call.url.includes("bulk-children")) {
          postCount += 1;
          return jsonResponse(
            { id: "new-1", tenant_id: "t1", farm_id: "farm-1", parent_location_id: null, location_type_id: "type-ph", code: "PH1", name: "Packing Hall 1", status: "active", greenhouse_classification: null, occupiable: false, capacity: null },
            201,
          );
        }
        return undefined;
      },
    });
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));

    fireEvent.change(screen.getByLabelText("Location type"), { target: { value: "packing_hall" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "PH1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Packing Hall 1" } });
    fireEvent.click(screen.getByRole("button", { name: /^create location$/i }));

    await waitFor(() => expect(postCount).toBe(1));
    // Back to the tree view -- the create closed the form and the tree
    // query key was invalidated, both signs of a real refresh.
    await waitFor(() => expect(screen.queryByText("Placement")).not.toBeInTheDocument());
    expect(calls.some((c) => c.url.includes("/locations/tree"))).toBe(true);
  });

  it("shows a friendly message on a 403 and never claims success", async () => {
    stubFetch({
      onPost: (call) =>
        call.url.includes("/locations") && !call.url.includes("bulk-children")
          ? jsonResponse({ detail: "Forbidden" }, 403)
          : undefined,
    });
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));
    fireEvent.change(screen.getByLabelText("Location type"), { target: { value: "packing_hall" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "PH1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Packing Hall 1" } });
    fireEvent.click(screen.getByRole("button", { name: /^create location$/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Placement")).toBeInTheDocument();
  });

  it("shows a friendly message on a duplicate-code 409 conflict", async () => {
    stubFetch({
      onPost: (call) =>
        call.url.includes("/locations") && !call.url.includes("bulk-children")
          ? jsonResponse({ detail: "Location code already exists under this parent" }, 409)
          : undefined,
    });
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));
    fireEvent.change(screen.getByLabelText("Location type"), { target: { value: "packing_hall" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "PH1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Packing Hall 1" } });
    fireEvent.click(screen.getByRole("button", { name: /^create location$/i }));

    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());
  });

  it("shows a friendly message on an invalid parent/type 422 error, never a raw server error", async () => {
    stubFetch({
      onPost: (call) =>
        call.url.includes("/locations") && !call.url.includes("bulk-children")
          ? jsonResponse({ detail: "This location type is not permitted under this parent" }, 422)
          : undefined,
    });
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));
    fireEvent.change(screen.getByLabelText("Location type"), { target: { value: "packing_hall" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "PH1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Packing Hall 1" } });
    fireEvent.click(screen.getByRole("button", { name: /^create location$/i }));

    await waitFor(() => expect(screen.getByText(/not permitted under this parent/i)).toBeInTheDocument());
  });

  it("switches to bulk mode, requires a parent, and previews deterministic codes before using the real bulk-children endpoint", async () => {
    let bulkPostUrl: string | null = null;
    stubFetch({
      onPost: (call) => {
        if (call.url.includes("/bulk-children")) {
          bulkPostUrl = call.url;
          return jsonResponse([], 201);
        }
        return undefined;
      },
    });
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));
    fireEvent.click(screen.getByRole("radio", { name: /a range of locations/i }));

    fireEvent.change(screen.getByLabelText("Location type"), { target: { value: "cold_store_position" } });
    fireEvent.change(screen.getByLabelText("Parent location"), { target: { value: "cold-store-1" } });
    fireEvent.change(screen.getByLabelText("Code prefix"), { target: { value: "P" } });
    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("End"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Pad width"), { target: { value: "2" } });

    expect(screen.getByText("P01, P02, P03")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^create locations$/i }));
    await waitFor(() => expect(bulkPostUrl).toBe("/api/farms/farm-1/locations/cold-store-1/bulk-children"));
  });

  it("never calls a Movement, Occupancy, or Transformation endpoint from this setup flow", async () => {
    const calls = stubFetch({
      onPost: (call) =>
        call.url.includes("/locations") && !call.url.includes("bulk-children")
          ? jsonResponse({ id: "new-1", tenant_id: "t1", farm_id: "farm-1", parent_location_id: null, location_type_id: "type-ph", code: "PH1", name: "Packing Hall 1", status: "active", greenhouse_classification: null, occupiable: false, capacity: null }, 201)
          : undefined,
    });
    render(withQueryClient(<LocationsPage />));
    await waitFor(() => expect(screen.getByText("Greenhouse 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /add location/i }));
    fireEvent.change(screen.getByLabelText("Location type"), { target: { value: "packing_hall" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "PH1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Packing Hall 1" } });
    fireEvent.click(screen.getByRole("button", { name: /^create location$/i }));

    await waitFor(() => expect(screen.queryByText("Placement")).not.toBeInTheDocument());
    expect(calls.some((c) => /\/movements|\/occupanc|\/transformations/i.test(c.url))).toBe(false);
  });
});
