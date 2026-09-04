import type { NextConfig } from "next";

// GitHub Pages serves from /<repo> rather than the domain root, so asset paths
// need a prefix there and must NOT have one locally. Set by the Pages workflow.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  // Static export so the built site opens without a Node server, and so it can
  // never diverge from the batch it was built from.
  output: "export",
  // Emit out/records/index.html rather than out/records.html. A bare .html
  // file only resolves at /records if the host happens to try that extension;
  // a directory with an index.html resolves everywhere, which matters because
  // the nav links point at /records and a judge may open the built site from
  // any static server.
  trailingSlash: true,
  images: { unoptimized: true },
  basePath,
  assetPrefix: basePath || undefined,
};

export default nextConfig;
