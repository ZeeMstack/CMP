import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  useSamplingPoints: vi.fn(),
  useWaterSources: vi.fn(),
  useReservoirs: vi.fn(),
  useIrrigationCircuits: vi.fn(),
  useWaterReturnPoints: vi.fn(),
  useWaterInstruments: vi.fn(),
  useAssets: vi.fn(),
  useRecordMeasurement: vi.fn(),
  useCalibrationStatus: vi.fn(),
}));

vi.mock("@/lib/query/hooks", () => hooks);

import { MeasurementWorksheet } from "./page";

const SAMPLING_POINT = {
  id: "sp-1", code: "SP-1", name: "Tank A Sampling Point", point_type: "reservoir",
  water_source_id: null, reservoir_id: "res-1", irrigation_circuit_id: null,
  water_delivery_point_id: null, water_return_point_id: null, status: "active", notes: null,
};

function queryStub<T>(data: T) {
  return { data, isLoading: false, isError: false, refetch: vi.fn() };
}

describe("MeasurementWorksheet (PILOT-WATER-001B multi-metric entry)", () => {
  let mutateAsync: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mutateAsync = vi.fn().mockResolvedValue({ id: "m-1" });
    hooks.useSamplingPoints.mockReturnValue(queryStub([SAMPLING_POINT]));
    hooks.useWaterSources.mockReturnValue(queryStub([]));
    hooks.useReservoirs.mockReturnValue(queryStub([{ id: "res-1", code: "RES-1", name: "Tank A", reservoir_type: "nutrient_reservoir", status: "active" }]));
    hooks.useIrrigationCircuits.mockReturnValue(queryStub([]));
    hooks.useWaterReturnPoints.mockReturnValue(queryStub([]));
    hooks.useWaterInstruments.mockReturnValue(queryStub([]));
    hooks.useAssets.mockReturnValue(queryStub([]));
    hooks.useCalibrationStatus.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    hooks.useRecordMeasurement.mockReturnValue({ mutateAsync, isPending: false });
  });

  it("submits exactly one WaterMeasurement for the single metric filled in, never fabricating the other three", async () => {
    render(<MeasurementWorksheet farmId="farm-1" />);

    fireEvent.change(screen.getByLabelText(/Sampling Point/i), { target: { value: "sp-1" } });
    fireEvent.change(screen.getByLabelText(/pH \(pH\)/i), { target: { value: "6.1" } });

    fireEvent.click(screen.getByRole("button", { name: /Record Measurements/i }));
    await screen.findByText("Measurements recorded.");

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    const [payload] = mutateAsync.mock.calls[0];
    expect(payload).toMatchObject({ metric: "PH", value: "6.1", unit: "pH" });
  });

  it("submits one independent record per filled metric row when several are entered", async () => {
    render(<MeasurementWorksheet farmId="farm-1" />);

    fireEvent.change(screen.getByLabelText(/Sampling Point/i), { target: { value: "sp-1" } });
    fireEvent.change(screen.getByLabelText(/pH \(pH\)/i), { target: { value: "6.1" } });
    fireEvent.change(screen.getByLabelText(/EC \(mS\/cm\)/i), { target: { value: "1.8" } });

    fireEvent.click(screen.getByRole("button", { name: /Record Measurements/i }));
    await screen.findByText("Measurements recorded.");

    expect(mutateAsync).toHaveBeenCalledTimes(2);
    const metrics = mutateAsync.mock.calls.map(([payload]) => payload.metric).sort();
    expect(metrics).toEqual(["EC", "PH"]);
  });

  it("refuses to submit with no metric filled in, rather than sending a blank/zero reading", () => {
    render(<MeasurementWorksheet farmId="farm-1" />);

    fireEvent.change(screen.getByLabelText(/Sampling Point/i), { target: { value: "sp-1" } });
    fireEvent.click(screen.getByRole("button", { name: /Record Measurements/i }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("Enter at least one metric value.")).toBeInTheDocument();
  });
});
