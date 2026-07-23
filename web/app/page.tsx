import { signOut, withAuth } from "@workos-inc/authkit-nextjs";

export default async function HomePage() {
  const { user, organizationId } = await withAuth();

  if (!user) {
    return (
      <main>
        <a href="/sign-in">Sign in</a>
      </main>
    );
  }

  return (
    <main>
      <p>
        Signed in as {user.email}
        {organizationId ? ` (org ${organizationId})` : ""}
      </p>
      <form
        action={async () => {
          "use server";
          await signOut();
        }}
      >
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
