import { z } from "zod";

import type { FarmCreate } from "@/lib/api/client";

/**
 * PILOT-SETUP-001B4: mirrors the backend's own validation exactly (see
 * `app.schemas.farm.FarmCreate`) -- code/name/timezone required and
 * trimmed, country_code exactly two letters, city_region optional. No
 * length ceiling or business rule is invented here; the backend enforces
 * Farm-code uniqueness within the Tenant itself (surfaced as a 409, not
 * client-side validation).
 */
const requiredTrimmed = (label: string) => z.string().trim().min(1, `${label} is required`);

export const createFarmFormSchema = z.object({
  code: requiredTrimmed("Farm code"),
  name: requiredTrimmed("Farm name"),
  countryCode: z
    .string()
    .trim()
    .regex(/^[A-Za-z]{2}$/, "Country code must be exactly two letters (ISO-2)"),
  cityRegion: z.string().trim().optional(),
  timezone: requiredTrimmed("Timezone"),
});
export type CreateFarmFormValues = z.infer<typeof createFarmFormSchema>;

export const DEFAULT_CREATE_FARM_FORM_VALUES: CreateFarmFormValues = {
  code: "",
  name: "",
  countryCode: "",
  cityRegion: "",
  timezone: "",
};

export function buildFarmCreatePayload(values: CreateFarmFormValues): FarmCreate {
  return {
    code: values.code,
    name: values.name,
    country_code: values.countryCode,
    city_region: values.cityRegion && values.cityRegion.length > 0 ? values.cityRegion : null,
    timezone: values.timezone,
  };
}
