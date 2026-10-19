"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { CommunicationCompose } from "./compose";
import { CommunicationTemplates } from "./templates";
import { CommunicationCampaigns } from "./campaigns";
import { CommunicationAutomations } from "./automations";

type View="compose"|"campaigns"|"templates"|"automations";
const tabs=[
  {name:"Compose",href:"/communication",view:"compose"},
  {name:"Campaigns",href:"/communication/campaigns",view:"campaigns"},
  {name:"Templates",href:"/communication/templates",view:"templates"},
  {name:"Automations",href:"/communication/automations",view:"automations"},
] as const;

export function CommunicationWorkspace({view}:{view:View}){
  const [revision,setRevision]=useState(0);
  const [operational,setOperational]=useState(false);
  const [statusChecked,setStatusChecked]=useState(false);
  useEffect(()=>{
    let active=true;
    fetch("/api/admin/messaging/status",{cache:"no-store"})
      .then(async r=>{if(!r.ok)throw Error("unavailable");return await r.json();})
      .then((data:{operationally_enabled:boolean})=>{
        if(active){setOperational(data.operationally_enabled);setStatusChecked(true);}
      }).catch(()=>{if(active)setStatusChecked(false);});
    return ()=>{active=false;};
  },[]);
  return <AppShell>
    <div className="communication-workspace">
      <div className="comm-main-navigation">
        <nav className="comm-tabs" aria-label="Communication views">
          {tabs.map(tab=><Link key={tab.view} href={tab.href}
            className={"comm-tab"+(view===tab.view?" active":"")}
            aria-current={view===tab.view?"page":undefined}>{tab.name}</Link>)}
        </nav>
        <div className="comm-delivery-indicator" aria-label="Delivery readiness">
          <span className={"comm-ready-dot"+(operational?" on":"")} aria-hidden="true"/>
          {operational?"Existing WhatsApp sender active":
            statusChecked?"New campaigns require channel activation":"Delivery not verified"}
        </div>
      </div>
      {view==="compose"?<CommunicationCompose onSaved={()=>setRevision(x=>x+1)}/>:
        view==="campaigns"?<CommunicationCampaigns revision={revision}/>:
        view==="templates"?<CommunicationTemplates/>:
        <CommunicationAutomations/>}
    </div>
  </AppShell>;
}
