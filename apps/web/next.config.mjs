/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Build autonome pour une image de production légère (cf. Dockerfile.prod).
  output: "standalone",
};

export default nextConfig;
