"use client";

import { useCallback,useEffect,useRef,useState } from "react";
import { Icon } from "../ui/icon";
import { PromoterEditor } from "./promoter-editor";
import { PromoterSponsors } from "./promoter-sponsors";
import type { Promoter,PromoterPage } from "./promoter-types";
import { csrfToken } from "./promoter-types";

export function PromoterList({view}:{view:"active"|"all"}){
  const [search,setSearch]=useState("");
  const [query,setQuery]=useState("");
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [data,setData]=useState<PromoterPage|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [pending,setPending]=useState(false);
  const [editing,setEditing]=useState<Promoter|null>(null);
  const modalRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const timer=setTimeout(()=>{setQuery(search);setOffset(0);},250);
    return ()=>clearTimeout(timer);
  },[search]);
  useEffect(()=>setOffset(0),[view]);
  const load=useCallback(async(signal:AbortSignal)=>{
    const params=new URLSearchParams({q:query,limit:"20",offset:String(offset)});
    if(view==="active")params.set("active","true");
    const response=await fetch("/api/admin/promoters?"+params,{cache:"no-store",signal});
    if(!response.ok)throw Error("Unable to load promoters.");
    return await response.json() as PromoterPage;
  },[query,offset,view]);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    load(controller.signal).then(result=>{if(!controller.signal.aborted)setData(result);})
      .catch(()=>{if(!controller.signal.aborted)setError("Unable to load promoters. Please retry.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[load,revision]);

  useEffect(()=>{
    if(!editing)return;
    const focused=document.activeElement as HTMLElement|null;
    const dialog=modalRef.current;
    dialog?.querySelector<HTMLButtonElement>('button[aria-label="Close edit"]')?.focus();
    const onKey=(e:KeyboardEvent)=>{
      if(e.key==="Escape"){e.preventDefault();setEditing(null);return;}
      if(e.key!=="Tab"||!dialog)return;
      const els=Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),a[href]'
      )).filter(x=>x.getClientRects().length>0);
      if(!els.length)return;
      if(e.shiftKey&&document.activeElement===els[0]){e.preventDefault();els[els.length-1].focus();}
      else if(!e.shiftKey&&document.activeElement===els[els.length-1]){e.preventDefault();els[0].focus();}
    };
    document.addEventListener("keydown",onKey);
    return ()=>{document.removeEventListener("keydown",onKey);focused?.focus();};
  },[editing]);

  async function toggle(item:Promoter){
    if(pending)return;
    if(item.is_active && item.sponsor_count>0){
      setError("Reassign or unassign all linked sponsors before marking this promoter inactive.");
      return;
    }
    if(item.is_active && !window.confirm("Mark "+item.full_name+" as inactive?"))return;
    setPending(true);setError("");
    try{
      const token=await csrfToken();
      const response=await fetch("/api/admin/promoters/"+item.id,{
        method:"PATCH",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":token},
        body:JSON.stringify({version:item.version,is_active:!item.is_active}),
      });
      if(!response.ok){
        setError(response.status===409?"This promoter has changed. Refresh and retry.":"Unable to update promoter status.");
        return;
      }
      setRevision(n=>n+1);
    }catch{setError("Connection problem. Status change not confirmed.");}
    finally{setPending(false);}
  }

  return <section className="list-panel" aria-label={view==="active"?"Active Promoters":"All Promoters"}>
    <div className="list-tools">
      <label className="search-control">
        <Icon name="search" size={17}/><span className="sr-only">Search promoters</span>
        <input placeholder="Search by name, number or area…" value={search} onChange={e=>setSearch(e.target.value)}/>
      </label>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th scope="col">Name</th><th scope="col">Phone number</th>
          <th scope="col">Area / City</th><th scope="col">Sponsors</th>
          <th scope="col">Status</th><th scope="col">Actions</th></tr></thead>
        <tbody>
          {loading?<tr><td colSpan={6}><div className="empty-state" role="status">Loading promoters…</div></td></tr>
          :!data?.items.length?<tr><td colSpan={6}><div className="empty-state"><Icon name="users" size={29}/><h3>No promoters found</h3><p>{view==="active"?"Active promoters appear here after registration.":"Try another search or add a promoter."}</p></div></td></tr>
          :data.items.map(p=><tr key={p.id}>
            <td><strong className="table-name">{p.full_name}</strong></td>
            <td>{p.mobile_number}</td><td>{p.area_city}</td>
            <td>{p.sponsor_count}</td>
            <td><span className={"status-pill "+(p.is_active?"active":"inactive")}>{p.is_active?"Active":"Inactive"}</span></td>
            <td><div className="row-actions">
              <button type="button" className="text-action" onClick={()=>setEditing(p)}>Edit</button>
              <button type="button" disabled={pending} className="text-action" onClick={()=>toggle(p)}>{p.is_active?"Deactivate":"Reactivate"}</button>
            </div></td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{data?"Showing "+(data.total===0?0:offset+1)+"–"+Math.min(offset+20,data.total)+" of "+data.total+" promoters":"Waiting for records"}</span>
      <div className="paging-actions">
        <button className="btn btn-secondary" disabled={loading||offset===0} onClick={()=>setOffset(o=>Math.max(0,o-20))}>Previous</button>
        <button className="btn btn-secondary" disabled={loading||!data||offset+20>=data.total} onClick={()=>setOffset(o=>o+20)}>Next</button>
      </div>
    </div>
    {editing&&<div className="modal-scrim" role="presentation">
      <div ref={modalRef} className="edit-modal" role="dialog" aria-modal="true" aria-label={"Edit "+editing.full_name}>
        <div className="modal-topline">
          <span>Promoter details</span>
          <button type="button" className="icon-button" aria-label="Close edit" onClick={()=>setEditing(null)}><Icon name="close"/></button>
        </div>
        <PromoterEditor key={editing.id+":"+editing.version} initial={editing} onCancel={()=>setEditing(null)}
          onSaved={()=>{setEditing(null);setRevision(n=>n+1);}}/>
        <PromoterSponsors promoter={editing} onChanged={async()=>{
           setRevision(n=>n+1);
           try{
             const response=await fetch("/api/admin/promoters/"+editing.id,{cache:"no-store"});
             if(!response.ok)throw Error("refresh failed");
             setEditing(await response.json() as Promoter);
           }catch{
             setEditing(null);
             setError("Assignment saved. Reopen the promoter to refresh details.");
           }
         }}/>
      </div>
    </div>}
  </section>;
}
