import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Deep Research v5",
  description: "Deep Research — vertical slice MVP",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="topbar">
            <span className="brand">Deep Research</span>
          </header>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}