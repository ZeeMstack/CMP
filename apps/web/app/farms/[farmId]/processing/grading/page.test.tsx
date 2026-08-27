import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import GradingPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP_LETTUCE = { id: "crop-1", code: "LET", common_name: "Lettuce" };
const CROP_TOMATO = { id: "crop-2", code: "TOM", common_name: "Tomato" };

const HPL_WEIGHT_ONLY = {
  id: "hpl-1", tenant_id: "t", farm_id: "farm-1", code: "HL-0001", harvest_event_id: "he-1",
  batch_id: "batch-1", batch_code: "B-1", workflow: { id: "wf-1", code: "leafy", name: "Leafy" },
  workflow_version_id: "wfv-1", crop: CROP_LETTUCE, variety: null,
  total_harvested_weight_kg: "100.000", total_whole_unit_count: null,
  effective_time: "2026-01-10T08:00:00Z", recorded_at: "2026-01-10T08:05:00Z", source_lines: [],
};

const HPL_COUNT_MODE = {
  id: "hpl-2", tenant_id: "t", farm_id: "farm-1", code: "HL-0002", harvest_event_id: "he-2",
  batch_id: "batch-2", batch_code: "B-2", workflow: { id: "wf-1", code: "leafy", name: "Leafy" },
  workflow_version_id: "wfv-1", crop: CROP_TOMATO, variety: null,
  total_harvested_weight_kg: "50.000", total_whole_unit_count: 200,
  effective_time: "2026-01-10T08:00:00Z", recorded_at: "2026-01-10T08:05:00Z", source_lines: [],
};

function balanceFor(lot: {
  id: string; code: string; total_harvested_weight_kg: string; total_whole_unit_count: number | null;
  effective_time: string;
}) {
  return {
    produce_lot_id: lot.id, produce_lot_code: lot.code,
    received_weight_kg: lot.total_harvested_weight_kg, available_weight_kg: lot.total_harvested_weight_kg,
    received_whole_unit_count: lot.total_whole_unit_count, available_whole_unit_count: lot.total_whole_unit_count,
    entry_count: 1, last_effective_time: lot.effective_time,
  };
}

const LOCATIONS_TREE = [
  { id: "loc-1", code: "PH1", name: "Processing Hall 1", children: [], capacity: null, status: "active", occupiable: true },
];

// Grade Definition "Grade A/B" (crop-1/Lettuce) with a RETIRED version whose
// historical window (Jan-Jul 2025) is fully before the currently ACTIVE
// version's own window (Jul 2025 onward), plus a DRAFT version that must
// never be selectable at any effective_time.
const GRADE_DEFINITIONS_LETTUCE = [
  { id: "gd-1", tenant_id: "t", crop_id: "crop-1", variety_id: null, code: "GD1", name: "Grade A/B", description: null, created_at: "2025-01-01T00:00:00Z" },
];
const GRADE_VERSIONS_GD1 = [
  {
    id: "gdv-1", tenant_id: "t", grade_definition_id: "gd-1", version_number: 1, status: "retired",
    effective_from: "2025-01-01T00:00:00Z", effective_until: "2025-07-01T00:00:00Z",
    spec_notes: "old spec", created_by: null, created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: "gdv-2", tenant_id: "t", grade_definition_id: "gd-1", version_number: 2, status: "active",
    effective_from: "2025-07-01T00:00:00Z", effective_until: null,
    spec_notes: "current spec", created_by: null, created_at: "2025-07-01T00:00:00Z",
  },
  {
    id: "gdv-3", tenant_id: "t", grade_definition_id: "gd-1", version_number: 3, status: "draft",
    effective_from: null, effective_until: null,
    spec_notes: "upcoming spec", created_by: null, created_at: "2026-01-01T00:00:00Z",
  },
];

const GRADE_DEFINITIONS_TOMATO = [
  { id: "gd-2", tenant_id: "t", crop_id: "crop-2", variety_id: null, code: "GD2", name: "Grade Tomato", description: null, created_at: "2020-01-01T00:00:00Z" },
];
const GRADE_VERSIONS_GD2 = [
  {
    id: "gdv-t1", tenant_id: "t", grade_definition_id: "gd-2", version_number: 1, status: "active",
    effective_from: "2020-01-01T00:00:00Z", effective_until: null,
    spec_notes: null, created_by: null, created_at: "2020-01-01T00:00:00Z",
  },
];

