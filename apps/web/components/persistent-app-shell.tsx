"use client";

import { usePathname } from "next/navigation";
import { AppShell } from "./app-shell";

const approvedModules=new Set([
  "dashboard","prospects","promoters","collections",
  "payouts","communication","settings",
]);

export function PersistentAppShell({children}:{children:React.ReactNode}){
  const pathname=usePathname();
  const module=pathname.split("/")[1];
  if(!approvedModules.has(module))return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
