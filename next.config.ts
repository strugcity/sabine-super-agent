import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  /* config options here */

  // Exclude the dashboard directory from the root build
  // Dashboard has its own separate deployment
  webpack: (config) => {
    config.watchOptions = {
      ...config.watchOptions,
      ignored: ['**/dashboard/**', '**/node_modules/**'],
    };
    return config;
  },

  // Exclude dashboard from TypeScript compilation
  typescript: {
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
