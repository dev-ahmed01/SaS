"use client";
import Link from "next/link";
import { useEffect,useState } from "react";
import { Icon } from "../ui/icon";
import { formatCRMDate } from "../../lib/crm-dates";
import type { Candidate,Promoter,SponsorPage } from "./promoter-types";
import { csrfToken } from "./promoter-types";

const money=(amount:number)=>(amount/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",maximumFractionDigits:0,
});
export function PromoterSponsors({promoter,onChanged,kind,onCount}:{
  promoter:Promoter;onChanged:()=>void;kind:"sponsors"|"prospects";
  onCount?:(count:number)=>void;
}){
  const [links,setLinks]=useState<SponsorPage|null>(null);
  const [available,setAvailable]=useState<Candidate[]>([]);
  const [search,setSearch]=useState("");
  const [offset,setOffset]=useState(0);
  const [version,setVersion]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    const query=new URLSearchParams({limit:"20",offset:String(offset),kind});
    fetch("/api/admin/promoters/"+promoter.id+"/sponsors?"+query,{cache:"no-store",signal:controller.signal})
      .then(async r=>{if(!r.ok)throw Error("Unable to load assigned people.");return await r.json() as SponsorPage;})
      .then(result=>{if(!controller.signal.aborted){setLinks(result);onCount?.(result.total);}})
      .catch(()=>{if(!controller.signal.aborted)setError("Unable to load assigned people.");});
    return ()=>controller.abort();
  },[promoter.id,version,offset,kind,onCount]);
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
      "? If already assigned, this moves them from their previous promoter."
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
          ?"Assignment changed or promoter is inactive. Refresh and retry."
          :"Could not update this assignment.");
        return;
      }
      setOffset(0);setVersion(n=>n+1);setSearch("");onChanged();
    }catch{setError("Connection problem. Assignment was not confirmed.");}
    finally{setBusy(false);}
  }
  const title=kind==="sponsors"?"Sponsors":"Prospects";
  return <section className="promoter-assignments" aria-label={kind==="sponsors"?"Sponsor assignments":"Prospect assignments"}>
    <div className="promoter-list-heading">
      <h3><Icon name={kind==="sponsors"?"users":"user-plus"} size={19}/>
        {title} ({links?.total??"…"})</h3>
    </div>
    <p className="panel-description">{kind==="sponsors"
      ?"People who have made a recorded contribution"
      :"Registered people awaiting a first contribution"}</p>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {links?.items.length?<div className="promoter-assignment-scroll">
      <table className="promoter-assignment-table">
        <thead><tr><th scope="col">Name</th><th scope="col">City</th>
          <th scope="col">Start month</th><th scope="col">Monthly</th>
          <th scope="col">Status</th><th scope="col">Action</th></tr></thead>
        <tbody>{links.items.map(link=><tr key={link.assignment_id}>
          <td><Link href={"/prospects/"+link.prospect_id} className="promoter-person-link">{link.full_name}</Link>
            <small>{link.mobile_number}</small></td>
          <td>{link.area_city||"—"}</td>
          <td>{link.start_month?formatCRMDate(link.start_month):"—"}</td>
          <td>{money(link.monthly_contribution_paise)}</td>
          <td><span className={"status-pill "+link.crm_stage}>{link.crm_stage==="active"?"Active":"Inactive"}</span></td>
          <td><button type="button" className="text-action" disabled={busy}
            onClick={()=>change({
              id:link.prospect_id,full_name:link.full_name,mobile_number:link.mobile_number,
              version:link.prospect_version,archived_at:null
            },true)}>Unassign</button></td>
        </tr>)}</tbody>
      </table>
    </div>:links?<div className="promoter-empty-state">
      <span className="promoter-empty-icon"><Icon name="users" size={26}/></span>
      <p>No assigned {kind}.</p>
      <small>{kind==="sponsors"
        ?"Contributors will appear here after a recorded payment."
        :"Registered prospects assigned to this promoter will appear here."}</small>
    </div>:<p role="status">Loading assignments…</p>}
    {links&&links.total>20&&<div className="paging-footer">
      <span>{offset+1}–{Math.min(links.total,offset+20)} of {links.total}</span>
      <div className="paging-actions">
        <button type="button" className="btn btn-secondary" disabled={offset===0}
          onClick={()=>setOffset(n=>Math.max(0,n-20))}>Previous</button>
        <button type="button" className="btn btn-secondary" disabled={offset+20>=links.total}
          onClick={()=>setOffset(n=>n+20)}>Next</button>
      </div>
    </div>}
    {promoter.is_active&&kind==="prospects"&&<div className="promoter-assign-search">
      <h3>Assign a prospect</h3>
      <label className="field"><span className="field-label">Search registered prospects</span>
        <input value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="Search name, phone or city" aria-label="Find sponsor"/></label>
      {search.trim().length>=2&&<div className="promoter-candidate-list">
        {available.length===0&&<span className="muted">No matching prospects found.</span>}
        {available.filter(p=>!p.archived_at).map(candidate=>
          <div key={candidate.id} className="promoter-sponsor-row">
            <div><strong>{candidate.full_name}</strong><span>{candidate.mobile_number}</span></div>
            <button type="button" className="btn btn-secondary" disabled={busy}
              onClick={()=>change(candidate,false)}>Assign</button>
          </div>)}
      </div>}
    </div>}
  </section>;
}
