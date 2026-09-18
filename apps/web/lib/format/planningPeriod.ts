/** PILOT-PLAN-001B: the Planning worksheet's default date window -- "next
 * 8-12 weeks" per the ticket. Defaults to today through +84 days (12 weeks),
 * the upper end of that range, since a shorter window can always be dialed
 * back by the user but a manager opening the worksheet cold benefits more
 * from seeing too much than too little. Plain calendar dates (`YYYY-MM-DD`),
 * no time-of-day -- mirrors `formatPlanDate`'s own UTC-noon-anchored
 * parsing so no browser timezone can shift a boundary by a day. */
export function defaultPlanningPeriod(today: Date = new Date()): { start: string; end: string } {
  const start = toIsoDate(today);
  const endDate = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
  endDate.setUTCDate(endDate.getUTCDate() + 84);
  return { start, end: toIsoDate(endDate) };
}

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
