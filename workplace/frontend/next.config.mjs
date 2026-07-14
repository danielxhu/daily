import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

// Pin the file-tracing root to this app so Next does not infer a higher
// workspace root from stray lockfiles (e.g. ~/package-lock.json).
const root = dirname(fileURLToPath(import.meta.url));

/** @type {import("next").NextConfig} */
const nextConfig = {
  experimental: {
    outputFileTracingRoot: root,
  },
};

export default nextConfig;
