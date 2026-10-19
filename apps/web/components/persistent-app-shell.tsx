"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { invalidateSnapshots } from "../lib/module-snapshots";
import { AppShell } from "./app-shell";

const approvedModules=new Set([
  "dashboard","prospects","promoters","collections",
  "payouts","communication","settings",
]);

export function PersistentAppShell({children}:{children:React.ReactNode}){
  const pathname=usePathname();
  const module=pathname.split("/")[1];
  useEffect(()=>{
    if(!approvedModules.has(module))invalidateSnapshots("");
  },[module]);
  if(!approvedModules.has(module))return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
