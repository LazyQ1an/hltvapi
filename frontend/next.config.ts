import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  rewrites: async () => [
    {
      source: "/api/:path*",
      destination: "http://localhost:8000/:path*",
    },
  ],
};

export default nextConfig;
