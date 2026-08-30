import { z } from "zod";

import type { CropCreate } from "@/lib/api/client";

/** PILOT-SETUP-001B6: mirrors `app.schemas.crop.CROP_CATEGORIES` exactly --
 * these are the only four values the backend accepts for `crop_category`,
 * never free text. Iceberg lettuce is `leafy_green` configuration data, not
 * a hard-coded product rule -- this list has no crop-specific entries. */
export const CROP_CATEGORY_OPTIONS = [
  { value: "leafy_green", label: "Leafy green" },
  { value: "vine", label: "Vine" },
  { value: "herb", label: "Herb" },
  { value: "other", label: "Other" },
] as const;

export const cropFormSchema = z.object({
  code: z.string().min(1, "Code is required"),
  common_name: z.string().min(1, "Common name is required"),
  scientific_name: z.string().nullable(),
  crop_category: z.enum(["leafy_green", "vine", "herb", "other"], {
    message: "Select a crop category",
  }),
});
export type CropFormValues = z.infer<typeof cropFormSchema>;

export const DEFAULT_CROP_FORM_VALUES: CropFormValues = {
  code: "",
  common_name: "",
  scientific_name: null,
  crop_category: "leafy_green",
};

export function buildCropCreatePayload(values: CropFormValues): CropCreate {
  return {
    code: values.code.trim(),
    common_name: values.common_name.trim(),
    scientific_name: values.scientific_name?.trim() || null,
    crop_category: values.crop_category,
  };
}
