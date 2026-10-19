/** Server-only upstream configuration. Fail closed for hosted stages. */
export function backendOrigin(): string | null {
  const hosted = process.env.APP_ENV === "staging" || process.env.APP_ENV === "production";
  const supplied = process.env.API_INTERNAL_URL;
  if (!supplied) {
    return !hosted && process.env.NODE_ENV === "development"
      ? "http://127.0.0.1:8000" : null;
  }
  try {
    const url = new URL(supplied);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username || url.password || url.search || url.hash ||
      url.pathname !== "/"
    ) return null;
    if (hosted) {
      const publicOrigin = new URL(process.env.APP_PUBLIC_ORIGIN ?? "");
      if (
        publicOrigin.protocol !== "https:" ||
        publicOrigin.username || publicOrigin.password || publicOrigin.search ||
        publicOrigin.hash || publicOrigin.pathname !== "/" ||
        url.protocol !== "https:"
      ) return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}
