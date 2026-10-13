"use client";
import { useEffect,useState } from "react";
import type { Candidate,Promoter,SponsorPage } from "./promoter-types";
import { csrfToken } from "./promoter-types";

export function PromoterSponsors({promoter,onChanged}:{promoter:Promoter;onChanged:()=>void}){
  const [links,setLinks]=useState<SponsorPage|null>(null);
  const [available,setAvailable]=useState<Candidate[]>([]);
  const [search,setSearch]=useState("");
  const [offset,setOffset]=useState(0);
  const [version,setVersion]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    const query=new URLSearchParams({limit:"20",offset:String(offset)});
    fetch("/api/admin/promoters/"+promoter.id+"/sponsors?"+query,{cache:"no-store",signal:controller.signal})
      .then(async r=>{if(!r.ok)throw Error("Unable to load assigned sponsors.");return await r.json() as SponsorPage;})
      .then(result=>{if(!controller.signal.aborted)setLinks(result);})
      .catch(()=>{if(!controller.signal.aborted)setError("Unable to load assigned sponsors.");});
    return ()=>controller.abort();
  },[promoter.id,version,offset]);
  useEffect(()=>{
    if(search.trim().length<2){setAvailable([]);return;}
    const controller=new AbortController();
    const timer=setTimeout(()=>{
      fetch("/api/admin/prospects?"+new URLSearchParams({q:search.trim(),limit:"20"}),{
        cache:"no-store",signal:controller.signal
      }).then(async r=>{if(!r.ok)throw Error("Unable to search.");return await r.json();})
        .then(payload=>{if(!controller.signal.aborted)setAvailable(payload.items as Candidate[]);})
        .catch(()=>{if(!controller.signal.aborted)setError("Unable to search prospects.");});
    },250);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[search,version]);
  async function change(prospect:Candidate,remove:boolean){
    if(busy)return;
    if(!remove&&!window.confirm(
      "Assign "+prospect.full_name+" to "+promoter.full_name+
      "? If already assigned, this moves the sponsor from their previous promoter."
    ))return;
    setBusy(true);setError("");
    try {
      const csrf=await csrfToken();
      const result=await fetch(
        "/api/admin/promoters/"+promoter.id+"/sponsors/"+prospect.id,{
          method:remove?"DELETE":"PUT",credentials:"same-origin",
          headers:{"X-CSRF-Token":csrf,"If-Match":String(prospect.version)},
        }
      );
      if(!result.ok){
        setError(result.status===409
          ?"Assignment changed, or promoter is inactive. Close and reopen to refresh."
          :"Could not update this sponsor assignment.");
        return;
      }
      setOffset(0);setVersion(n=>n+1);setSearch("");onChanged();
    }catch{setError("Connection problem. Assignment was not confirmed.");}
    finally{setBusy(false);}
  }
  return <section className="promoter-assignments" aria-label="Sponsor assignments">
    <h3>Assigned sponsors</h3>
    <p className="panel-description">Each sponsor has one primary promoter. The 20th-day combined follow-up will use these links once WhatsApp delivery is configured.</p>
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="promoter-sponsor-list">
      {links?.items.map(link=><div key={link.assignment_id} className="promoter-sponsor-row">
        <div><strong>{link.full_name}</strong><span>{link.mobile_number} · {link.lifecycle_status}</span></div>
        <button type="button" className="text-action" disabled={busy} onClick={()=>change({
          id:link.prospect_id,full_name:link.full_name,mobile_number:link.mobile_number,
          version:link.prospect_version,archived_at:null
        },true)}>Unassign</button>
      </div>)}
      {links?.items.length===0&&<p className="muted">No sponsors assigned to this promoter.</p>}
      {!links&&<p role="status">Loading assignments…</p>}
    </div>
    {links&&links.total>20&&<div className="paging-footer">
      <span>{offset+1}–{Math.min(links.total,offset+20)} of {links.total}</span>
      <div className="paging-actions">
        <button type="button" className="btn btn-secondary" disabled={offset===0} onClick={()=>setOffset(n=>Math.max(0,n-20))}>Previous</button>
        <button type="button" className="btn btn-secondary" disabled={offset+20>=links.total} onClick={()=>setOffset(n=>n+20)}>Next</button>
      </div>
    </div>}
    {promoter.is_active&&<div className="promoter-assign-search">
      <h3>Assign another sponsor</h3>
      <label className="field"><span className="field-label">Search registered prospects</span><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search name, phone or area" aria-label="Find sponsor"/></label>
      {search.trim().length>=2&&<div className="promoter-candidate-list">
        {available.length===0&&<span className="muted">No matching prospects found.</span>}
        {available.filter(p=>!p.archived_at).map(candidate=><div key={candidate.id} className="promoter-sponsor-row">
          <div><strong>{candidate.full_name}</strong><span>{candidate.mobile_number}</span></div>
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={()=>change(candidate,false)}>Assign</button>
        </div>)}
      </div>}
    </div>}
  </section>;
}
