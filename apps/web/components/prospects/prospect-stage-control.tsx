"use client";

import { useEffect, useState } from "react";
import { pipelineStages, type PipelineStage } from "./pipeline-types";
import type { Prospect } from "./prospects-types";

export function ProspectStageControl({prospect,onChanged}:{
  prospect:Prospect;onChanged:()=>void;
}){
  const [stages,setStages]=useState<PipelineStage[]>([]);
  const [value,setValue]=useState(prospect.pipeline_stage_id??"");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{setValue(prospect.pipeline_stage_id??"");},[prospect.pipeline_stage_id]);
  useEffect(()=>{
    let alive=true;
    pipelineStages().then(items=>{if(alive)setStages(items);})
      .catch(()=>{if(alive)setError("Could not load stages.");});
    return()=>{alive=false;};
  },[]);
  async function change(next:string){
    if(busy||next===value)return;
    const previous=value;
    setValue(next);setBusy(true);setError("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired. Sign in again.");
      const {csrf_token}=await session.json();
      const response=await fetch("/api/admin/prospects/"+prospect.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({version:prospect.version,pipeline_stage_id:next||null}),
      });
      if(!response.ok)throw Error(response.status===409?
        "Prospect changed elsewhere. Refresh before changing stage.":
        "Stage could not be updated.");
      onChanged();
    }catch(e){setValue(previous);setError(e instanceof Error?e.message:"Could not update stage.");}
    finally{setBusy(false);}
  }
  return <div className="crm-stage-control">
    <label className="field"><span className="field-label">Prospect stage</span>
      <select aria-label="Change prospect stage" value={value} disabled={busy||!stages.length||Boolean(prospect.archived_at)}
        onChange={e=>void change(e.target.value)}>
        <option value="">Unassigned</option>
        {stages.map(stage=><option key={stage.id} value={stage.id}>{stage.name}</option>)}
      </select>
    </label>
    {error&&<p className="form-error" role="alert">{error}</p>}
  </div>;
}
