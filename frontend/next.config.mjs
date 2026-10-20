/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No rewrite/proxy here on purpose. The browser calls the FastAPI
  // backend directly at NEXT_PUBLIC_API_BASE and the backend's
  // CORS_ORIGINS allows this dev origin — see backend/.env.example.
  // A same-origin proxy would put the bearer token behind a second hop
  // for no gain.
};

export default nextConfig;