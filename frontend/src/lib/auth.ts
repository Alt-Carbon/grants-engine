import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const ALLOWED_DOMAIN = "altcarbon.com";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    async signIn({ profile }) {
      // Only allow @altcarbon.com emails
      const email = profile?.email ?? "";
      if (!email.endsWith(`@${ALLOWED_DOMAIN}`)) {
        return false;
      }
      return true;
    },
    authorized({ auth: session, request }) {
      const isLoggedIn = !!session?.user;
      const isLoginPage = request.nextUrl.pathname.startsWith("/login");
      const isAuthApi = request.nextUrl.pathname.startsWith("/api/auth");
      const isCronApi = request.nextUrl.pathname.startsWith("/api/cron");

      // Always allow auth API and cron endpoints
      if (isAuthApi || isCronApi) return true;

      // Redirect logged-in users away from login page
      if (isLoginPage) {
        if (isLoggedIn) {
          return Response.redirect(new URL("/dashboard", request.nextUrl));
        }
        return true;
      }

      // Require login for everything else
      return isLoggedIn;
    },
    async session({ session }) {
      return session;
    },
  },
});
