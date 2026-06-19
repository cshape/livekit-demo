import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) so the Docker image
  // can ship just the runtime + traced node_modules instead of the full repo.
  output: 'standalone',
};

export default nextConfig;
