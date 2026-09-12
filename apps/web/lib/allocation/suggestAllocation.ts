/** PILOT-UX-002A: shared "Suggest allocation" proposal algorithm for the
 * Production Transfer and InterSalads allocation workspaces. Pure and
 * side-effect free -- the caller (each form) applies the result to its own
 * react-hook-form state, so this never touches domain validation, capacity
 * rules, or the submitted payload shape (those are unchanged: still the
 * exact same explicit source -> destination -> quantity allocation entries
 * the backend already requires).
 *
 * A destination is "locked" (left untouched by the suggestion) when either:
 *  - its capacity is unknown (`capacity === null`) -- never assume unknown
 *    capacity is safe to fill, per the ticket's explicit rule; or
 *  - it already carries at least one allocation -- an operator override (or
 *    a prior suggestion the operator already reviewed) is never silently
 *    overwritten by a later "Suggest allocation" click, so overrides
 *    persist until the operator clears that row themselves.
 *
 * Locked destinations' existing allocations are still subtracted from each
 * source's budget before filling the remaining (unlocked) destinations, so
 * the suggestion never proposes allocating more of a source than is
 * actually left after honoring what's already committed elsewhere in the
 * draft. Fill order is deterministic: destinations in the given array
 * order, sources within each destination in the given array order --
 * matching the order the operator added them in, never an arbitrary or
 * randomized order. */

export interface SuggestAllocationSourceInput {
  sourceId: string;
  /** Ceiling available FROM this source, independent of any allocation
   * already recorded against it (current authoritative available count
   * minus this source's own recorded losses). */
  available: number;
}

export interface SuggestAllocationExistingEntry {
  sourceId: string;
  quantity: number;
}

export interface SuggestAllocationDestinationInput {
  destinationId: string;
  /** Known biological/position capacity, or null when not yet resolvable
   * (e.g. no Plate selected yet) -- null destinations are always locked. */
  capacity: number | null;
  existingAllocations: SuggestAllocationExistingEntry[];
}

export interface SuggestedAllocationEntry {
  sourceId: string;
  quantity: number;
}

export interface SuggestAllocationResult {
  /** Every destination id from the input is present here -- for a locked
   * destination this is simply its existing allocations, unchanged, so a
   * caller can always apply the full result without special-casing which
   * destinations were actually touched. */
  byDestinationId: Record<string, SuggestedAllocationEntry[]>;
  /** Destination ids the suggestion actually filled or refilled (i.e. not
   * locked) -- use this to know which rows to write back into form state. */
  filledDestinationIds: string[];
}

export function suggestAllocations(
  sources: SuggestAllocationSourceInput[],
  destinations: SuggestAllocationDestinationInput[],
): SuggestAllocationResult {
  const budget = new Map<string, number>(sources.map((s) => [s.sourceId, s.available]));

  const lockedIds = new Set<string>();
  for (const destination of destinations) {
    const isLocked = destination.capacity == null || destination.existingAllocations.length > 0;
    if (!isLocked) continue;
    lockedIds.add(destination.destinationId);
    for (const entry of destination.existingAllocations) {
      budget.set(entry.sourceId, (budget.get(entry.sourceId) ?? 0) - entry.quantity);
    }
  }

  const byDestinationId: Record<string, SuggestedAllocationEntry[]> = {};
  const filledDestinationIds: string[] = [];

  for (const destination of destinations) {
    if (lockedIds.has(destination.destinationId)) {
      byDestinationId[destination.destinationId] = destination.existingAllocations.map((entry) => ({ ...entry }));
      continue;
    }
    let remainingCapacity = destination.capacity as number;
    const rows: SuggestedAllocationEntry[] = [];
    for (const source of sources) {
      if (remainingCapacity <= 0) break;
      const availableFromSource = budget.get(source.sourceId) ?? 0;
      if (availableFromSource <= 0) continue;
      const take = Math.min(availableFromSource, remainingCapacity);
      if (take <= 0) continue;
      rows.push({ sourceId: source.sourceId, quantity: take });
      budget.set(source.sourceId, availableFromSource - take);
      remainingCapacity -= take;
    }
    byDestinationId[destination.destinationId] = rows;
    filledDestinationIds.push(destination.destinationId);
  }

  return { byDestinationId, filledDestinationIds };
}
