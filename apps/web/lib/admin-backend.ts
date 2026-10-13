/** Private, server-only API location. Never expose the PostgreSQL DSN or API secrets. */
export function backendOrigin(): string | null {
  const supplied = process.env.API_INTERNAL_URL;
  if (!supplied) {
    return process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : null;
  }
  try {
    const url = new URL(supplied);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) return null;
    return url.origin;
  } catch {
    return null;
  }
}