function gradingEventResult(overrides: Record<string, unknown> = {}) {
  return {
    id: "ge-1", tenant_id: "t", farm_id: "farm-1", source_harvested_produce_lot_id: "hpl-1",
    source_produce_lot_code: "HL-0001", processing_hall_location_id: "loc-1",
    effective_time: "2026-08-20T10:00:00Z", recorded_time: "2026-08-20T10:00:00Z", actor_user_id: "user-1",
    client_command_id: "cmd-1", note: null,
    input_presented_weight_kg: "100.000", input_presented_whole_unit_count: null,
    rejected_weight_kg: "0", rejected_whole_unit_count: null,
    loss_weight_kg: "0", loss_whole_unit_count: null,
    sample_weight_kg: "0", sample_whole_unit_count: null,
    remainder_weight_kg: "0", remainder_whole_unit_count: null,
    processed_weight_kg: "100.000", processed_whole_unit_count: null,
    outputs: [{
      id: "gpl-1", tenant_id: "t", farm_id: "farm-1", grading_event_id: "ge-1", code: "GA-001",
      crop: CROP_LETTUCE, variety: null, grade_definition_version_id: "gdv-2",
      original_received_weight_kg: "100.000", original_received_whole_unit_count: null,
      effective_time: "2026-08-20T10:00:00Z", recorded_at: "2026-08-20T10:00:00Z",
    }],
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/grading-events") && method === "POST") {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.recordResult ?? gradingEventResult());
      }
      if (url.includes("/grading-events")) {
        return jsonResponse(overrides.events ?? []);
      }
      if (url.includes("/harvested-produce-lots/") && url.includes("/balance")) {
        const lotId = url.match(/harvested-produce-lots\/([^/?]+)/)?.[1];
        const lot = lotId === "hpl-2" ? HPL_COUNT_MODE : HPL_WEIGHT_ONLY;
        return jsonResponse(balanceFor(lot));
      }
      if (url.includes("/harvested-produce-lots")) {
        return jsonResponse(overrides.lots ?? [HPL_WEIGHT_ONLY]);
      }
      if (url.includes("/locations/tree")) {
        return jsonResponse(LOCATIONS_TREE);
      }
      if (url.includes("/grade-definitions/gd-1/versions")) {
        return jsonResponse(GRADE_VERSIONS_GD1);
      }
      if (url.includes("/grade-definitions/gd-2/versions")) {
        return jsonResponse(GRADE_VERSIONS_GD2);
      }
      if (url.includes("/grade-definitions") && url.includes("crop_id=crop-1")) {
        return jsonResponse(GRADE_DEFINITIONS_LETTUCE);
      }
      if (url.includes("/grade-definitions") && url.includes("crop_id=crop-2")) {
        return jsonResponse(GRADE_DEFINITIONS_TOMATO);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectLot(codeText: string) {
  await waitFor(() => expect(screen.getByText(codeText)).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /grade this lot/i }));
  await waitFor(() => expect(screen.getByLabelText(/processing location/i)).toBeInTheDocument());
}

function fillLocation() {
  fireEvent.change(screen.getByLabelText(/processing location/i), { target: { value: "loc-1" } });
}

/** Waits for the Grade Definition option to actually exist before selecting
 * it -- `useGradeDefinitions` fetches asynchronously, so firing `change`
 * before the option exists has the browser silently ignore the requested
 * value (it isn't one of the `<select>`'s current options yet), leaving the
 * field un-selected despite the event having "succeeded". */
async function selectGrade(gradeDefinitionId: string) {
  await waitFor(() => expect(within(screen.getByLabelText(/^grade$/i)).getByRole("option", { name: /^Grade/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^grade$/i), { target: { value: gradeDefinitionId } });
}

async function pickGradeAndVersion(versionOptionNamePattern: RegExp) {
  await selectGrade("gd-1");
  await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: versionOptionNamePattern })).toBeInTheDocument());
  const version = within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: versionOptionNamePattern });
  fireEvent.change(screen.getByLabelText(/^version$/i), { target: { value: (version as HTMLOptionElement).value } });
}

