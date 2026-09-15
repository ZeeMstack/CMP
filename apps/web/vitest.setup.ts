import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrollIntoView at all (unlike window.open, which
// it stubs as a no-op with a console warning) -- any component that calls
// it (e.g. LocationTree's scanned-Location auto-scroll, PILOT-SCAN-001E)
// would otherwise throw `TypeError: ...scrollIntoView is not a function`
// in every test that renders it, whether or not that test cares about
// scrolling.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

afterEach(() => {
  cleanup();
});
