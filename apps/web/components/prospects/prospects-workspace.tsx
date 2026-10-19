"use client";

import { useRouter } from "next/navigation";
import { AppShell } from "../app-shell";
import { ModuleTabs } from "../ui/primitives";
import { ProspectEditor } from "./prospect-editor";
import { ProspectList } from "./prospect-list";

const tabs=[
  {id:"all",label:"All Prospects",href:"/prospects"},
  {id:"add",label:"Add Prospect",href:"/prospects/add"},
  {id:"active",label:"Active",href:"/prospects/active"},
  {id:"inactive",label:"Inactive",href:"/prospects/inactive"},
] as const;

export function ProspectsWorkspace({view}:{view:"add"|"all"|"active"|"inactive"}){
  const router=useRouter();
  return <AppShell>
    <div className="prospect-tabs"><ModuleTabs current={view} tabs={tabs}/></div>
    <div className="prospects-workspace">
      {view==="add"
        ?<ProspectEditor onSaved={saved=>router.push("/prospects/"+saved.id)}/>
        :<ProspectList view={view}/>}
    </div>
  </AppShell>;
}
