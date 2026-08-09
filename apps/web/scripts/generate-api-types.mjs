// Regenerates lib/api/schema.gen.ts from the backend's live OpenAPI schema.
//
// This is a manual, explicit step (`npm run api:types`) -- it is never run
// as part of `npm run build`/`dev`, so the normal frontend build never
// requires the backend process to be running. It DOES require a Python
// environment that can import the FastAPI app (apps/api/.venv), since it
// calls `app.openapi()` in-process rather than hitting a live HTTP server.
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const apiDir = resolve(here, "../../api");
const outFile = resolve(here, "../lib/api/schema.gen.ts");

const pythonCandidates = [
  resolve(apiDir, ".venv/Scripts/python.exe"),
  resolve(apiDir, ".venv/bin/python"),
];

function dumpOpenApiJson() {
  for (const python of pythonCandidates) {
    const result = spawnSync(
      python,
      ["-c", "import json,app.main as m;print(json.dumps(m.app.openapi()))"],
      { cwd: apiDir, encoding: "utf-8" },
    );
    if (result.status === 0 && result.stdout) {
      return JSON.parse(result.stdout);
    }
  }
  throw new Error(
    "Could not generate the OpenAPI schema. Ensure apps/api's virtualenv exists " +
      "(apps/api/.venv) and `python -c \"import app.main\"` succeeds from apps/api.",
  );
}

const schema = dumpOpenApiJson();
const ast = await openapiTS(schema);
const output = astToString(ast);

mkdirSync(dirname(outFile), { recursive: true });
writeFileSync(
  outFile,
  `// GENERATED FILE -- do not edit by hand.\n// Regenerate with: npm run api:types\n\n${output}`,
);
console.log(`Wrote ${outFile}`);
