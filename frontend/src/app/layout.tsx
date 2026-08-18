import "./globals.css";

import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { AuthProvider } from "@/components/auth/AuthContext";
import { AuthSessionBootstrap } from "@/components/auth/AuthSessionBootstrap";
import { AppShell } from "@/components/layout/AppShell";
import { ToastContainer } from "@/components/ui/ToastContainer";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--font-geist-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MP.AI",
  description: "Production AI agent platform for messengers, CRM and live operator inbox",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" className="dark h-full bg-black">
      <body
        className={`${inter.variable} min-h-full bg-black font-sans text-zinc-100 antialiased`}
      >
        <AuthProvider>
          <AuthSessionBootstrap />
          <AppShell>{children}</AppShell>
          <ToastContainer />
        </AuthProvider>
      </body>
    </html>
  );
}
