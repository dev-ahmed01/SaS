import { redirect } from "next/navigation";

// Dashboard is the default landing route; its data is served by the protected dashboard API.
export default function HomePage() {
  redirect("/dashboard");
}
