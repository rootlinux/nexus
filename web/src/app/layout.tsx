import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import "./globals.css";
import { AuthProvider } from "../contexts/AuthContext";
import { PwaBoot } from "../components/PwaBoot";

const BASE_URL = process.env.NEXT_PUBLIC_WEB_BASE_URL || 'https://linusx.xyz'

export const metadata: Metadata = {
  title: {
    default: "Nexus",
    template: "%s · Nexus",
  },
  description: "A private network for invited circles, considered conversation, and a quieter social pace.",
  applicationName: "Nexus",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon.ico", sizes: "any" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "1024x1024", type: "image/png" },
    ],
    shortcut: ["/favicon.ico"],
  },
  appleWebApp: {
    capable: true,
    title: "Nexus",
    statusBarStyle: "black-translucent",
  },
  formatDetection: {
    telephone: false,
  },
  openGraph: {
    title: "Nexus",
    description: "A private network for invited circles, considered conversation, and a quieter social pace.",
    siteName: "Nexus",
    type: "website",
    url: BASE_URL,
images: [
          {
            url: `${BASE_URL}/brand/nexus-og.png`,
            width: 1200,
            height: 630,
            alt: "Nexus",
          },
        ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Nexus",
    description: "A private network for invited circles, considered conversation, and a quieter social pace.",
    images: [`${BASE_URL}/brand/nexus-og.png`],
  },
  other: {
    "apple-mobile-web-app-capable": "yes",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const headersList = await headers();
  const nonce = headersList.get('x-nonce') ?? undefined;

  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <head>
        {/* Next.js needs the nonce to inject its own inline scripts */}
        {nonce && <meta name="csp-nonce" content={nonce} />}
      </head>
      <body className="min-h-full flex flex-col">
        <AuthProvider>
          <PwaBoot />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
