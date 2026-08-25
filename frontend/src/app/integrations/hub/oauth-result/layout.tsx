import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "OAuth — MP.AI",
};

export default function HubOAuthResultLayout({ children }: { children: ReactNode }) {
  return <div className="min-h-screen bg-black text-zinc-100">{children}</div>;
}
