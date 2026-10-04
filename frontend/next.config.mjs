import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

// Pin the file-tracing root to this app so Next does not infer a higher
// workspace root from stray lockfiles (e.g. ~/package-lock.json).
const root = dirname(fileURLToPath(import.meta.url));

// GitHub Pages demo build (`npm run build:pages`): a static export served under
// the repository's sub-path (e.g. /daily). Unset for every other build.
const pagesBasePath = process.env.PAGES_BASE_PATH;

/** @type {import("next").NextConfig} */
const nextConfig = {
  experimental: {
    outputFileTracingRoot: root,
  },
  ...(pagesBasePath !== undefined && {
    output: "export",
    basePath: pagesBasePath,
    trailingSlash: true,
    images: { unoptimized: true },
    env: { NEXT_PUBLIC_BASE_PATH: pagesBasePath },
  }),
};

export default nextConfig;
