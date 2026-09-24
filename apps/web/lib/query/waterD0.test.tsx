import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  endDeliveryEvent,
  getBatchWaterExposureTimeline,
  getCircuitWaterExposureTimeline,
  getDeliveryEvent,
  getReservoirWaterExposureTimeline,
} from "@/lib/api/client";
import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { useEndDeliveryEvent } from "@/lib/query/hooks";
import { queryKeys } from "@/lib/query/keys";
import { DEFAULT_TEST_BOOTSTRAP, TEST_TENANT_ID } from "@/lib/test-utils";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("UX-OPS-001D: D0 client paths", () => {
  it("calls the exact deployed D0 routes", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return json({});
    }));
    await getDeliveryEvent("f1", "d1");
    await endDeliveryEvent("f1", "d1", { effective_end: "2026-09-24T07:00:00.000Z", note: null, client_command_id: "c1" });
    await getBatchWaterExposureTimeline("b1", "f1", "2026-09-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z");
    await getCircuitWaterExposureTimeline("ic1", "f1", "2026-09-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z");
    await getReservoirWaterExposureTimeline("r1", "f1", "2026-09-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z");
    const window = "farm_id=f1&window_start=2026-09-01T00%3A00%3A00.000Z&window_end=2026-09-02T00%3A00%3A00.000Z";
    expect(calls.map((c) => c.url)).toEqual([
      "/api/farms/f1/water-delivery-events/d1",
      "/api/farms/f1/water-delivery-events/d1/end",
      `/api/crop-batches/b1/water-exposure-timeline?${window}`,
      `/api/irrigation-circuits/ic1/water-exposure-timeline?${window}`,
      `/api/reservoirs/r1/water-exposure-timeline?${window}`,
    ]);
    expect(calls[1].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({
      effective_end: "2026-09-24T07:00:00.000Z", note: null, client_command_id: "c1",
    });
  });
});

describe("UX-OPS-001D: End Delivery cache effects", () => {
  it("writes the 201 response into the detail read and invalidates farm/circuit lists and every timeline on the farm", async () => {
    const resolved = {
      id: "d1", tenant_id: "t", farm_id: "f1", reservoir_id: "r1", irrigation_circuit_id: "ic1",
      effective_start: "2026-09-24T05:00:00Z", effective_end: "2026-09-24T07:00:00Z", delivered_volume: null,
      delivered_volume_uom_id: null, nutrient_mix_id: null, notes: null, end_source: "END_EVENT",
      water_delivery_end_event_id: "e1", end_note: null,
    };
    vi.stubGlobal("fetch", vi.fn(async () => json(resolved, 201)));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(queryKeys.authBootstrap(), DEFAULT_TEST_BOOTSTRAP);
    const t = TEST_TENANT_ID;
    const watched = [
      queryKeys.deliveryEventsForFarm(t, "f1"),
      queryKeys.deliveryEventsForCircuit(t, "ic1"),
      queryKeys.waterExposureTimeline(t, "f1", "batch", "b1", "w1"),
      queryKeys.waterExposureTimeline(t, "f1", "reservoir", "r1", "w2"),
    ];
    const untouched = queryKeys.waterExposureTimeline(t, "other-farm", "batch", "b1", "w1");
    for (const key of [...watched, untouched]) client.setQueryData(key, []);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
      </QueryClientProvider>
    );
    const { result } = renderHook(() => useEndDeliveryEvent("f1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({
        deliveryId: "d1", payload: { effective_end: "2026-09-24T07:00:00Z", note: null, client_command_id: "c1" },
      });
    });
    expect(client.getQueryData(queryKeys.deliveryEvent(t, "f1", "d1"))).toEqual(resolved);
    for (const key of watched) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    expect(client.getQueryState(untouched)?.isInvalidated).toBe(false);
  });
});
