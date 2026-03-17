import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { SessionProvider } from "@/components/SessionProvider";
import { ToastProvider } from "@/components/Toast";
import { auth } from "@/lib/auth";

export const metadata: Metadata = {
  title: "Grants Engine — Alt Carbon",
  description: "AI-powered grant discovery, scoring, and drafting",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  const isLoginPage = !session;

  return (
    <html lang="en">
      <body>
        <SessionProvider>
          <ToastProvider>
            {isLoginPage ? (
              children
            ) : (
              <div className="flex h-screen overflow-hidden">
                <Sidebar />
                <main className="flex flex-1 flex-col overflow-y-auto pt-14 lg:pt-0">
                  {children}
                </main>
              </div>
            )}
          </ToastProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
