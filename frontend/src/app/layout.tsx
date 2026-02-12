import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { ThemeToggleButton } from "@/components/refcheck/theme-toggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "RefCheck AI",
  description: "Scientific reference verification for biomedical manuscripts",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
          <header className="border-b border-border px-6 py-3 flex items-center justify-between">
            <h1 className="text-xl font-semibold tracking-tight">RefCheck AI</h1>
            <ThemeToggleButton />
          </header>
          <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
        </ThemeProvider>
      </body>
    </html>
  );
}
