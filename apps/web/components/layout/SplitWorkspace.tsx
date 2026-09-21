import type { ReactNode } from "react";

/** UX-OPS-001A shared primitive: the standard 8/4 desktop operational
 * split -- a main work area plus a sticky summary/action rail -- collapsing
 * to a single stacked column (main, then rail) on tablet/mobile. DOM order
 * always puts `main` before `rail`, which already matches the required
 * mobile task order (context above this, then allocation, then summary)
 * without any reordering CSS. The rail only becomes sticky at the desktop
 * breakpoint; on narrower screens it is a normal in-flow block so it never
 * traps a second independent scroll region on a phone. */
export function SplitWorkspace({ main, rail }: { main: ReactNode; rail: ReactNode }) {
  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-12">
      <div className="lg:col-span-8">{main}</div>
      <div className="lg:sticky lg:top-4 lg:col-span-4">{rail}</div>
    </div>
  );
}
