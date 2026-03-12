/** @type {import('next').NextConfig} */

const isHybrid = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "hybrid";

const nextConfig = {
  output: "standalone",
  serverExternalPackages: ["mongodb"],
  ...(isHybrid && {
    async redirects() {
      return [
        { source: "/dashboard", destination: "/monitoring", permanent: false },
        { source: "/pipeline", destination: "/monitoring", permanent: false },
        { source: "/triage", destination: "/monitoring", permanent: false },
      ];
    },
  }),
};

export default nextConfig;
