"use client";

import { useEffect, useState } from "react";
import type { Promoter, SponsorLink, SponsorPage } from "./promoter-types";
import { csrfToken } from "./promoter-types";

type Mode = "all" | "individual";
export function PromoterStatusDialog({promoter,onClose,onChanged}:{
  promoter:Promoter;onClose:()=>void;onChanged:()=>void;
}){
  const [mode,setMode]=useState<Mode>("all");
  const [replacement,setReplacement]=useState("");
  const [choices,setChoices]=useState<Record<string,string>>({});
  const [others,setOthers]=useState<Promoter[]>([]);
  const [assignments,setAssignments]=useState<SponsorLink[]>([]);
  const [loaded,setLoaded]=useState(false);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    let mounted=true;
    async function load(){
      const options=await fetch("/api/admin/promoters?active=true&limit=100",{cache:"no-store"});
      if(!options.ok)throw Error("Unable to load available promoters.");
      const result=await options.json() as {items:Promoter[]};
      if(!mounted)return;
      setOthers(result.items.filter(row=>row.id!==promoter.id));
      if(promoter.is_active){
        const all:SponsorLink[]=[];
        let offset=0,total=1;
        while(offset<total){
          const response=await fetch("/api/admin/promoters/"+promoter.id+
            "/sponsors?limit=100&offset="+offset,{cache:"no-store"});
          if(!response.ok)throw Error("Unable to load assigned people.");
          const page=await response.json() as SponsorPage;
          all.push(...page.items);
          total=page.total;
          offset+=page.items.length;
          if(!page.items.length)break;
        }
        if(mounted)setAssignments(all);
      }
      if(mounted)setLoaded(true);
    }
    load().catch(e=>{if(mounted)setError(e instanceof Error?e.message:"Unable to load assignments.");});
    return()=>{mounted=false;};
  },[promoter.id,promoter.is_active]);

  const complete=mode==="all"?Boolean(replacement):assignments.every(row=>Boolean(choices[row.prospect_id]));
  async function submit(){
    if(busy||!loaded)return;
    if(promoter.is_active&&assignments.length>0&&!complete){
      setError("Choose where every assigned person should go before deactivating.");return;
    }
    setBusy(true);setError("");
    try{
      const csrf=await csrfToken();
      const change:Record<string,unknown>={version:promoter.version,is_active:!promoter.is_active};
      if(promoter.is_active&&assignments.length){
        if(mode==="all")change.reassign_to_promoter_id=replacement;
        else change.reassign_individually=Object.fromEntries(assignments.map(row=>
          [row.prospect_id,choices[row.prospect_id]==="__unassign__"?null:choices[row.prospect_id]]));
      }
      const response=await fetch("/api/admin/promoters/"+promoter.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify(change),
      });
      if(!response.ok)throw Error(response.status===409?
        "Assignments or promoter status changed. Close, refresh and retry.":
        response.status===422?"Review the assignments; all destinations must be eligible.":
        "The status change could not be saved.");
      onChanged();
    }catch(e){setError(e instanceof Error?e.message:"Could not save changes.");}
    finally{setBusy(false);}
  }
  return <div className="crm-dialog-scrim">
    <section className="crm-dialog crm-handover-dialog" role="dialog" aria-modal="true"
      aria-label="Confirm promoter status">
      <h2>{promoter.is_active?"Deactivate promoter?":"Reactivate promoter?"}</h2>
      <p>{promoter.full_name}</p>
      {!loaded&&!error&&<p role="status">Loading current assignments…</p>}
      {promoter.is_active&&loaded&&assignments.length>0&&<>
        <p>Choose where to move {assignments.length} assigned people. Changes are applied together,
          and the previous assignment history is kept.</p>
        <fieldset className="crm-handover-mode"><legend>Reassignment method</legend>
          <label><input type="radio" checked={mode==="all"}
            onChange={()=>setMode("all")}/> Transfer everyone to one promoter</label>
          <label><input type="radio" checked={mode==="individual"}
            onChange={()=>setMode("individual")}/> Choose for each person</label>
        </fieldset>
        {mode==="all"?<label className="field">
          <span className="field-label">New promoter *</span>
          <select value={replacement} onChange={e=>setReplacement(e.target.value)}>
            <option value="">Select an active promoter</option>
            {others.map(p=><option key={p.id} value={p.id}>{p.full_name}</option>)}
          </select></label>:<div className="crm-handover-people" aria-label="Individual assignments">
          {assignments.map(row=><label key={row.assignment_id} className="crm-handover-person">
            <span><strong>{row.full_name}</strong><small>{row.mobile_number}</small></span>
            <select aria-label={"Reassign "+row.full_name} value={choices[row.prospect_id]??""}
              onChange={e=>setChoices(prev=>({...prev,[row.prospect_id]:e.target.value}))}>
              <option value="">Choose destination *</option>
              {others.map(p=><option key={p.id} value={p.id}>{p.full_name}</option>)}
              <option value="__unassign__">Leave unassigned</option>
            </select>
          </label>)}
        </div>}
      </>}
      {promoter.is_active&&loaded&&!assignments.length&&
        <p className="crm-muted">No assignments need transferring.</p>}
      {error&&<p className="form-error" role="alert">{error}</p>}
      <div className="form-actions">
        <button className="btn btn-secondary" type="button" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" type="button" onClick={submit}
          disabled={busy||!loaded||(promoter.is_active&&assignments.length>0&&!complete)}>
          {busy?"Saving…":promoter.is_active?"Confirm deactivation":"Reactivate"}
        </button>
      </div>
    </section>
  </div>;
}
