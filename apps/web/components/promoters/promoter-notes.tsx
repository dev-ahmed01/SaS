"use client";

import { useEffect, useState } from "react";
import type { Promoter } from "./promoter-types";
import { csrfToken } from "./promoter-types";

export function PromoterNotes({promoter,onChanged}:{
  promoter:Promoter;onChanged:()=>void;
}){
  const [draft,setDraft]=useState(promoter.notes??"");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [saved,setSaved]=useState(false);
  useEffect(()=>{setDraft(promoter.notes??"");setSaved(false);},[promoter.id,promoter.notes]);
  const changed=draft.trim()!==(promoter.notes??"");
  async function save(){
    if(saving||!changed)return;
    setSaving(true);setError("");setSaved(false);
    try{
      const csrf=await csrfToken();
      const response=await fetch("/api/admin/promoters/"+promoter.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({version:promoter.version,notes:draft.trim()||null}),
      });
      if(!response.ok)throw new Error(response.status===409
        ?"Promoter details changed. Refresh and review your note before saving."
        :"Could not save internal notes.");
      setSaved(true);onChanged();
    }catch(e){setError(e instanceof Error?e.message:"Could not save notes.");}
    finally{setSaving(false);}
  }
  return <section className="crm-detail-card promoter-notes-panel" aria-label="Internal promoter notes">
    <div className="crm-panel-heading">
      <h2>Notes</h2><span className="crm-muted">Internal — Admin only</span>
    </div>
    <label className="field">
      <span className="field-label">Notes about this promoter</span>
      <textarea rows={3} maxLength={1500} value={draft}
        placeholder="Add an internal note…" onChange={e=>{setDraft(e.target.value);setError("");setSaved(false);}}/>
    </label>
    <div className="promoter-notes-bottom">
      <span>{error?<span className="form-error" role="alert">{error}</span>:
        saved?<span role="status">Saved</span>:changed?"Unsaved changes":""}</span>
      <button type="button" className="btn btn-secondary" onClick={save}
        disabled={!changed||saving}>{saving?"Saving…":"Save note"}</button>
    </div>
  </section>;
}
