import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "NukeLab Platform",
  description: "Multi-user scientific computing platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
