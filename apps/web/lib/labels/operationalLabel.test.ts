import { describe, expect, it } from "vitest";

import {
  batchMasterLabel,
  germinationPlacementLabel,
  intersaladsPlacementLabel,
  intervinesPlacementLabel,
  leafyProductionPlacementLabel,
  seedlingEntryLabel,
  sowingTrayLabel,
  vinesProductionPlacementLabel,
} from "./operationalLabel";

describe("operationalLabel builders (PILOT-SCAN-001B OperationalLabelContext)", () => {
  it("Batch Master Label identifies the Batch only -- no tray/carrier/location fact", () => {
    const label = batchMasterLabel({ batchCode: "B-2026-014" });
    expect(label.entityTypeLabel).toBe("Batch");
    expect(label.code).toBe("B-2026-014");
    expect(label.lines.join(" ")).not.toMatch(/tray|plate|cube|bag/i);
  });

  it("Germination placement label carries Batch, Tray, Stage, Chamber, Trolley, and Level", () => {
    const label = germinationPlacementLabel({
      batchCode: "B-2026-014",
      trayCode: "TR-001",
      chamberCode: "GERM-01",
      trolleyCode: "TRL-02",
      positionCode: "L03",
    });
    const text = `${label.entityTypeLabel} ${label.code} ${label.lines.join(" ")}`;
    expect(text).toContain("TR-001");
    expect(text).toContain("B-2026-014");
    expect(text).toMatch(/Germination/);
    expect(text).toContain("GERM-01");
    expect(text).toContain("TRL-02");
    expect(text).toContain("L03");
  });

  it("Seedling label keeps the same physical Seed Tray identity, never a different carrier", () => {
    const label = seedlingEntryLabel({ batchCode: "B-2026-014", trayCode: "TR-001", tableCode: "ST-04" });
    expect(label.entityTypeLabel).toBe("Seed Tray");
    expect(label.code).toBe("TR-001");
  });

  it("InterSalads placement label never mentions Seed Tray -- it identifies the destination Nursery Cultivation Plate", () => {
    const label = intersaladsPlacementLabel({ batchCode: "B-2026-014", carrierCode: "NP-010", tableCode: "IS-02" });
    expect(label.entityTypeLabel).toBe("Nursery Cultivation Plate");
    const text = `${label.entityTypeLabel} ${label.code} ${label.lines.join(" ")}`;
    expect(text).not.toMatch(/seed tray/i);
  });

  it("Leafy Production placement label never carries Nursery Plate identity forward -- only the Production Cultivation Plate", () => {
    const label = leafyProductionPlacementLabel({ batchCode: "B-2026-014", carrierCode: "PP-0147", tableCode: "LP-03" });
    expect(label.entityTypeLabel).toBe("Production Cultivation Plate");
    expect(label.code).toBe("PP-0147");
    const text = `${label.entityTypeLabel} ${label.code} ${label.lines.join(" ")}`;
    expect(text).not.toMatch(/nursery/i);
  });

  it("InterVines placement label never shows a Grow Bag -- Grow Bags do not exist at this stage", () => {
    const label = intervinesPlacementLabel({ batchCode: "B-2026-014", carrierCode: "GC-099", tableCode: "IV-01" });
    expect(label.entityTypeLabel).toBe("Grow Cube");
    const text = `${label.entityTypeLabel} ${label.code} ${label.lines.join(" ")}`;
    expect(text).not.toMatch(/grow bag/i);
  });

  it("Vines Production placement label uses only Grow Bag + Gutter + Batch + plant count -- no invented Greenhouse/Zone/Span", () => {
    const label = vinesProductionPlacementLabel({
      batchCode: "B-2026-014",
      carrierCode: "GB-501",
      gutterCode: "GUT-07",
      plantCount: 6,
    });
    expect(label.entityTypeLabel).toBe("Grow Bag");
    const text = `${label.entityTypeLabel} ${label.code} ${label.lines.join(" ")}`;
    expect(text).toContain("GUT-07");
    expect(text).toContain("6 plants");
    expect(text).not.toMatch(/zone|span|greenhouse/i);
  });

  it("every builder returns the STANDARD template (operational identity needs room for context)", () => {
    expect(batchMasterLabel({ batchCode: "B-1" }).size).toBe("standard");
    expect(sowingTrayLabel({ batchCode: "B-1", trayCode: "T-1" }).size).toBe("standard");
  });
});
