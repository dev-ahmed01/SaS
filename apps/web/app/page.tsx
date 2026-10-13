import { redirect } from "next/navigation";

// Dashboard KPIs are intentionally not mocked. First working preview: Prospects.
export default function HomePage() {
  redirect("/prospects");
}
