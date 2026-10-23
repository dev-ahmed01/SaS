"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../app-shell";
import { Icon } from "../ui/icon";
import { ContactConsent } from "../communication/contact-consent";
import { PromoterEditor } from "./promoter-editor";
import { PromoterSponsors } from "./promoter-sponsors";
import type { Promoter } from "./promoter-types";
import { csrfToken } from "./promoter-types";
import { formatCRMDate } from "../../lib/crm-dates";

const day=(value:string)=>formatCRMDate(value);
function Info({label,value}:{label:string;value:string}){
  return <div className="crm-detail-field"><dt>{label}</dt><dd>{value||"—"}</dd></div>;
}
function Card({title,children}:{title:string;children:React.ReactNode}){
  return <section className="crm-detail-card">
    <h2>{title}</h2><dl className="crm-detail-grid">{children}</dl>
  </section>;
}
export function PromoterDetails({id}:{id:string}){
  const [record,setRecord]=useState<Promoter|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [confirm,setConfirm]=useState(false);
  const [replacement,setReplacement]=useState("");
  const [otherPromoters,setOtherPromoters]=useState<Promoter[]>([]);
  const [busy,setBusy]=useState(false);
  const [revision,setRevision]=useState(0);
  const load=useCallback(async(signal?:AbortSignal)=>{
    const res=await fetch("/api/admin/promoters/"+id,{cache:"no-store",signal});
    if(!res.ok)throw Error("Could not load promoter details.");
    return await res.json() as Promoter;
  },[id]);
  useEffect(()=>{
    const controller=new AbortController();setError("");setLoading(true);
    load(controller.signal)
      .then(data=>{if(!controller.signal.aborted)setRecord(data);})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[load,revision]);
  useEffect(()=>{
    if(!confirm||!record?.is_active||!record.sponsor_count)return;
    const controller=new AbortController();
    fetch("/api/admin/promoters?active=true&limit=100",{
      cache:"no-store",signal:controller.signal,
    }).then(r=>r.json()).then(data=>{
      if(!controller.signal.aborted)setOtherPromoters(
        (data.items as Promoter[]).filter(p=>p.id!==record.id));
    }).catch(()=>{if(!controller.signal.aborted)setError("Could not load replacement promoters.");});
    return ()=>controller.abort();
  },[confirm,record]);
  async function toggleStatus(){
    if(!record||busy)return;
    if(record.is_active&&record.sponsor_count&&!replacement){
      setError("Select an active replacement promoter before deactivating.");return;
    }
    setBusy(true);setError("");
    try{
      const csrf=await csrfToken();
      const result=await fetch("/api/admin/promoters/"+record.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({version:record.version,is_active:!record.is_active,
          ...(record.is_active&&record.sponsor_count?{reassign_to_promoter_id:replacement}:{})}),
      });
      if(!result.ok)throw Error(result.status===409
        ?"The record changed or sponsors are still assigned. Reload and retry."
        :"Could not update promoter status.");
      setConfirm(false);setRevision(x=>x+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to update status.");}
    finally{setBusy(false);}
  }
  return <AppShell>
    <div className="crm-details">
      <Link className="back-link" href="/promoters">
        <Icon name="arrow-left" size={17}/> All promoters
      </Link>
      {error&&<p role="alert" className="form-error">{error}</p>}
      {loading?<p role="status">Loading promoter…</p>:record&&<>
        <div className="crm-details-header">
          <div><h2>{record.full_name}</h2><p>Created {day(record.created_at)}</p></div>
          <span className={"status-pill "+(record.is_active?"active":"inactive")}>
            {record.is_active?"Active":"Inactive"}</span>
        </div>
        <div className="crm-detail-actions promoter-detail-actions">
          <button type="button" className="crm-action-card" onClick={()=>setEditing(v=>!v)}>
            <Icon name="file" size={22}/>
            <span><strong>Edit details</strong><small>Update promoter information</small></span>
          </button>
          <button type="button" className="crm-action-card" onClick={()=>setConfirm(true)}>
            <Icon name="users" size={22}/>
            <span><strong>{record.is_active?"Deactivate":"Reactivate"}</strong>
              <small>Change promoter status</small></span>
          </button>
        </div>
        {editing&&<PromoterEditor initial={record} onCancel={()=>setEditing(false)}
          onSaved={()=>{setEditing(false);setRevision(v=>v+1);}}/>}
        <div className="promoter-two-column">
        <div className="promoter-column">
          <Card title="Personal information">
            <Info label="First Name" value={record.first_name??record.full_name.split(" ")[0]}/>
            <Info label="Last Name" value={record.last_name??record.full_name.split(" ").slice(1).join(" ")}/>
            <Info label="City" value={record.area_city}/>
            <Info label="Occupation" value={record.occupation??""}/>
          </Card>
          <Card title="Contact">
            <Info label="Mobile" value={record.mobile_number}/>
            <Info label="Email" value={record.email??""}/>
            <Info label="WhatsApp consent" value={record.whatsapp_opt_in?"Recorded":"Not recorded"}/>
          </Card>
          <ContactConsent recipientKind="promoter" recipientId={record.id}
            legacyWhatsAppOptIn={record.whatsapp_opt_in}
            allowGrant={record.is_active}/>
        </div>
        <div className="promoter-column">
          <Card title="Assignments & status">
            <Info label="Sponsors" value={String(record.sponsor_count)}/>
            <Info label="Status" value={record.is_active?"Active":"Inactive"}/>
            <Info label="Last updated" value={day(record.updated_at)}/>
          </Card>
          <section className="crm-detail-card crm-assignment-card">
            <PromoterSponsors promoter={record} kind="sponsors"
              onChanged={()=>setRevision(x=>x+1)}/>
          </section>
          <section className="crm-detail-card crm-assignment-card">
            <PromoterSponsors promoter={record} kind="prospects"
              onChanged={()=>setRevision(x=>x+1)}/>
          </section>
        </div>
      </div>
      </>}
    </div>
    {confirm&&record&&<div className="crm-dialog-scrim">
      <section className="crm-dialog" role="dialog" aria-modal="true"
        aria-label="Confirm promoter status">
        <h2>{record.is_active?"Deactivate promoter?":"Reactivate promoter?"}</h2>
        <p>{record.full_name}</p>
        {record.is_active&&record.sponsor_count>0&&<>
          <p>Select an active promoter to transfer all {record.sponsor_count} assignments to.
            Future WhatsApp summaries will use the replacement promoter.</p>
          <label className="field"><span className="field-label">Reassign to *</span>
            <select required aria-label="Replacement promoter" value={replacement}
              onChange={e=>setReplacement(e.target.value)}>
              <option value="">Select active promoter</option>
              {otherPromoters.map(p=><option key={p.id} value={p.id}>{p.full_name}</option>)}
            </select></label>
        </>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" disabled={busy}
            onClick={()=>setConfirm(false)}>Cancel</button>
          <button type="button" className="btn btn-primary"
            disabled={busy||(record.is_active&&record.sponsor_count>0&&!replacement)}
            onClick={toggleStatus}>{busy?"Saving…":"Confirm"}</button>
        </div>
      </section>
    </div>}
  </AppShell>;
}
