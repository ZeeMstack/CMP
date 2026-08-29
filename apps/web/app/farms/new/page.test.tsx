import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import NewFarmPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type FetchMock = Mock<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>;

/** Typed via the `vi.fn` generic rather than named-but-unused implementation
 * parameters, so `mock.calls[0]` still carries `[input, init]` types for the
 * request-shape assertions below without triggering no-unused-vars -- the
 * mock always returns the same canned `response` regardless of how it's
 * called, so the implementation itself never needs to read its arguments. */
function mockFetchOnce(response: Response): FetchMock {
  const fetchMock: FetchMock = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const CREATED_FARM = {
  id: "farm-new-1",
  tenant_id: "t1",
  code: "FARM-01",
  name: "Acme Farms — Site 1",
  country_code: "PK",
  city_region: "Lahore",
  timezone: "Asia/Karachi",
  status: "active",
};

function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText("Farm code"), { target: { value: "FARM-01" } });
  fireEvent.change(screen.getByLabelText("Farm name"), { target: { value: "Acme Farms — Site 1" } });
  fireEvent.change(screen.getByLabelText("Country code (ISO-2)"), { target: { value: "PK" } });
  fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "Asia/Karachi" } });
}

afterEach(() => {
  pushMock.mockClear();
  vi.unstubAllGlobals();
});

describe("NewFarmPage", () => {
  it("renders exactly the backend-supported FarmCreate fields -- no greenhouse, crop, setup, or tenant fields", () => {
    render(withQueryClient(<NewFarmPage />));

    expect(screen.getByLabelText("Farm code")).toBeInTheDocument();
    expect(screen.getByLabelText("Farm name")).toBeInTheDocument();
    expect(screen.getByLabelText("Country code (ISO-2)")).toBeInTheDocument();
    expect(screen.getByLabelText("City / region (optional)")).toBeInTheDocument();
    expect(screen.getByLabelText("Timezone")).toBeInTheDocument();

    expect(screen.queryByLabelText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/greenhouse/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/crop/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/variety/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/owner/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/coordinat/i)).not.toBeInTheDocument();
  });

  it("requires code, name, country code, and timezone but leaves city/region optional", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(CREATED_FARM, 201));
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<NewFarmPage />));

    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(screen.getByText("Farm code is required")).toBeInTheDocument());
    expect(screen.getByText("Farm name is required")).toBeInTheDocument();
    expect(screen.getByText("Timezone is required")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("submits exactly one POST /farms with the FarmCreate contract, city_region null when left blank", async () => {
    const fetchMock = mockFetchOnce(jsonResponse(CREATED_FARM, 201));
    render(withQueryClient(<NewFarmPage />));

    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/farms");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string);
    expect(body).toEqual({
      code: "FARM-01",
      name: "Acme Farms — Site 1",
      country_code: "PK",
      city_region: null,
      timezone: "Asia/Karachi",
    });
  });

  it("includes a trimmed city_region when the operator fills it in", async () => {
    const fetchMock = mockFetchOnce(jsonResponse(CREATED_FARM, 201));
    render(withQueryClient(<NewFarmPage />));

    fillRequiredFields();
    fireEvent.change(screen.getByLabelText("City / region (optional)"), { target: { value: "Lahore" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body.city_region).toBe("Lahore");
  });

  it("navigates to the new Farm's Farm Setup route on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(CREATED_FARM, 201)));
    render(withQueryClient(<NewFarmPage />));

    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/farms/farm-new-1/farm-setup"));
  });

  it("renders a clean permission-denied message on 403, never a raw backend payload", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "Insufficient permissions" }, 403)));
    render(withQueryClient(<NewFarmPage />));

    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() =>
      expect(
        screen.getByText("You do not have permission to create farms for this tenant."),
      ).toBeInTheDocument(),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("renders the duplicate Farm code conflict on 409 and preserves entered values", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Farm code already exists in this tenant" }, 409)),
    );
    render(withQueryClient(<NewFarmPage />));

    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(screen.getByText("Farm code already exists in this tenant")).toBeInTheDocument());
    expect(screen.getByLabelText("Farm code")).toHaveValue("FARM-01");
    expect(screen.getByLabelText("Farm name")).toHaveValue("Acme Farms — Site 1");
    expect(screen.getByLabelText("Country code (ISO-2)")).toHaveValue("PK");
    expect(screen.getByLabelText("Timezone")).toHaveValue("Asia/Karachi");
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("never calls a /platform/* route or sends a client-side tenant override", async () => {
    const fetchMock = mockFetchOnce(jsonResponse(CREATED_FARM, 201));
    render(withQueryClient(<NewFarmPage />));

    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create Farm" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).not.toMatch(/\/platform\//);
    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body).not.toHaveProperty("tenant_id");
  });
});
