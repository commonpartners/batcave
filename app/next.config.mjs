/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: {
    // Lint is run separately in CI; don't fail the production build on lint warnings.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
