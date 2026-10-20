/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The frontend talks to the FastAPI backend over /api/* in the same origin
  // during dev. See `app/api/auth/[...path]/route.ts` for the proxy.
};

export default nextConfig;