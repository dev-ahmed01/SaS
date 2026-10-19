"use client";

import { AppShell } from "../app-shell";
import { ModuleTabs } from "../ui/primitives";
import { ProspectEditor } from "./prospect-editor";
import { ProspectList } from "./prospect-list";

const tabs=[
  {id:"add",label:"Add Prospect",href:"/prospects"},
  {id:"inactive",label:"Inactive",href:"/prospects/inactive"},
  {id:"all",label:"All Prospects",href:"/prospects/all"},
] as const;

export function ProspectsWorkspace({view}:{view:"add"|"inactive"|"all"}) {
  return <AppShell>
    <ModuleTabs current={view} tabs={tabs}/>
    <div className="prospects-workspace">
      {view==="add"
        ? <ProspectEditor onSaved={()=>window.location.assign("/prospects/all")}/>
        : <ProspectList view={view}/>}
    </div>
  </AppShell>;
}
