"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

/** NURSERY-OPS-004B.2 section 20: a minimal, narrowly-reusable
 * filterable/searchable selection control -- built for the InterSalads
 * Transplant picker (Source Tray / Plate / Table), not a general design-
 * system combobox. Filters by the caller-supplied `label` (operator-
 * readable code/name), keyboard usable (Up/Down/Enter/Escape), touch-
 * friendly (44px minimum target), clear selected state, explicit empty/
 * no-match state. No portal/floating-ui dependency -- the list renders
 * inline below the input, matching every other form control's plain-
 * Tailwind styling in this app. */

export interface FilterableSelectOption {
  value: string;
  label: string;
  description?: string;
}

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";

export function FilterableSelect({
  options,
  value,
  onChange,
  placeholder,
  emptyMessage,
  noMatchMessage,
  loading,
  disabled,
  "aria-label": ariaLabel,
}: {
  options: FilterableSelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  emptyMessage?: string;
  noMatchMessage?: string;
  /** True while the caller's own options query is still loading -- shown
   * instead of `emptyMessage`, which otherwise misleadingly reads as
   * "there are none" rather than "not loaded yet". */
  loading?: boolean;
  disabled?: boolean;
  "aria-label"?: string;
}) {
  const listboxId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(0);

  const selected = options.find((o) => o.value === value) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length === 0) return options;
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || (o.description ?? "").toLowerCase().includes(q),
    );
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  function openList() {
    if (disabled) return;
    setOpen(true);
    setHighlightedIndex(0);
  }

  function choose(option: FilterableSelectOption) {
    onChange(option.value);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (disabled) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        openList();
        return;
      }
      setHighlightedIndex((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const option = filtered[highlightedIndex];
      if (open && option) choose(option);
      else openList();
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  return (
    // BROWSER QA CORRECTION 2: `isolate` alone only scopes the open list's
    // `z-10` (below) against elements INSIDE this same wrapper -- it does
    // NOT lift the wrapper itself above a later DOM sibling (e.g. the next
    // form field/FilterableSelect rendered after this one in the same
    // form). Two `position: relative` siblings with no explicit z-index
    // both default to `z-index: auto`, which paints in DOM order -- so a
    // later field could still paint over an earlier one's open dropdown
    // even though the dropdown's own internal stacking was "correct" in
    // isolation. Real Chromium QA caught exactly this: Zone/Span painting
    // over an open Plate dropdown. `z-20` only while `open` gives the
    // wrapper itself elevated priority over its siblings for as long as
    // its menu is showing, without permanently altering paint order for
    // every other closed instance on the page.
    <div ref={containerRef} className={`relative isolate ${open ? "z-20" : ""}`}>
      <input
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        aria-autocomplete="list"
        className={inputClass}
        disabled={disabled}
        placeholder={selected ? selected.label : placeholder ?? "Search…"}
        value={open ? query : selected ? selected.label : ""}
        onFocus={openList}
        onChange={(e) => {
          setQuery(e.target.value);
          openList();
        }}
        onKeyDown={onKeyDown}
        onBlur={(e) => {
          // Tabbing/clicking to somewhere outside this control must close
          // the list -- without this, keyboard users who Tab away (rather
          // than click away, already handled by the outside-mousedown
          // listener) leave a stale open dropdown behind. `relatedTarget`
          // is null for most non-focus-shifting blurs (e.g. window losing
          // focus entirely) -- treated as "still ours" rather than closing
          // on every incidental blur.
          if (e.relatedTarget && containerRef.current && !containerRef.current.contains(e.relatedTarget as Node)) {
            setOpen(false);
            setQuery("");
          }
        }}
      />
      {open && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-md border border-border-subtle bg-surface shadow-lg"
        >
          {loading && <li className="px-3 py-3 text-sm text-ink-muted">Loading…</li>}
          {!loading && options.length === 0 && (
            <li className="px-3 py-3 text-sm text-ink-muted">{emptyMessage ?? "Nothing available"}</li>
          )}
          {!loading && options.length > 0 && filtered.length === 0 && (
            <li className="px-3 py-3 text-sm text-ink-muted">{noMatchMessage ?? "No matches"}</li>
          )}
          {!loading &&
            filtered.map((option, index) => (
            <li key={option.value} role="option" aria-selected={option.value === value} className="w-full">
              <button
                type="button"
                onClick={() => choose(option)}
                onMouseEnter={() => setHighlightedIndex(index)}
                className={`flex min-h-11 w-full flex-col items-start justify-center gap-0.5 px-3 py-1.5 text-left text-sm ${
                  index === highlightedIndex ? "bg-surface-subtle" : ""
                } ${option.value === value ? "font-semibold text-brand-700" : "text-ink"}`}
              >
                <span>{option.label}</span>
                {option.description && <span className="text-xs text-ink-muted">{option.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
