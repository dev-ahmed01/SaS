import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    const headers = [
      {key:"X-Content-Type-Options",value:"nosniff"},
      {key:"X-Frame-Options",value:"DENY"},
      {key:"Referrer-Policy",value:"strict-origin-when-cross-origin"},
      {key:"Permissions-Policy",value:"camera=(), microphone=(), geolocation=()"},
    ];
    if (process.env.APP_ENV === "production") {
      headers.push({key:"Strict-Transport-Security",value:"max-age=86400"});
    }
    return [{source:"/:path*",headers}];
  },
};

export default nextConfig;
