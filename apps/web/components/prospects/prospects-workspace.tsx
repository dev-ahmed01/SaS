"use client";

import { useRouter } from "next/navigation";
import { AppShell } from "../app-shell";
import { ModuleTabs } from "../ui/primitives";
import { ProspectEditor } from "./prospect-editor";
import { ProspectList } from "./prospect-list";
import { PipelineManager } from "./pipeline-manager";

const tabs=[
  {id:"all",label:"All Prospects",href:"/prospects"},
  {id:"add",label:"Add Prospects",href:"/prospects/add"},
  {id:"active",label:"Active",href:"/prospects/active"},
  {id:"inactive",label:"Inactive",href:"/prospects/inactive"},
  {id:"stages",label:"Stages",href:"/prospects/stages"},
] as const;

export function ProspectsWorkspace({view}:{view:"add"|"all"|"active"|"inactive"|"stages"}){
  const router=useRouter();
  return <AppShell>
    <div className="prospect-tabs stages-enabled"><ModuleTabs current={view} tabs={tabs}/></div>
    <div className="prospects-workspace">
      {view==="add"
        ?<ProspectEditor onSaved={saved=>router.push("/prospects/"+saved.id)}/>
        :view==="stages"?<PipelineManager/> :<ProspectList view={view}/>}
    </div>
  </AppShell>;
}
