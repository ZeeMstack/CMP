import { z } from "zod";

import type { LocationBulkChildrenCreate, LocationCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B5: the generic Location domain has 24 backend
 * `location_type` codes (no `GET /location-types` endpoint exists to list
 * them), but most are either created by the dedicated Farm Setup wizard
 * (greenhouse-classification-scoped types: zone/span/grow_table/grow_gutter/
 * grow_bag_position/etc., and `greenhouse` itself) or are unreachable leaves.
 * This B5 "Add Location" UI is scoped to exactly the generic, non-greenhouse
 * types Farm Setup does not already cover -- the ones the ticket's own
 * examples name (Store, Packing Hall, Cold Store, Cold-Store Position) plus
 * Dispatch Area and Store Bin, which share the identical generic-root/
 * generic-child shape. Adding `greenhouse` here would let an operator create
 * an untemplated greenhouse outside Farm Setup's classification-driven
 * wizard -- explicitly out of scope (CLAUDE.md: never build greenhouse
 * hierarchy changes here). The backend's own hierarchy rule table (never
 * duplicated as a second source of truth here) is still the sole authority
 * on which of these may nest under which -- see the file doc comment on
 * LocationCreateForm for how an invalid combination is handled. */
export const GENERIC_LOCATION_TYPES = [
  { code: "store", label: "Store" },
  { code: "store_bin", label: "Store Bin" },
  { code: "packing_hall", label: "Packing Hall" },
  { code: "cold_store", label: "Cold Store" },
  { code: "cold_store_position", label: "Cold-Store Position" },
  { code: "dispatch_area", label: "Dispatch Area" },
] as const;

export const MAX_BULK_LOCATION_CHILDREN = 500;

const positiveInt = z.number().int("Must be a whole number").positive("Must be greater than zero");
const optionalPositiveInt = positiveInt.nullable();

export const locationFormSchema = z
  .object({
    mode: z.enum(["single", "bulk"]),
    location_type_code: z.string().min(1, "Location type is required"),
    // "" (not null) is the form's own "no parent selected" sentinel -- kept
    // as a plain string so a native <select> can bind to it directly;
    // converted to `null` only at payload-build time (see below).
    parent_location_id: z.string(),
    capacity: optionalPositiveInt,
    code: z.string(),
    name: z.string(),
    code_prefix: z.string(),
    start: positiveInt,
    end: positiveInt,
    pad_width: positiveInt,
    name_template: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.mode === "single") {
      if (!values.code.trim()) {
        ctx.addIssue({ code: "custom", path: ["code"], message: "Code is required" });
      }
      if (!values.name.trim()) {
        ctx.addIssue({ code: "custom", path: ["name"], message: "Name is required" });
      }
      return;
    }
    // Bulk mode: the bulk-children endpoint is nested under a required
    // parent_id path segment -- there is no root-level bulk create.
    if (!values.parent_location_id) {
      ctx.addIssue({
        code: "custom",
        path: ["parent_location_id"],
        message: "A parent location is required for bulk creation",
      });
    }
    if (!values.code_prefix.trim()) {
      ctx.addIssue({ code: "custom", path: ["code_prefix"], message: "Code prefix is required" });
    }
    if (values.end < values.start) {
      ctx.addIssue({ code: "custom", path: ["end"], message: "End must be greater than or equal to start" });
    } else if (values.end - values.start + 1 > MAX_BULK_LOCATION_CHILDREN) {
      ctx.addIssue({
        code: "custom",
        path: ["end"],
        message: `Cannot generate more than ${MAX_BULK_LOCATION_CHILDREN} locations at once`,
      });
    }
  });

export type LocationFormValues = z.infer<typeof locationFormSchema>;

export const DEFAULT_LOCATION_FORM_VALUES: LocationFormValues = {
  mode: "single",
  location_type_code: "",
  parent_location_id: "",
  capacity: null,
  code: "",
  name: "",
  code_prefix: "",
  start: 1,
  end: 1,
  pad_width: 2,
  name_template: "",
};

/** Pure, deterministic preview of the codes the backend's own range/
 * generator bulk-children endpoint will produce -- never sent as an
 * explicit list, only rendered so the operator can check it before
 * submitting the same prefix/start/end/pad_width the request itself uses. */
export function generateLocationCodePreview(prefix: string, start: number, end: number, padWidth: number): string[] {
  if (!prefix.trim() || !Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  const codes: string[] = [];
  for (let n = start; n <= end; n++) {
    codes.push(`${prefix.trim().toUpperCase()}${String(n).padStart(padWidth, "0")}`);
  }
  return codes;
}

export function buildLocationCreatePayload(values: LocationFormValues): LocationCreate {
  return {
    location_type_code: values.location_type_code,
    code: values.code.trim(),
    name: values.name.trim(),
    parent_location_id: values.parent_location_id || null,
    capacity: values.capacity,
  };
}

export function buildLocationBulkChildrenPayload(values: LocationFormValues): LocationBulkChildrenCreate {
  return {
    location_type_code: values.location_type_code,
    code_prefix: values.code_prefix.trim(),
    start: values.start,
    end: values.end,
    pad_width: values.pad_width,
    name_template: values.name_template.trim() ? values.name_template.trim() : null,
    capacity: values.capacity,
  };
}