describe("GradingPage reconciliation", () => {
  it("1. a balanced Grading reconciliation allows progression to Review and submission", async () => {
    stubFetch();
    render(withQueryClient(<GradingPage />));
    await selectLot("HL-0001");
    fillLocation();
    await pickGradeAndVersion(/^v2/);

    fireEvent.change(screen.getByLabelText(/gpl code/i), { target: { value: "GA-001" } });
    fireEvent.change(screen.getByLabelText(/output weight/i), { target: { value: "100" } });

    await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText("Grading recorded")).toBeInTheDocument());
  });

  it("2. an unbalanced Grading reconciliation blocks progression to Review", async () => {
    stubFetch();
    render(withQueryClient(<GradingPage />));
    await selectLot("HL-0001");
    fillLocation();
    await pickGradeAndVersion(/^v2/);

    fireEvent.change(screen.getByLabelText(/gpl code/i), { target: { value: "GA-001" } });
    // Only 50 of the 100 kg presented is accounted for -- 50 kg is left
    // unexplained (no rejection/loss/sample/remainder to cover it).
    fireEvent.change(screen.getByLabelText(/output weight/i), { target: { value: "50" } });

    await waitFor(() => expect(screen.getByText("Out of balance")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() =>
      expect(screen.getByText(/must equal input presented \(100\.000 kg\)/)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review before recording")).not.toBeInTheDocument();
  });

  it("3. count-mode reconciliation is enforced independently of weight reconciliation", async () => {
    stubFetch({ lots: [HPL_COUNT_MODE] });
    render(withQueryClient(<GradingPage />));
    await selectLot("HL-0002");
    fillLocation();

    await selectGrade("gd-2");
    await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v1/ })).toBeInTheDocument());
    const version = within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v1/ }) as HTMLOptionElement;
    fireEvent.change(screen.getByLabelText(/^version$/i), { target: { value: version.value } });

    // Weight is fully balanced (50 = 50), but the count side is not
    // (accounted 150 != input presented 200) -- this must block on its own.
    fireEvent.change(screen.getByLabelText(/gpl code/i), { target: { value: "GT-001" } });
    fireEvent.change(screen.getByLabelText(/output weight/i), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText(/output count/i), { target: { value: "150" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() =>
      expect(screen.getByText(/must equal input presented count \(200\)/)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Review before recording")).not.toBeInTheDocument();
  });
});

describe("GradingPage effective-time Version selection", () => {
  it("4. a historically-valid RETIRED GradeDefinitionVersion is selectable for a backdated effective_time (and DRAFT is never selectable)", async () => {
    stubFetch();
    render(withQueryClient(<GradingPage />));
    await selectLot("HL-0001");
    fillLocation();
    await selectGrade("gd-1");
    await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v2/ })).toBeInTheDocument());
    // At "today" (inside v2's open-ended active window), v2 is offered and
    // the DRAFT v3 never is.
    expect(within(screen.getByLabelText(/^version$/i)).queryByRole("option", { name: /^v3/ })).not.toBeInTheDocument();

    // Backdate into v1's own historical window (Jan-Jul 2025), well before
    // v2 was ever activated (Jul 2025).
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2025-03-15" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "12:00" } });

    await waitFor(() =>
      expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v1 — old spec/ })).toBeInTheDocument(),
    );
    expect(within(screen.getByLabelText(/^version$/i)).queryByRole("option", { name: /^v2/ })).not.toBeInTheDocument();
    expect(within(screen.getByLabelText(/^version$/i)).queryByRole("option", { name: /^v3/ })).not.toBeInTheDocument();
  });

  it("5. an out-of-window ACTIVE/RETIRED Version and a DRAFT Version are both unavailable", async () => {
    stubFetch();
    render(withQueryClient(<GradingPage />));
    await selectLot("HL-0001");
    fillLocation();
    await selectGrade("gd-1");
    await waitFor(() => expect(within(screen.getByLabelText(/^version$/i)).getByRole("option", { name: /^v2/ })).toBeInTheDocument());

    // Before v1 even existed (v1's own effective_from is 2025-01-01) -- no
    // Version's window covers this date, and the DRAFT v3 never qualifies
    // regardless of date.
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2024-01-01" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "12:00" } });

    await waitFor(() =>
      expect(screen.getByText(/No version of this grade is valid at the selected effective time/)).toBeInTheDocument(),
    );
    const versionSelect = screen.getByLabelText(/^version$/i);
    expect(within(versionSelect).queryAllByRole("option").filter((o) => (o as HTMLOptionElement).value !== "")).toHaveLength(0);
  });

  it("changing effective_time out of an already-selected Version's window clears the selection instead of leaving it silently selected", async () => {
    stubFetch();
    render(withQueryClient(<GradingPage />));
    await selectLot("HL-0001");
    fillLocation();
    await pickGradeAndVersion(/^v2/);
    expect((screen.getByLabelText(/^version$/i) as HTMLSelectElement).value).toBe("gdv-2");

    // v2's window starts 2025-07-01 -- backdating before that must clear it.
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2024-01-01" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "12:00" } });

    await waitFor(() => expect((screen.getByLabelText(/^version$/i) as HTMLSelectElement).value).toBe(""));
  });
});
