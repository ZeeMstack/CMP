import { describe, expect, it } from "vitest";

import { exposureKindLabel } from "./page";

/** PILOT-WATER-001B frozen wording rule (mirrored from WATER-001A): exposure
 * is traceability evidence only, never a health/disease claim. The exact
 * two evidence kinds the backend emits must render with their exact
 * labels, and the forbidden vocabulary must never appear anywhere in this
 * mapping's output. */
describe("exposureKindLabel wording", () => {
  it("labels RECORDED_DELIVERY_EXPOSURE readably without inventing new wording", () => {
    expect(exposureKindLabel("RECORDED_DELIVERY_EXPOSURE")).toBe("Recorded Delivery Exposure");
  });

  it("labels CONFIGURED_TOPOLOGY_EXPOSURE readably without inventing new wording", () => {
    expect(exposureKindLabel("CONFIGURED_TOPOLOGY_EXPOSURE")).toBe("Configured Topology Exposure");
  });

  it("never produces forbidden disease/contamination wording for either evidence kind", () => {
    const forbidden = /affected|contaminat|infect|disease/i;
    expect(exposureKindLabel("RECORDED_DELIVERY_EXPOSURE")).not.toMatch(forbidden);
    expect(exposureKindLabel("CONFIGURED_TOPOLOGY_EXPOSURE")).not.toMatch(forbidden);
  });

  it("passes an unrecognized kind through rather than fabricating a label", () => {
    expect(exposureKindLabel("SOME_FUTURE_KIND")).toBe("SOME_FUTURE_KIND");
  });
});
