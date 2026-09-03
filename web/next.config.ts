import type { NextConfig } from "next";

// GitHub Pages serves from /<repo> rather than the domain root, so asset paths
// need a prefix there and must NOT have one locally. Set by the Pages workflow.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  // Static export so the built site opens without a Node server, and so it can
  // never diverge from the batch it was built from.
  output: "export",
  images: { unoptimized: true },
  basePath,
  assetPrefix: basePath || undefined,
};

export default nextConfig;
