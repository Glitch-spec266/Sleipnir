#!/usr/bin/env node

/**
 * npm entry point for Sleipnir.
 *
 * @dataiku/uv mirrors Astral's platform-specific uv releases to npm.  Calling
 * its own bin script rather than relying on PATH keeps this launcher portable
 * across npm, pnpm, and Windows global-install layouts.
 */
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);
const uvBin = require.resolve("@dataiku/uv/bin.cjs");
const source = "git+https://github.com/Glitch-spec266/Sleipnir.git";
const result = spawnSync(
  process.execPath,
  [uvBin, "tool", "run", "--from", source, "sleipnir", ...process.argv.slice(2)],
  { stdio: "inherit" },
);

if (result.error) {
  console.error(`sleipnir: could not start uv: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
