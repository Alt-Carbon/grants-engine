import { auth, signIn } from "@/lib/auth";
import { redirect } from "next/navigation";
import Image from "next/image";
import {
  ShieldCheck,
  ArrowRight,
} from "lucide-react";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const session = await auth();
  if (session) redirect("/dashboard");

  const params = await searchParams;
  const error = params.error;

  return (
    <div className="relative flex min-h-screen bg-gray-950">
      {/* ── Left: Image panel ───────────────────────────────────────── */}
      <div className="relative hidden w-[52%] lg:block">
        {/* Full-bleed image */}
        <Image
          src="/login-hero.webp"
          alt="Darjeeling tea terraces"
          fill
          priority
          className="object-cover"
        />

        {/* Subtle dark gradient overlay at edges for readability */}
        <div className="absolute inset-0 bg-gradient-to-r from-gray-950/40 via-transparent to-gray-950/80" />
        <div className="absolute inset-0 bg-gradient-to-t from-gray-950/70 via-transparent to-gray-950/50" />

        {/* Top-left: Logo on the image */}
        <div className="absolute left-8 top-8 z-10 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 backdrop-blur-md ring-1 ring-white/20">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/AltLogoWhite-mnemonic.png" alt="Alt Carbon" className="h-5 w-5 object-contain" />
          </div>
          <span className="text-base font-bold text-white/90 drop-shadow-lg">
            Alt Carbon
          </span>
        </div>

      </div>

      {/* ── Right: Login panel ──────────────────────────────────────── */}
      <div className="relative flex flex-1 flex-col items-center justify-center p-6 lg:p-16">
        {/* Subtle ambient glow */}
        <div className="pointer-events-none absolute -left-32 top-1/3 h-[400px] w-[400px] rounded-full bg-green-600/5 blur-[120px]" />

        <div className="w-full max-w-sm">
          {/* Mobile: Logo + hero image (below lg) */}
          <div className="mb-10 lg:hidden">
            <div className="relative mb-6 aspect-[16/9] w-full overflow-hidden rounded-2xl">
              <Image
                src="/login-hero.webp"
                alt="Darjeeling tea terraces"
                fill
                priority
                className="object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-gray-950/80 to-transparent" />
              <div className="absolute bottom-4 left-4 flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 backdrop-blur-md ring-1 ring-white/20">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/AltLogoWhite-mnemonic.png" alt="Alt Carbon" className="h-4 w-4 object-contain" />
                </div>
                <span className="text-sm font-bold text-white drop-shadow-lg">
                  Alt Carbon
                </span>
              </div>
            </div>
            <h2 className="text-2xl font-extrabold text-white">
              Grants{" "}
              <span className="bg-gradient-to-r from-green-400 to-emerald-400 bg-clip-text text-transparent">
                Engine
              </span>
            </h2>
            <p className="mt-1.5 text-sm text-gray-500">
              Sign in to your workspace
            </p>
          </div>

          {/* Desktop: Welcome text (above lg) */}
          <div className="mb-8 hidden lg:block">
            <h2 className="text-2xl font-bold text-white">Log in</h2>
            <p className="mt-1.5 text-[15px] text-gray-500">
              Access your account
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="mb-6 flex items-center gap-2.5 rounded-xl border border-red-800/40 bg-red-950/40 px-4 py-3">
              <ShieldCheck className="h-4 w-4 shrink-0 text-red-400" />
              <p className="text-sm text-red-400">
                {error === "AccessDenied"
                  ? "Only @altcarbon.com emails are allowed."
                  : "Something went wrong. Please try again."}
              </p>
            </div>
          )}

          {/* Google sign-in button */}
          <form
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: "/dashboard" });
            }}
          >
            <button
              type="submit"
              className="group flex w-full items-center justify-center gap-3 rounded-xl bg-white px-5 py-3.5 text-[15px] font-semibold text-gray-900 shadow-sm transition-all duration-200 hover:shadow-lg hover:shadow-green-500/5 active:scale-[0.98]"
            >
              <svg className="h-5 w-5 shrink-0" viewBox="0 0 24 24">
                <path
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                  fill="#4285F4"
                />
                <path
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  fill="#34A853"
                />
                <path
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  fill="#FBBC05"
                />
                <path
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  fill="#EA4335"
                />
              </svg>
              Sign in with Google
              <ArrowRight className="h-4 w-4 text-gray-400 transition-transform duration-200 group-hover:translate-x-0.5" />
            </button>
          </form>

        </div>
      </div>
    </div>
  );
}
