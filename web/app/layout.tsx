import type { ReactNode } from "react";
import { AuthKitProvider } from "@workos-inc/authkit-nextjs/components";
import { withAuth } from "@workos-inc/authkit-nextjs";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const { accessToken, ...initialAuth } = await withAuth();

  return (
    <html lang="en">
      <body>
        <AuthKitProvider initialAuth={initialAuth}>{children}</AuthKitProvider>
      </body>
    </html>
  );
}
