"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { Icon } from "../ui/icon";
import type { Promoter, PromoterPage } from "./promoter-types";
import { csrfToken } from "./promoter-types";
import { formatCRMDate } from "../../lib/crm-dates";

const displayDate=formatCRMDate;

export function PromoterList({view}:{view:"all"|"active"|"inactive"}){
  const [search,setSearch]=useState("");
  const [q,setQ]=useState("");
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [page,setPage]=useState<PromoterPage|null>(()=>recentSnapshot<PromoterPage>("/api/admin/promoters?"+new URLSearchParams({q:"",limit:"20",offset:"0",...(view!=="all"?{active:String(view==="active")}:{})})));
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [pending,setPending]=useState(false);
  const [target,setTarget]=useState<Promoter|null>(null);

  useEffect(()=>{
    const timer=setTimeout(()=>{setQ(search);setOffset(0);},250);
    return ()=>clearTimeout(timer);
  },[search]);
  useEffect(()=>setOffset(0),[view]);
  const fetchPage=useCallback(async(signal:AbortSignal)=>{
    const query=new URLSearchParams({q,limit:"20",offset:String(offset)});
    if(view!=="all")query.set("active",String(view==="active"));
    const response=await fetch("/api/admin/promoters?"+query,{
      cache:"no-store",signal,
    });
    if(!response.ok)throw Error("Unable to load promoters.");
    return await response.json() as PromoterPage;
  },[q,offset,view]);
  useEffect(()=>{
    const abort=new AbortController();
    const query=new URLSearchParams({q,limit:"20",offset:String(offset)});
    if(view!=="all")query.set("active",String(view==="active"));
    const key="/api/admin/promoters?"+query;
    const cached=recentSnapshot<PromoterPage>(key);
    setPage(cached);setLoading(!cached);setError("");
    fetchPage(abort.signal)
      .then(data=>{if(!abort.signal.aborted){rememberSnapshot(key,data);setPage(data);}})
      .catch(e=>{if(!abort.signal.aborted)setError(e.message);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return ()=>abort.abort();
  },[fetchPage,revision]);

  async function toggle(){
    if(!target||pending)return;
    if(target.is_active && target.sponsor_count){
      setError("Reassign or unassign every sponsor before deactivating this promoter.");
      setTarget(null);return;
    }
    setPending(true);setError("");
    try{
      const csrf=await csrfToken();
      const res=await fetch("/api/admin/promoters/"+target.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"X-CSRF-Token":csrf,"Content-Type":"application/json"},
        body:JSON.stringify({version:target.version,is_active:!target.is_active}),
      });
      if(!res.ok)throw Error(res.status===409
        ?"This promoter was updated or still has assigned sponsors. Refresh and retry."
        :"Could not change promoter status.");
      setTarget(null);setRevision(v=>v+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to update status.");}
    finally{setPending(false);}
  }
  const title=view==="all"?"All Promoters":view==="active"?"Active Promoters":"Inactive Promoters";
  return <section className="crm-list" aria-label={title}>
    <div className="crm-list-tools">
      <label className="search-control">
        <Icon name="search" size={18}/><span className="sr-only">Search promoters</span>
        <input value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="Search names, mobile, city or occupation…"/>
      </label>
      <span className="crm-record-count">{page?.total??0} promoters</span>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    <div className="table-scroll crm-table-scroll">
      <table className="data-table crm-table promoter-crm-table">
        <thead><tr>{["Created","Full Name","Mobile","City","Sponsors","Status"].map(col=>
          <th scope="col" key={col}>{col}</th>)}</tr></thead>
        <tbody>
          {loading&&!page?<tr><td colSpan={6}><p role="status" className="crm-list-empty">Loading promoters…</p></td></tr>
            :!page?.items.length?<tr><td colSpan={6}>
              <div className="crm-list-empty">
                <Icon name="users" size={29}/><h2>No promoters found</h2>
                <p>{q?"Try another search.":"Add your first promoter to begin."}</p>
                {view==="all"&&<Link href="/promoters/add" className="btn btn-primary">Add Promoter</Link>}
              </div></td></tr>
            :page.items.map(item=><tr key={item.id}>
              <td>{displayDate(item.created_at)}</td>
              <td><Link className="crm-person-link" href={"/promoters/"+item.id}>{item.full_name}</Link></td>
              <td>{item.mobile_number}</td>
              <td>{item.area_city||"—"}</td>
              <td>{item.sponsor_count}</td>
              <td><div className="crm-stage-cell">
                <span className={"status-pill "+(item.is_active?"active":"inactive")}>
                  {item.is_active?"Active":"Inactive"}</span>
                <button type="button" className="text-action crm-stage-change"
                  aria-label={(item.is_active?"Deactivate ":"Reactivate ")+item.full_name}
                  onClick={()=>setTarget(item)}>
                  {item.is_active?"Deactivate":"Reactivate"}
                </button>
              </div></td>
            </tr>)}
        </tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{page?"Showing "+(page.total?offset+1:0)+"–"+
        Math.min(offset+20,page.total)+" of "+page.total:"Loading…"}</span>
      <div className="paging-actions">
        <button className="btn btn-secondary" type="button" disabled={loading||offset===0}
          onClick={()=>setOffset(x=>Math.max(0,x-20))}>Previous</button>
        <button className="btn btn-secondary" type="button"
          disabled={loading||!page||offset+20>=page.total}
          onClick={()=>setOffset(x=>x+20)}>Next</button>
      </div>
    </div>
    {target&&<div className="crm-dialog-scrim">
      <section className="crm-dialog" role="dialog" aria-modal="true"
        aria-label="Confirm promoter status">
        <h2>{target.is_active?"Deactivate promoter?":"Reactivate promoter?"}</h2>
        <p>{target.full_name}</p>
        <p className="crm-muted">{target.is_active
          ?"Promoters with assigned sponsors must be unassigned or reassigned first."
          :"The promoter will return to the Active list."}</p>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" disabled={pending}
            onClick={()=>setTarget(null)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={pending}
            onClick={toggle}>{pending?"Saving…":"Confirm"}</button>
        </div>
      </section>
    </div>}
  </section>;
}
