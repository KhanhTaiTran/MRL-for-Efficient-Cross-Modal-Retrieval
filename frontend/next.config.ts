export default {
  output: "standalone",
  allowedDevOrigins: ["local-origin.dev", "*.local-origin.dev"],
  experimental: {
    ppr: "incremental" as const,
    inlineCss: true,
    useCache: true,
  },
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: [
      {
        protocol: "https",
        hostname: "cdn.shopify.com",
        pathname: "/s/files/**",
      },
      {
        protocol: "https",
        hostname: "images.unsplash.com",
        pathname: "/**",
      },
    ],
  },
};
