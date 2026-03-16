/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  serverExternalPackages: ["mongodb"],
  experimental: {
    serverExternalPackages: ["mongodb"],
  },
};

export default nextConfig;
