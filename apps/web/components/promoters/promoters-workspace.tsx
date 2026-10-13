"use client";
import { AppShell } from "../app-shell";
import { ModuleTabs,PageHeading } from "../ui/primitives";
import { PromoterEditor } from "./promoter-editor";
import { PromoterList } from "./promoter-list";

const tabs=[
  {id:"add",label:"Add Promoter",href:"/promoters"},
  {id:"active",label:"Active",href:"/promoters/active"},
  {id:"all",label:"All Promoters",href:"/promoters/all"},
] as const;

export function PromotersWorkspace({view}:{view:"add"|"active"|"all"}){
  return <AppShell>
    <PageHeading title="Promoters"/>
    <ModuleTabs current={view} tabs={tabs}/>
    <div className="prospects-workspace">
      {view==="add"
        ? <PromoterEditor onSaved={()=>window.location.assign("/promoters/all")}/>
        : <PromoterList view={view}/>}
    </div>
  </AppShell>;
}
