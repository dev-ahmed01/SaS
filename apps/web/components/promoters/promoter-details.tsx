"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { PromoterEditor } from "./promoter-editor";
import { PromoterNotes } from "./promoter-notes";
import { PromoterSponsors } from "./promoter-sponsors";
import { PromoterStatusDialog } from "./promoter-status-dialog";
import type { Promoter } from "./promoter-types";
import { formatCRMDate } from "../../lib/crm-dates";

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
  const [sponsorCount,setSponsorCount]=useState<number|null>(null);
  const [prospectCount,setProspectCount]=useState<number|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [confirm,setConfirm]=useState(false);
  const [deleteOpen,setDeleteOpen]=useState(false);
  const [deleting,setDeleting]=useState(false);
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
    load(controller.signal).then(person=>{
      if(!controller.signal.aborted)setRecord(person);
    }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not load promoter.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[load,revision]);
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
      <div className="promoter-metrics" aria-label="Current promoter assignments">
        <Stat label="Sponsors" icon="users" value={sponsorCount??"—"}
          onClick={()=>scrollTo("promoter-sponsors")}/>
        <Stat label="Prospects" icon="user-plus" value={prospectCount??"—"}
          onClick={()=>scrollTo("promoter-prospects")}/>
        <Stat label="Total assigned" icon="check" value={record.sponsor_count}/>
      </div>
      <section className="crm-detail-card promoter-profile-card" aria-label="Personal details">
        <div className="crm-panel-heading"><h2>Personal details</h2>
          <button type="button" className="btn btn-secondary" onClick={()=>setEditing(v=>!v)}
            aria-expanded={editing}>
            <Icon name="pencil" size={16}/> {editing?"Close edit":"Edit details"}
          </button>
        </div>
        {editing?<PromoterEditor initial={record} onCancel={()=>setEditing(false)}
          onSaved={()=>{setEditing(false);refresh();}}/>:
          <dl className="promoter-profile-facts">
            <Fact label="Full name">{record.full_name}</Fact>
            <Fact label="Mobile (WhatsApp)">{record.mobile_number}</Fact>
            {record.whatsapp_number&&record.whatsapp_number!==record.mobile_number&&
              <Fact label="WhatsApp">{record.whatsapp_number}</Fact>}
            <Fact label="Email">{record.email||"—"}</Fact>
            <Fact label="City">{record.area_city||"—"}</Fact>
          </dl>}
      </section>
      <div className="crm-redesign-columns crm-assignment-panels promoter-assignments-grid">
        <div id="promoter-prospects" className="crm-detail-card crm-assignment-card">
          <PromoterSponsors promoter={record} kind="prospects" onChanged={refresh}
            onCount={setProspectCount}/>
        </div>
        <div id="promoter-sponsors" className="crm-detail-card crm-assignment-card">
          <PromoterSponsors promoter={record} kind="sponsors" onChanged={refresh}
            onCount={setSponsorCount}/>
        </div>
      </div>
      <div className="promoter-final-row">
        <PromoterNotes promoter={record} onChanged={refresh}/>
        <div className="crm-redesign-actions" aria-label="Promoter actions">
          <button type="button" className="btn btn-secondary crm-danger-btn"
            onClick={()=>setDeleteOpen(true)}>
            <Icon name="trash" size={17}/> Delete promoter
          </button>
          <button type="button"
            className={"btn "+(record.is_active?"btn-secondary crm-danger-btn":"btn-primary")}
            onClick={()=>setConfirm(true)}>
            {record.is_active?"Mark Inactive":"Reactivate"}
          </button>
        </div>
      </div>
    </>}
    {deleteOpen&&record&&<div className="crm-dialog-scrim">
      <section className="crm-dialog" role="dialog" aria-modal="true"
        aria-label="Confirm permanent promoter deletion">
        <h2>Are you sure you want to delete this promoter?</h2>
        <p>This is permanent, not deactivation. Promoters with any sponsor
          assignment history cannot be deleted. Reassignment does not erase
          that historical record.</p>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" disabled={deleting}
            onClick={()=>setDeleteOpen(false)}>Cancel</button>
          <button type="button" className="btn btn-danger" disabled={deleting}
            onClick={async()=>{
              setDeleting(true);setError("");
              try{
                const token=await (await fetch("/api/admin/session",{cache:"no-store"})).json();
                const res=await fetch("/api/admin/promoters/"+id+"/permanent-delete",{
                  method:"POST",credentials:"same-origin",
                  headers:{"Content-Type":"application/json","X-CSRF-Token":token.csrf_token},
                  body:JSON.stringify({version:record.version,confirmation:"DELETE"}),
                });
                if(!res.ok){
                  const payload=await res.json().catch(()=>null);
                  throw Error(typeof payload?.detail==="string"?payload.detail:
                    "Could not permanently delete promoter.");
                }
                window.location.assign("/promoters");
              }catch(e){setError(e instanceof Error?e.message:"Deletion failed.");}
              finally{setDeleting(false);setDeleteOpen(false);}
            }}>Yes, delete permanently</button>
        </div>
      </section>
    </div>}
    {confirm&&record&&<PromoterStatusDialog promoter={record} onClose={()=>setConfirm(false)}
      onChanged={()=>{setConfirm(false);refresh();}}/>}
  </div></AppShell>;
}
