"use client";

import {FormEvent,useCallback,useEffect,useState} from "react";
import Link from "next/link";

export type FieldOption = {
  id:string;field_key:"payout_purpose";code:string;label:string;
  is_active:boolean;sort_order:number;version:number;
};
export type FieldOptionPage = {field_key:string;items:FieldOption[]};

export function FieldOptions({csrf,role}:{csrf:string;role:string}){
  const [rows,setRows]=useState<FieldOption[]>([]);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [newLabel,setNewLabel]=useState("");
  const [editing,setEditing]=useState<string|null>(null);
  const [draft,setDraft]=useState("");
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const owner=role==="owner";

  const load=useCallback(async()=>{
    const res=await fetch("/api/admin/settings/field-options?field_key=payout_purpose",
      {cache:"no-store"});
    if(!res.ok)throw new Error("Could not load configurable payout purposes.");
    const data=await res.json() as FieldOptionPage;
    setRows(data.items??[]);setError("");
  },[]);
  useEffect(()=>{
    let active=true;
    (async()=>{try{await load();}catch{
      if(active)setError("Could not load payout purpose options. Try again.");
    }finally{if(active)setLoading(false);}})();
    return()=>{active=false;};
  },[load]);

  async function mutate(url:string,method:"POST"|"PATCH",body:unknown,success:string):Promise<boolean>{
    if(!owner||busy||!csrf)return false;
    setBusy(true);setError("");setNotice("");
    try{
      const response=await fetch(url,{method,credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify(body)});
      if(!response.ok){
        const problem=await response.json().catch(()=>({detail:"Change was not saved."}));
        throw new Error(typeof problem?.detail==="string"?problem.detail:
          "Change was not saved. Refresh your options and retry.");
      }
      await load();
      setEditing(null);
      setNotice(success);
      return true;
    }catch(exc){
      setError(exc instanceof Error?exc.message:"Could not update field options.");
      return false;
    }finally{setBusy(false);}
  }
  async function add(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const label=newLabel.trim().replace(/\s+/g," ");
    if(label.length<2||label.length>240){
      setError("Option labels must contain 2–240 characters.");return;
    }
    const added=await mutate("/api/admin/settings/field-options","POST",
      {field_key:"payout_purpose",label},"Purpose added.");
    if(added)setNewLabel("");
  }
  async function update(row:FieldOption,body:Record<string,unknown>,success:string){
    await mutate("/api/admin/settings/field-options/"+row.id,"PATCH",
      {version:row.version,...body},success);
  }
  function move(index:number,direction:-1|1){
    const other=index+direction;
    if(other<0||other>=rows.length)return;
    const items=rows.map(r=>r.id);
    [items[index],items[other]]=[items[other],items[index]];
    void mutate("/api/admin/settings/field-options/reorder","POST",
      {field_key:"payout_purpose",item_ids:items},"Option order updated.");
  }

  return <section className="content-panel field-options-settings"
      aria-label="Field Options">
    <div className="field-options-heading">
      <div>
        <p className="field-options-eyebrow">FIELD OPTIONS</p>
        <h2>Manage field options</h2>
        <p className="crm-muted">Keep Payout Purpose names consistent across records.
          Existing payout history retains its original descriptions.</p>
      </div>
      <span className="field-options-count">{rows.filter(r=>r.is_active).length} active</span>
    </div>
    <div className="field-options-group-head">
      <div>
        <h3>Payout purpose</h3>
        <p className="crm-muted">These choices appear in the Add Payout dropdown.</p>
      </div>
      <Link className="btn btn-secondary btn-action" href="/payouts">View payouts</Link>
    </div>
    {loading&&<p role="status">Loading purpose options…</p>}
    {error&&<p className="form-error" role="alert">{error}{" "}
      <button className="text-action" type="button" onClick={()=>void load().catch(
        ()=>setError("Unable to reload. Please check your connection."))}>Retry</button></p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
    {!loading&&<div className="field-options-list">
      {rows.map((row,index)=><div className={"field-option-item"+(!row.is_active?" is-inactive":"")}
        key={row.id}>
        <span className="field-option-order">{String(index+1).padStart(2,"0")}</span>
        <div className="field-option-label">
          {editing===row.id?
            <label className="field">
              <span className="field-label">Edit option</span>
              <input autoFocus value={draft} maxLength={240}
                onChange={e=>setDraft(e.target.value)}/>
            </label>:
            <><strong>{row.label}</strong><small>
              {row.is_active?"Available for new payouts":"Inactive · historical payouts retained"}
            </small></>}
        </div>
        {owner&&<div className="field-option-actions">
          {editing===row.id?<>
            <button type="button" className="btn btn-primary btn-action" disabled={busy}
              onClick={()=>void update(row,{label:draft.trim()},"Option renamed.")}>Save</button>
            <button type="button" className="btn btn-secondary btn-action"
              onClick={()=>setEditing(null)} disabled={busy}>Cancel</button>
          </>:<>
            <button type="button" aria-label={"Move "+row.label+" up"} title="Move up"
              className="field-option-order-btn" disabled={busy||index===0}
              onClick={()=>move(index,-1)}>↑</button>
            <button type="button" aria-label={"Move "+row.label+" down"} title="Move down"
              className="field-option-order-btn" disabled={busy||index===rows.length-1}
              onClick={()=>move(index,1)}>↓</button>
            <button type="button" className="btn btn-secondary btn-row-action"
              disabled={busy} onClick={()=>{setEditing(row.id);setDraft(row.label);}}>Edit</button>
            <button type="button" className={
                "btn btn-row-action "+(row.is_active?"crm-danger-btn":"btn-secondary")}
              disabled={busy} onClick={()=>{
                if(!window.confirm((row.is_active?"Deactivate":"Reactivate")+
                  ' "'+row.label+'"? Historical payout descriptions remain unchanged.'))return;
                void update(row,{is_active:!row.is_active},
                  row.is_active?"Option deactivated.":"Option reactivated.");
              }}>{row.is_active?"Deactivate":"Reactivate"}</button>
          </>}
        </div>}
      </div>)}
      {!rows.length&&<p className="crm-muted">No purpose options have been configured.</p>}
    </div>}
    {owner&&<form className="field-option-add" onSubmit={add}>
      <label className="field">
        <span className="field-label">Add a payout purpose</span>
        <input value={newLabel} maxLength={240} placeholder="e.g. Office supplies"
          onChange={e=>{setNewLabel(e.target.value);setError("");}} required minLength={2}/>
      </label>
      <button type="submit" className="btn btn-primary"
        disabled={busy||newLabel.trim().length<2}>Add option</button>
    </form>}
    {!owner&&<p className="crm-muted">Only an owner can change field options.</p>}
  </section>;
}
