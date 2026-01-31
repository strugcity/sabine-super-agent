import type { NextConfig } from 'next';
import path from 'path';

const nextConfig: NextConfig = {
  /* config options here */

  // Fix workspace root detection - ensures build outputs go to the correct location
  // This prevents Next.js from using a lockfile in a parent directory as the root
  outputFileTracingRoot: path.join(__dirname),

  // Explicitly ignore the Python app/ directory at root
  // Next.js App Router pages are in src/app/
  webpack: (config, { isServer }) => {
    config.watchOptions = {
      ...config.watchOptions,
      ignored: ['**/dashboard/**', '**/node_modules/**', '**/venv/**'],
    };

    // Exclude Python files from webpack processing
    config.module.rules.push({
      test: /\.py$/,
      use: 'ignore-loader',
    });

    return config;
  },

  // Exclude dashboard from TypeScript compilation
  typescript: {
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
