import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { backendOrigin } from "./admin-backend";

/** Every module view is server-gated. Merely possessing a cookie does not grant access. */
export async function requireAdminSession(): Promise<void> {
  const token = (await cookies()).get("sas_session")?.value;
  const backend = backendOrigin();
  if (!token || !backend) redirect("/login");
  let authenticated = false;
  try {
    const response = await fetch(backend + "/v1/auth/session", {
      method: "GET",
      headers: { Cookie: "sas_session=" + encodeURIComponent(token) },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    authenticated = response.ok;
  } catch {
    authenticated = false;
  }
  if (!authenticated) redirect("/login");
}
