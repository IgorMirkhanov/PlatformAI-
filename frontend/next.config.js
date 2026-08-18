/** @type {import('next').NextConfig} */
const backendUrl = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Do not advertise the framework via X-Powered-By.
  poweredByHeader: false,
  async redirects() {
    return [
      {
        source: "/bots",
        destination: "/dashboard",
        permanent: false,
      },
      {
        source: "/bots/:id/flow",
        destination: "/flow-builder?botId=:id",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${backendUrl}/api/v1/ws/:path*`,
      },
      {
        source: "/uploads/:path*",
        destination: `${backendUrl}/uploads/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
