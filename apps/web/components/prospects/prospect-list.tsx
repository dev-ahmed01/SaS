"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ProspectEditor } from "./prospect-editor";
import type { Prospect, ProspectPage } from "./prospects-types";
import { Icon } from "../ui/icon";

function amount(paise:number):string {
  return (paise/100).toLocaleString("en-IN",{style:"currency",currency:"INR"});
}

async function mutate(path:string, method:string, version:number):Promise<Response> {
  const session=await fetch("/api/admin/session",{cache:"no-store"});
  if(!session.ok)throw Error("Session expired. Please sign in again.");
  const {csrf_token}=await session.json();
  return fetch(path,{
    method,credentials:"same-origin",
    headers:{"X-CSRF-Token":csrf_token,"If-Match":String(version)}
  });
}

export function ProspectList({view}:{view:"inactive"|"all"}) {
  const [q,setQ]=useState("");
  const [debounced,setDebounced]=useState("");
  const [includeArchived,setIncludeArchived]=useState(false);
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [records,setRecords]=useState<ProspectPage|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [operation,setOperation]=useState(false);
  const [editing,setEditing]=useState<Prospect|null>(null);
  const modalRef=useRef<HTMLDivElement>(null);

  useEffect(()=>{
    if(!editing)return;
    const previousFocus=document.activeElement as HTMLElement | null;
    const modal=modalRef.current;
    modal?.querySelector<HTMLButtonElement>('button[aria-label="Close edit"]')?.focus();
    function handleKey(event:KeyboardEvent){
      if(event.key==="Escape"){
        event.preventDefault();
        setEditing(null);
        return;
      }
      if(event.key!=="Tab"||!modal)return;
      const elements=Array.from(modal.querySelectorAll<HTMLElement>(
        'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]'
      )).filter(node=>node.getClientRects().length>0);
      if(elements.length===0)return;
      const first=elements[0],last=elements[elements.length-1];
      if(event.shiftKey && document.activeElement===first){
        event.preventDefault();last.focus();
      }else if(!event.shiftKey && document.activeElement===last){
        event.preventDefault();first.focus();
      }
    }
    document.addEventListener("keydown",handleKey);
    return ()=>{document.removeEventListener("keydown",handleKey);previousFocus?.focus();};
  },[editing]);

  useEffect(()=>{
    const timer=setTimeout(()=>{setDebounced(q);setOffset(0);},250);
    return ()=>clearTimeout(timer);
  },[q]);
  useEffect(()=>setOffset(0),[includeArchived,view]);
  const load=useCallback(async(signal:AbortSignal)=>{
    const params=new URLSearchParams({
      limit:"20", offset:String(offset),
      q:debounced,include_archived:String(view==="all"&&includeArchived)
    });
    if(view==="inactive")params.set("status","inactive");
    const response=await fetch("/api/admin/prospects?"+params,{
      cache:"no-store",signal
    });
    if(!response.ok)throw Error("Unable to load prospects.");
    return await response.json() as ProspectPage;
  },[offset,debounced,includeArchived,view]);

  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    load(controller.signal).then(result=>{if(!controller.signal.aborted)setRecords(result);})
      .catch(err=>{if(!controller.signal.aborted)setError(err.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[load,revision]);

  async function changeArchived(prospect:Prospect) {
    if(operation)return;
    const restoring=Boolean(prospect.archived_at);
    if(!restoring && !window.confirm(
      "Archive "+prospect.full_name+"? This hides the record from normal lists but preserves its history."
    ))return;
    setOperation(true);setError("");
    try {
      const response=await mutate(
        "/api/admin/prospects/"+prospect.id+(restoring?"/restore":""),
        restoring?"POST":"DELETE",prospect.version
      );
      if(!response.ok){
        setError(response.status===409
          ?"This prospect has changed. Refresh the list before trying again."
          :"The record could not be updated. Please try again.");
        return;
      }
      setRevision(n=>n+1);
    }catch{setError("Connection problem. The change was not confirmed.");}
    finally{setOperation(false);}
  }

  return <section className="list-panel" aria-label={view==="inactive"?"Inactive Prospects":"All Prospects"}>
    <div className="list-tools prospect-tools">
      <label className="search-control"><Icon name="search" size={17}/><span className="sr-only">Search prospects</span><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search by name or number…"/></label>
      {view==="all"&&<label className="archive-toggle"><input type="checkbox" checked={includeArchived} onChange={e=>setIncludeArchived(e.target.checked)}/> Show archived</label>}
    </div>
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="table-scroll">
      <table className="data-table prospects-table">
        <thead><tr>
          <th scope="col">Name</th><th scope="col">Mobile Number</th>
          <th scope="col">Status</th><th scope="col">Actions</th>
        </tr></thead>
        <tbody>
          {loading?<tr><td colSpan={4}><div className="empty-state" role="status">Loading prospects…</div></td></tr>
          :!records || records.items.length===0?<tr><td colSpan={4}><div className="empty-state"><Icon name="users" size={30}/><h3>No prospects found</h3><p>{view==="inactive"?"Inactive prospects will appear once the payment history engine identifies two consecutive missed months.":"Try a different search or use Add Prospect to register a new contributor."}</p></div></td></tr>
          :records.items.map(record=><tr key={record.id}>
            <td><strong className="table-name">{record.full_name}</strong><span className="table-subtitle">{amount(record.monthly_contribution_paise)} / month</span></td>
            <td>{record.mobile_number}</td>
            <td><span className={"status-pill "+record.lifecycle_status}>{record.archived_at?"Archived":record.lifecycle_status==="new"?"New":record.lifecycle_status==="active"?"Active":"Inactive"}</span></td>
            <td><div className="row-actions">
              {!record.archived_at&&<button type="button" className="text-action" onClick={()=>setEditing(record)}>Edit</button>}
              <button type="button" className="text-action" disabled={operation} onClick={()=>changeArchived(record)}>{record.archived_at?"Restore":"Archive"}</button>
            </div></td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{records?("Showing "+(records.total===0?0:offset+1)+"–"+Math.min(offset+20,records.total)+" of "+records.total+" prospects"):"Waiting for records"}</span>
      <div className="paging-actions"><button className="btn btn-secondary" disabled={loading||offset===0} onClick={()=>setOffset(n=>Math.max(0,n-20))}>Previous</button><button className="btn btn-secondary" disabled={loading||!records||offset+20>=records.total} onClick={()=>setOffset(n=>n+20)}>Next</button></div>
    </div>
    {editing&&<div className="modal-scrim" role="presentation">
      <div ref={modalRef} className="edit-modal" role="dialog" aria-modal="true" aria-label={"Edit "+editing.full_name}>
        <div className="modal-topline"><span>Prospect details</span><button className="icon-button" type="button" aria-label="Close edit" onClick={()=>setEditing(null)}><Icon name="close"/></button></div>
        <ProspectEditor initial={editing} onSaved={()=>{setEditing(null);setRevision(n=>n+1);}} onCancel={()=>setEditing(null)}/>
      </div>
    </div>}
  </section>;
}
