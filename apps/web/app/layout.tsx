import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Business Brain — Razorpay merchant intelligence",
  description: "Shared merchant world model, agent orchestration, and an admin console over every layer.",
};

/**
 * Stamps the saved theme before first paint so the app never flashes the wrong
 * mode. Falls back to the OS preference when nothing has been chosen.
 */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var saved = localStorage.getItem("bb_theme");
    var theme = saved || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // The bootstrap script stamps data-theme before React hydrates, so the
    // server's markup deliberately differs from the client's here.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
