import "./globals.css";

import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";

import { AuthProvider } from "@/components/auth/AuthContext";
import { AuthSessionBootstrap } from "@/components/auth/AuthSessionBootstrap";
import { CookieConsentBanner } from "@/components/legal/CookieConsentBanner";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/components/theme/ThemeProvider";
import { ToastContainer } from "@/components/ui/ToastContainer";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--font-geist-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MP.AI",
  description: "Production AI agent platform for messengers, CRM and live operator inbox",
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" className="h-full" suppressHydrationWarning>
      <body
        className={`${inter.variable} min-h-full bg-canvas font-sans text-canvas-fg antialiased`}
      >
        <a href="#main-content" className="skip-link">
          Перейти к содержимому
        </a>
        <Script
          src="https://widget.tiptop-pay.kz/bundles/cloudpayments.js"
          strategy="lazyOnload"
        />
        <ThemeProvider>
          <AuthProvider>
            <AuthSessionBootstrap />
            <AppShell>{children}</AppShell>
            <ToastContainer />
            <CookieConsentBanner />
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
