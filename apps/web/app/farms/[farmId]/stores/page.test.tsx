import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import StoresAndBinsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const tree = [
  {
    id: "gh-1", code: "GH1", name: "Greenhouse 1", location_type_id: "type-gh", location_type_code: "greenhouse",
    status: "active", occupiable: false, capacity: null, children: [],
  },
  {
    id: "store-1", code: "MAIN-STORE", name: "Main Store", location_type_id: "type-store", location_type_code: "store",
    status: "active", occupiable: false, capacity: null,
    children: [
      {
        id: "bin-1", code: "BIN-001", name: "Bin 001", location_type_id: "type-bin", location_type_code: "store_bin",
        status: "active", occupiable: true, capacity: null, children: [],
      },
    ],
  },
];

function stubFetch(onPost?: (url: string, body: unknown) => Response | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = JSON.parse(String(init?.body));
      const overridden = onPost?.(url, body);
      if (overridden) return overridden;
      return jsonResponse({ id: "new-loc", ...body }, 201);
    }
    if (url.includes("/locations/tree")) return jsonResponse(tree);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoresAndBinsPage", () => {
  it("shows only Store-rooted subtrees, never a Greenhouse", async () => {
    stubFetch();
    render(withQueryClient(<StoresAndBinsPage />));
    await waitFor(() => expect(screen.getByText("Main Store")).toBeInTheDocument());
    expect(screen.getByText("Bin 001")).toBeInTheDocument();
    expect(screen.queryByText("Greenhouse 1")).not.toBeInTheDocument();
  });

  it("shows an empty state when the Farm has no Stores yet", async () => {
    stubFetch();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([tree[0]])));
    render(withQueryClient(<StoresAndBinsPage />));
    await waitFor(() => expect(screen.getByText("No Stores yet")).toBeInTheDocument());
  });

  it("creates a new root Store with no parent, via the constrained New Store tab", async () => {
    const fetchMock = stubFetch();
    render(withQueryClient(<StoresAndBinsPage />));
    await waitFor(() => expect(screen.getByText("Main Store")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("tab", { name: "New Store" }));
    fireEvent.change(screen.getByPlaceholderText("MAIN-STORE"), { target: { value: "CHEMICAL-STORE" } });
    fireEvent.change(screen.getByPlaceholderText("Main Store"), { target: { value: "Chemical Store" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Store" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith("/locations") && (c[1] as RequestInit)?.method === "POST",
      );
      expect(postCall).toBeDefined();
      const body = JSON.parse(String((postCall?.[1] as RequestInit).body));
      expect(body).toMatchObject({ location_type_code: "store", code: "CHEMICAL-STORE", parent_location_id: null });
    });
  });

  it("never offers a Greenhouse-typed option anywhere in the Store form", async () => {
    stubFetch();
    render(withQueryClient(<StoresAndBinsPage />));
    await waitFor(() => expect(screen.getByText("Main Store")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("tab", { name: "Add Area" }));
    expect(screen.queryByText(/greenhouse/i)).not.toBeInTheDocument();
  });
});
