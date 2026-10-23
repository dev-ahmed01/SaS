"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { Prospect } from "./prospects-types";
import { reasonLabel, stageReasons } from "./prospects-types";

export function StageDialog({prospect,onClose,onChanged}:{
  prospect:Prospect;onClose:()=>void;onChanged:(updated:Prospect)=>void;
}) {
  const isInactive=prospect.crm_stage==="active";
  const [reason,setReason]=useState("");
  const [note,setNote]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const ref=useRef<HTMLSelectElement>(null);

  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    ref.current?.focus();
    function onKey(e:KeyboardEvent){
      if(e.key==="Escape"){e.preventDefault();onClose();}
    }
    window.addEventListener("keydown",onKey);
    return ()=>{window.removeEventListener("keydown",onKey);previous?.focus();};
  },[onClose]);

  async function submit(event:FormEvent){
    event.preventDefault();
    if(saving)return;
    if(isInactive&&!reason){setError("Select why this prospect is becoming inactive.");return;}
    if(!isInactive&&note.trim().length<3){setError("Record the follow-up and why the prospect is ready.");return;}
    setSaving(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Your session has expired. Sign in again.");
      const {csrf_token}=await session.json();
      const response=await fetch("/api/admin/prospects/"+prospect.id+"/stage",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({version:prospect.version,stage:isInactive?"inactive":"active",
          reason:isInactive?reason:null,note:note.trim()||null})
      });
      if(!response.ok)throw Error(response.status===409
        ?"This record changed. Close and reopen it to refresh."
        :"Could not update the stage. Please try again.");
      onChanged(await response.json() as Prospect);
    }catch(e){setError(e instanceof Error?e.message:"Unable to update the prospect.");}
    finally{setSaving(false);}
  }

  return <div className="crm-dialog-scrim" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
    <section className="crm-dialog" role="dialog" aria-modal="true"
      aria-label={isInactive?"Mark prospect inactive":"Reactivate prospect"}>
      <div className="crm-dialog-head">
        <div><h2>{isInactive?"Mark inactive":"Move to Active"}</h2>
          <p>{prospect.full_name}</p></div>
        <button type="button" className="text-action" onClick={onClose} aria-label="Close stage dialog">Close</button>
      </div>
      <form onSubmit={submit}>
        {isInactive ? <>
          <label className="field"><span className="field-label">Reason for leaving *</span>
            <select ref={ref} required value={reason} onChange={e=>setReason(e.target.value)}>
              <option value="">Choose a reason</option>
              {stageReasons.map(x=><option key={x.value} value={x.value}>{x.label}</option>)}
            </select></label>
          <label className="field"><span className="field-label">Additional context (optional)</span>
            <textarea maxLength={500} rows={3} value={note} onChange={e=>setNote(e.target.value)}
              placeholder="Brief context to help understand attrition"/></label>
          <p className="crm-dialog-help">This pauses reminder eligibility and records the reason. It does not erase payments or alter the accounting ledger.</p>
        </> : <>
          <p className="crm-dialog-help">Confirm you have contacted this prospect and record the outcome. Activating CRM contact does not record a payment.</p>
          <label className="field"><span className="field-label">Previous reason</span>
            <input value={reasonLabel(prospect.crm_inactive_reason)} readOnly/></label>
          <label className="field"><span className="field-label">Follow-up outcome / reason for activation *</span>
            <textarea ref={undefined} required minLength={3} maxLength={500} rows={3}
              value={note} onChange={e=>setNote(e.target.value)}
              placeholder="Who was contacted, their response, and agreed next step"/></label>
          <select ref={ref} className="sr-only" tabIndex={-1} aria-hidden="true"><option>Confirm</option></select>
        </>}
        {error&&<p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving||(isInactive?!reason:note.trim().length<3)}>
            {saving?"Saving…":isInactive?"Confirm Inactive":"Mark Active"}
          </button>
        </div>
      </form>
    </section>
  </div>;
}
