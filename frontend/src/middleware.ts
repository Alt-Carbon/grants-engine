export { auth as middleware } from "@/lib/auth";

export const config = {
  // Run middleware on all routes except static assets
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
