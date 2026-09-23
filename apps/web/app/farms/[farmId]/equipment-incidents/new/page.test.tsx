import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const searchParams = new URLSearchParams();
const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useSearchParams: () => searchParams,
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import ReportEquipmentIncidentPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ASSETS = [{ id: "asset-1", code: "GT-01", name: "Trolley 1" }];

let openStatus = 201;
const postedCommandIds: string[] = [];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/equipment-incidents")) {
        const body = JSON.parse(String(init.body));
        postedCommandIds.push(body.client_command_id);
        if (openStatus !== 201) return jsonResponse({ detail: "Server error" }, openStatus);
        return jsonResponse({ id: "inc-new", code: "EI-20260101-0001" }, 201);
      }
      if (url.includes("/assets")) return jsonResponse(ASSETS);
      if (url.includes("/locations/tree")) return jsonResponse([]);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  Array.from(searchParams.keys()).forEach((key) => searchParams.delete(key));
  pushMock.mockClear();
  postedCommandIds.length = 0;
  openStatus = 201;
});

describe("ReportEquipmentIncidentPage: preserves QR asset-lock and command-id stability", () => {
  it("locks the Asset field from ?assetId= exactly as the QR deep link sets it", async () => {
    searchParams.set("assetId", "asset-1");
    stubFetch();
    render(withQueryClient(<ReportEquipmentIncidentPage />));

    await waitFor(() => expect(screen.getByText(/Trolley 1 \(GT-01\)/)).toBeInTheDocument());
    expect(screen.queryByLabelText(/^asset$/i)).not.toBeInTheDocument();
  });

  it("redirects to the new incident's detail page on success", async () => {
    stubFetch();
    render(withQueryClient(<ReportEquipmentIncidentPage />));
    await waitFor(() => expect(screen.getByLabelText(/^asset$/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^asset$/i), { target: { value: "asset-1" } });
    fireEvent.change(screen.getByLabelText(/^description$/i), { target: { value: "Compressor failure" } });
    fireEvent.click(screen.getByRole("button", { name: /report incident/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/farms/farm-1/equipment-incidents/inc-new"));
  });

  it("reuses the same client_command_id when a submit is retried after a failure", async () => {
    openStatus = 500;
    stubFetch();
    render(withQueryClient(<ReportEquipmentIncidentPage />));
    await waitFor(() => expect(screen.getByLabelText(/^asset$/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^asset$/i), { target: { value: "asset-1" } });
    fireEvent.change(screen.getByLabelText(/^description$/i), { target: { value: "Compressor failure" } });
    fireEvent.click(screen.getByRole("button", { name: /report incident/i }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: /report incident/i }));
    await waitFor(() => expect(postedCommandIds).toHaveLength(2));
    expect(postedCommandIds[0]).toBe(postedCommandIds[1]);
  });
});
