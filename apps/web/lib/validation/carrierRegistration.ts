import { z } from "zod";

import type { CarrierBulkCreate, CarrierCreate, CarrierSpecificationRead } from "@/lib/api/client";

/** PILOT-SETUP-001B5: registration always resolves the CarrierType through
 * an existing, active CarrierSpecification -- never a bare
 * `carrier_type_code` -- so `carrier_type_code` is never sent from this
 * form. This is a deliberate scope narrowing (the backend also allows
 * type-only registration for CarrierTypes that don't require a
 * specification), matching the ticket's own requirement that "the operator
 * must choose an existing active CarrierSpecification." */
export const MAX_BULK_CARRIERS = 500;

/** FINAL INTEGRITY CLEANUP: the backend keeps `cultivation_plate` purely
 * for historical/backward compatibility -- existing Carriers and
 * Specifications referencing it are never touched -- but the frozen CMP
 * rule is that NEW physical Carrier registration must never create another
 * one against it. The only valid cultivation-plate concepts for new
 * registration are the distinct `nursery_cultivation_plate` and
 * `production_cultivation_plate` types. This is enforced here, once, and
 * applied at both the data-selection layer (the Carriers page) and again
 * inside `CarrierRegistrationForm` itself (see its own doc comment) so a
 * legacy specification can never become selectable no matter which layer
 * a future caller forgets to filter. */
export const LEGACY_GENERIC_CARRIER_TYPE_CODE = "cultivation_plate";

export function isSelectableForCarrierRegistration(
  spec: Pick<CarrierSpecificationRead, "status" | "carrier_type_code">,
): boolean {
  return spec.status === "active" && spec.carrier_type_code !== LEGACY_GENERIC_CARRIER_TYPE_CODE;
}

const positiveInt = z.number().int("Must be a whole number").positive("Must be greater than zero");

export const carrierRegistrationFormSchema = z
  .object({
    mode: z.enum(["single", "bulk"]),
    specification_id: z.string().min(1, "A carrier specification is required"),
    code: z.string(),
    issued_date: z.string(),
    code_prefix: z.string(),
    start: positiveInt,
    end: positiveInt,
    pad_width: positiveInt,
  })
  .superRefine((values, ctx) => {
    if (values.mode === "single") {
      if (!values.code.trim()) {
        ctx.addIssue({ code: "custom", path: ["code"], message: "Code is required" });
      }
      return;
    }
    if (!values.code_prefix.trim()) {
      ctx.addIssue({ code: "custom", path: ["code_prefix"], message: "Code prefix is required" });
    }
    if (values.end < values.start) {
      ctx.addIssue({ code: "custom", path: ["end"], message: "End must be greater than or equal to start" });
    } else if (values.end - values.start + 1 > MAX_BULK_CARRIERS) {
      ctx.addIssue({
        code: "custom",
        path: ["end"],
        message: `Cannot generate more than ${MAX_BULK_CARRIERS} carriers at once`,
      });
    }
  });

export type CarrierRegistrationFormValues = z.infer<typeof carrierRegistrationFormSchema>;

export const DEFAULT_CARRIER_REGISTRATION_FORM_VALUES: CarrierRegistrationFormValues = {
  mode: "single",
  specification_id: "",
  code: "",
  issued_date: "",
  code_prefix: "",
  start: 1,
  end: 1,
  pad_width: 3,
};

/** Pure, deterministic preview of the codes the backend's own range/
 * generator bulk endpoint will produce -- see `carrier_service.py`'s own
 * `f"{code_prefix}{str(n).zfill(pad_width)}"` generator, mirrored here only
 * for a truthful preview, never sent as an explicit list. */
export function generateCarrierCodePreview(prefix: string, start: number, end: number, padWidth: number): string[] {
  if (!prefix.trim() || !Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  const codes: string[] = [];
  for (let n = start; n <= end; n++) {
    codes.push(`${prefix.trim().toUpperCase()}${String(n).padStart(padWidth, "0")}`);
  }
  return codes;
}

export function buildCarrierCreatePayload(values: CarrierRegistrationFormValues): CarrierCreate {
  return {
    specification_id: values.specification_id,
    code: values.code.trim(),
    issued_date: values.issued_date.trim() ? values.issued_date.trim() : null,
  };
}

export function buildCarrierBulkCreatePayload(values: CarrierRegistrationFormValues): CarrierBulkCreate {
  return {
    specification_id: values.specification_id,
    code_prefix: values.code_prefix.trim(),
    start: values.start,
    end: values.end,
    pad_width: values.pad_width,
  };
}
