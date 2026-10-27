"use client";
import { useRouter } from "next/navigation";
import { AppShell } from "../app-shell";
import { ModuleTabs } from "../ui/primitives";
import { PromoterEditor } from "./promoter-editor";
import { PromoterList } from "./promoter-list";

const tabs=[
  {id:"all",label:"All Promoters",href:"/promoters"},
  {id:"add",label:"Add Promoters",href:"/promoters/add"},
  {id:"inactive",label:"Inactive",href:"/promoters/inactive"},
] as const;

export function PromotersWorkspace({view}:{view:"add"|"active"|"all"|"inactive"}){
  const router=useRouter();
  return <AppShell>
    <div className="prospect-tabs promoter-tabs"><ModuleTabs current={view} tabs={tabs}/></div>
    <div className="prospects-workspace">
      {view==="add"
        ?<PromoterEditor onSaved={saved=>router.push("/promoters/"+saved.id)}/>
        :<PromoterList view={view}/>}
    </div>
  </AppShell>;
}
