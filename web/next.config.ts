import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export so judges can open the built site without a Node server,
  // and so the site can never diverge from the batch it was built from.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
