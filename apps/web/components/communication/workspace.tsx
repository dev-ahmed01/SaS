"use client";

import Link from "next/link";
import { useState } from "react";
import { AppShell } from "../app-shell";
import { CommunicationCompose } from "./compose";
import { CommunicationTemplates } from "./templates";
import { CommunicationCampaigns } from "./campaigns";
import { CommunicationAutomations } from "./automations";

type View="compose"|"campaigns"|"templates";
const tabs=[
  {name:"Compose",href:"/communication",view:"compose"},
  {name:"Campaigns",href:"/communication/campaigns",view:"campaigns"},
  {name:"Templates & Automations",href:"/communication/templates",view:"templates"},
] as const;

export function CommunicationWorkspace({view}:{view:View}){
  const [revision,setRevision]=useState(0);
  return <AppShell>
    <div className="communication-workspace">
      <div className="comm-main-navigation">
        <nav className="comm-tabs" aria-label="Communication views">
          {tabs.map(tab=><Link key={tab.view} href={tab.href}
            className={"comm-tab"+(view===tab.view?" active":"")}
            aria-current={view===tab.view?"page":undefined}>{tab.name}</Link>)}
        </nav>

      </div>
      {view==="compose"?<CommunicationCompose onSaved={()=>setRevision(x=>x+1)}/>:
        view==="campaigns"?<CommunicationCampaigns revision={revision}/>:
        <div className="comm-stacked-sections">
          <CommunicationTemplates onChanged={()=>setRevision(x=>x+1)}/>
          <CommunicationAutomations revision={revision}/>
        </div>}
    </div>
  </AppShell>;
}
