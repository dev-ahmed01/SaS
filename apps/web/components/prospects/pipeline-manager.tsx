"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Icon } from "../ui/icon";
import { pipelineStages, stagePalette } from "./pipeline-types";
import type { PipelineStage } from "./pipeline-types";

type FormData={name:string;description:string;color:string;sort_order:string};
const blank:FormData={name:"",description:"",color:stagePalette[0],sort_order:"0"};

export function PipelineManager(){
  const [items,setItems]=useState<PipelineStage[]>([]);
  const [form,setForm]=useState<FormData>(blank);
  const [editing,setEditing]=useState<PipelineStage|null>(null);
  const [deleting,setDeleting]=useState<PipelineStage|null>(null);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);

  const load=useCallback(async()=>{
    setItems(await pipelineStages());
  },[]);
  useEffect(()=>{
    let active=true;
    setLoading(true);
    load().catch(e=>{if(active)setError(e.message);})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[load,revision]);

  function edit(item:PipelineStage){
    setEditing(item);setError("");
    setForm({
      name:item.name,description:item.description??"",
      color:item.color,sort_order:String(item.sort_order),
    });
    document.getElementById("pipeline-stage-name")?.focus();
    window.scrollTo({top:0,behavior:"smooth"});
  }
  function reset(){
    setEditing(null);setForm(blank);setError("");
  }
  async function getCsrf(){
    const r=await fetch("/api/admin/session",{cache:"no-store"});
    if(!r.ok)throw Error("Session expired. Sign in again.");
    return (await r.json()).csrf_token as string;
  }
  async function submit(e:FormEvent){
    e.preventDefault();if(saving)return;
    const order=Number(form.sort_order);
    if(!form.name.trim()){setError("Name is required.");return;}
    if(!Number.isInteger(order)||order<0||order>9999){
      setError("Order must be a whole number from 0 to 9999.");return;
    }
    setSaving(true);setError("");
    try{
      const csrf=await getCsrf();
      const body={
        name:form.name.trim(),description:form.description.trim()||null,
        color:form.color,sort_order:order,
        ...(editing?{version:editing.version}:{}),
      };
      const r=await fetch("/api/admin/prospect-stages"+(editing?"/"+editing.id:""),{
        method:editing?"PATCH":"POST",credentials:"same-origin",
        headers:{"X-CSRF-Token":csrf,"Content-Type":"application/json"},
        body:JSON.stringify(body),
      });
      if(!r.ok)throw Error(r.status===409
        ?"Stage name already exists, or the record changed. Refresh and retry."
        :r.status===422?"Check stage name, color and order.":"Stage could not be saved.");
      reset();setRevision(v=>v+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to save stage.");}
    finally{setSaving(false);}
  }
  async function remove(){
    if(!deleting||saving)return;
    setSaving(true);setError("");
    try{
      const csrf=await getCsrf();
      const r=await fetch("/api/admin/prospect-stages/"+deleting.id,{
        method:"DELETE",credentials:"same-origin",
        headers:{"X-CSRF-Token":csrf,"If-Match":String(deleting.version)},
      });
      if(!r.ok)throw Error(r.status===409
        ?"This stage is assigned or changed. Reassign prospects before deletion."
        :"Could not delete the stage.");
      setDeleting(null);setRevision(v=>v+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to delete stage.");}
    finally{setSaving(false);}
  }
  return <section className="pipeline-manager" aria-label="Manage prospect stages">
    <div className="pipeline-form prospect-form-panel">
      <div className="prospect-form-intro">
        <h2>{editing?"Edit stage":"Add stage"}</h2>
        <p>Customize your prospect journey</p>
      </div>
      <form onSubmit={submit}>
        <div className="prospect-field-row two">
          <label className="field"><span className="field-label">Name *</span>
            <input id="pipeline-stage-name" required maxLength={80} value={form.name}
              onChange={e=>setForm(p=>({...p,name:e.target.value}))}
              placeholder="Stage name"/></label>
          <label className="field"><span className="field-label">Description (optional)</span>
            <input maxLength={300} value={form.description}
              onChange={e=>setForm(p=>({...p,description:e.target.value}))}
              placeholder="Brief description"/></label>
        </div>
        <div className="pipeline-controls">
          <fieldset className="pipeline-colors"><legend>Color</legend>
            <div className="pipeline-color-swatches">
              {stagePalette.map(color=><button type="button" key={color}
                className={"pipeline-swatch"+(form.color===color?" selected":"")}
                style={{backgroundColor:color}} aria-label={"Choose color "+color}
                aria-pressed={form.color===color}
                onClick={()=>setForm(p=>({...p,color}))}/>)}
              <label className="pipeline-custom-color" title="Custom color">
                <span className="sr-only">Custom stage color</span>
                <input type="color" value={form.color}
                  onChange={e=>setForm(p=>({...p,color:e.target.value}))}/>
              </label>
            </div>
          </fieldset>
          <label className="field pipeline-order"><span className="field-label">Order</span>
            <input type="number" min="0" max="9999" step="1" value={form.sort_order}
              onChange={e=>setForm(p=>({...p,sort_order:e.target.value}))}/></label>
          <div className="pipeline-submit-actions">
            {editing&&<button type="button" className="btn btn-secondary"
              onClick={reset} disabled={saving}>Cancel</button>}
            <button className="btn btn-primary" type="submit" disabled={saving}>
              <Icon name="plus" size={15}/>{saving?"Saving…":editing?"Save Stage":"Add Stage"}
            </button>
          </div>
        </div>
      </form>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    <div className="pipeline-stage-list" aria-label="Configured stages">
      {loading?<p role="status">Loading stages…</p>:items.length===0?
        <div className="crm-list-empty">
          <Icon name="layers" size={27}/><h2>No stages configured</h2>
          <p>Create your first stage above. You can edit or remove it later.</p>
        </div>:items.map(item=><article className="pipeline-stage-row" key={item.id}>
          <span className="pipeline-stage-dot" style={{backgroundColor:item.color}}/>
          <div className="pipeline-stage-content">
            <strong>{item.name}</strong>
            {item.is_registration_default&&<span className="crm-muted">Registration default</span>}
            {item.description&&<span>{item.description}</span>}
          </div>
          <span className="pipeline-stage-count">{item.prospect_count} prospects</span>
          <span className="pipeline-stage-order">#{item.sort_order}</span>
          <button type="button" className="icon-button" aria-label={"Edit stage "+item.name}
            onClick={()=>edit(item)}><Icon name="pencil" size={17}/></button>
          {!item.is_registration_default&&
            <button type="button" className="icon-button pipeline-delete"
              aria-label={"Delete stage "+item.name}
              onClick={()=>setDeleting(item)}><Icon name="trash" size={17}/></button>}
        </article>)}
    </div>
    {deleting&&<div className="crm-dialog-scrim">
      <section role="dialog" aria-modal="true" aria-label="Confirm stage deletion"
        className="crm-dialog">
        <h2>Delete {deleting.name}?</h2>
        <p>Only unassigned stages can be deleted. This does not delete prospects.</p>
        {deleting.prospect_count>0&&<p className="form-error">
          {deleting.prospect_count} active records are assigned. Move them to another stage first.
        </p>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary"
            onClick={()=>setDeleting(null)} disabled={saving}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={saving||deleting.prospect_count>0}
            onClick={remove}>{saving?"Deleting…":"Delete stage"}</button>
        </div>
      </section>
    </div>}
  </section>;
}
