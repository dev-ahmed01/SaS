"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { PromoterEditor } from "./promoter-editor";
import { PromoterNotes } from "./promoter-notes";
import { ContactConsent } from "../communication/contact-consent";
import { PromoterSponsors } from "./promoter-sponsors";
import { PromoterStatusDialog } from "./promoter-status-dialog";
import type { Promoter } from "./promoter-types";
import { formatCRMDate } from "../../lib/crm-dates";

type Activity={id:string;kind:string;title:string;detail:string;occurred_at:string};
function Fact({label,children}:{label:string;children:React.ReactNode}){
  return <div className="promoter-profile-fact"><dt>{label}</dt><dd>{children}</dd></div>;
}
function Stat({label,value,icon,onClick}:{
  label:string;value:string|number;icon:"users"|"user-plus"|"check";onClick?:()=>void;
}){
  return <div className="promoter-metric">
    <span className="promoter-metric-icon"><Icon name={icon} size={22}/></span>
    <div><span>{label}</span><strong>{value}</strong>
      {onClick&&<button type="button" className="promoter-metric-link" onClick={onClick}>
        View {label.toLowerCase()} <span aria-hidden="true">→</span>
      </button>}
    </div>
  </div>;
}
export function PromoterDetails({id}:{id:string}){
  const [record,setRecord]=useState<Promoter|null>(null);
  const [activity,setActivity]=useState<Activity[]>([]);
  const [filter,setFilter]=useState("all");
  const [showOlder,setShowOlder]=useState(false);
  const [sponsorCount,setSponsorCount]=useState<number|null>(null);
  const [prospectCount,setProspectCount]=useState<number|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [consentOpen,setConsentOpen]=useState(false);
  const [confirm,setConfirm]=useState(false);
  const [revision,setRevision]=useState(0);
  const refresh=()=>setRevision(x=>x+1);
  const load=useCallback(async(signal?:AbortSignal)=>{
    const response=await fetch("/api/admin/promoters/"+id,{cache:"no-store",signal});
    if(!response.ok)throw Error("Could not load promoter details.");
    return await response.json() as Promoter;
  },[id]);
  useEffect(()=>{
    const controller=new AbortController();
    setError("");
    Promise.all([
      load(controller.signal),
      fetch("/api/admin/promoters/"+id+"/activity",{cache:"no-store",signal:controller.signal})
        .then(async r=>{if(!r.ok)throw Error("Activity timeline unavailable.");return r.json() as Promise<Activity[]>;}),
    ]).then(([person,events])=>{
      if(!controller.signal.aborted){setRecord(person);setActivity(events);}
    }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not load promoter.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[load,revision]);
  const entries=filter==="all"?activity:activity.filter(entry=>entry.kind===filter);
  const visibleEntries=showOlder?entries:entries.slice(0,12);
  const scrollTo=(elementId:string)=>document.getElementById(elementId)?.scrollIntoView({behavior:"smooth",block:"start"});
  const initials=record?.full_name.split(/\s+/).map(n=>n[0]).slice(0,2).join("").toUpperCase()??"";
  return <AppShell><div className="crm-details crm-redesign promoter-modern-detail">
    <Link href="/promoters" className="back-link"><Icon name="arrow-left" size={17}/> All promoters</Link>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {loading?<p role="status">Loading promoter…</p>:record&&<>
      <header className="promoter-identity-row">
        <span className="promoter-identity-avatar" aria-hidden="true">{initials}</span>
        <div className="promoter-identity-copy">
          <div className="crm-title-line">
            <h2>{record.full_name}</h2>
            <span className={"status-pill "+(record.is_active?"active":"inactive")}>
              {record.is_active?"Active":"Inactive"}
            </span>
          </div>
          <p>{record.mobile_number} · Joined {formatCRMDate(record.created_at)}</p>
        </div>
      </header>
      {editing&&<PromoterEditor initial={record} onCancel={()=>setEditing(false)}
        onSaved={()=>{setEditing(false);refresh();}}/>}
      <div className="promoter-metrics" aria-label="Current promoter assignments">
        <Stat label="Sponsors" icon="users" value={sponsorCount??"—"}
          onClick={()=>scrollTo("promoter-sponsors")}/>
        <Stat label="Prospects" icon="user-plus" value={prospectCount??"—"}
          onClick={()=>scrollTo("promoter-prospects")}/>
        <Stat label="Total assigned" icon="check" value={record.sponsor_count}/>
      </div>
      <div className="crm-redesign-columns promoter-information-row">
        <section className="crm-detail-card promoter-profile-card" aria-label="Personal information">
          <h2>Personal information</h2>
          <dl className="promoter-profile-facts">
            <Fact label="Phone (WhatsApp)">{record.mobile_number}</Fact>
            {record.whatsapp_number&&record.whatsapp_number!==record.mobile_number&&
              <Fact label="WhatsApp">{record.whatsapp_number}</Fact>}
            {record.email&&<Fact label="Email">{record.email}</Fact>}
            {record.area_city&&<Fact label="City">{record.area_city}</Fact>}
            {record.occupation&&<Fact label="Occupation">{record.occupation}</Fact>}
          </dl>
        </section>
        <section className="crm-detail-card promoter-timeline-card">
          <div className="crm-panel-heading"><h2>Activity timeline</h2>
            <select aria-label="Filter promoter activity" value={filter}
              onChange={e=>{setFilter(e.target.value);setShowOlder(false);}}>
              <option value="all">All activity</option>
              <option value="assignment">Assignments</option>
              <option value="updated">Updates</option>
            </select></div>
          <ol className="crm-activity-timeline">
            {visibleEntries.map(item=><li key={item.id}>
              <span className={"crm-activity-dot "+item.kind} aria-hidden="true"/>
              <div><strong>{item.title}</strong><p>{item.detail}</p>
                <small>{formatCRMDate(item.occurred_at)} · {new Date(item.occurred_at).toLocaleTimeString("en-IN",{timeZone:"Asia/Kolkata",hour:"2-digit",minute:"2-digit"})} IST</small>
              </div>
            </li>)}
          </ol>
          {entries.length===0&&<p className="crm-muted">No recorded activity of this type.</p>}
          {entries.length>12&&<button type="button" className="text-action"
            onClick={()=>setShowOlder(v=>!v)}>{showOlder?"Show recent 12":
            "Show all "+entries.length+" activities"}</button>}
        </section>
      </div>
      <div className="crm-redesign-columns crm-assignment-panels promoter-assignments-grid">
        <div id="promoter-sponsors" className="crm-detail-card crm-assignment-card">
          <PromoterSponsors promoter={record} kind="sponsors" onChanged={refresh}
            onCount={setSponsorCount}/>
        </div>
        <div id="promoter-prospects" className="crm-detail-card crm-assignment-card">
          <PromoterSponsors promoter={record} kind="prospects" onChanged={refresh}
            onCount={setProspectCount}/>
        </div>
      </div>
      <div className="promoter-final-row">
        <PromoterNotes promoter={record} onChanged={refresh}/>
        <div className="crm-redesign-actions" aria-label="Promoter actions">
          <button type="button" className="btn btn-secondary"
            aria-expanded={consentOpen} onClick={()=>setConsentOpen(open=>!open)}>
            Communication permissions
          </button>
          <button type="button" className="btn btn-secondary" onClick={()=>setEditing(v=>!v)}>
            <Icon name="pencil" size={17}/> Edit
          </button>
          <button type="button"
            className={"btn "+(record.is_active?"btn-secondary crm-danger-btn":"btn-primary")}
            onClick={()=>setConfirm(true)}>
            {record.is_active?"Mark Inactive":"Reactivate"}
          </button>
        </div>
      </div>
      {consentOpen&&<ContactConsent recipientKind="promoter" recipientId={record.id}
        legacyWhatsAppOptIn={record.whatsapp_opt_in} allowGrant={record.is_active} onChanged={refresh}/>}
    </>}
    {confirm&&record&&<PromoterStatusDialog promoter={record} onClose={()=>setConfirm(false)}
      onChanged={()=>{setConfirm(false);refresh();}}/>}
  </div></AppShell>;
}
