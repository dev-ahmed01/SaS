"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CampaignResultDetails } from "./campaign-results";
import { apiGet, apiWrite, istDisplay } from "./types";
import type { Campaign } from "./types";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";

type Summary={
  campaign_id:string;run_status:"not_approved"|"approved"|"cancelled"|"completed";
  submitted_unverified:number;rejected:number;unknown:number;
  queued:number;claimed:number;suppressed_after_approval:number;
  excluded_in_review:number;last_attempt_at:string|null;
};
type Filter="all"|"completed"|"pending"|"planned";

function campaignState(item:Campaign,summary?:Summary){
  if(item.status==="cancelled"||summary?.run_status==="cancelled")return "Cancelled";
  if(summary?.run_status==="completed")return "Completed";
  if(summary?.run_status==="approved")return "Approved";
  if(item.planned_for)return "Planned";
  return "Awaiting approval";
}
function activity(item:Campaign,summary?:Summary){
  if(summary?.run_status==="completed"&&summary.last_attempt_at){
    return {label:"Last attempt",date:summary.last_attempt_at};
  }
  if(item.planned_for)return {label:"Planned for",date:item.planned_for};
  if(summary?.last_attempt_at)return {label:"Last attempt",date:summary.last_attempt_at};
  return {label:"Created",date:item.created_at};
}
export function CommunicationCampaigns({revision}:{revision:number}){
  const [items,setItems]=useState<Campaign[]>(()=>
    recentSnapshot<Campaign[]>("/api/admin/communication/campaigns")??[]);
  const [results,setResults]=useState<Record<string,Summary>>({});
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [filter,setFilter]=useState<Filter>("all");
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [reload,setReload]=useState(0);
  const [purgePreview,setPurgePreview]=useState<{
    campaign_count:number;in_flight_attempts:number;
  }|null>(null);
  const [purgeConfirmation,setPurgeConfirmation]=useState("");
  const [purgeBusy,setPurgeBusy]=useState(false);
  const [cancelling,setCancelling]=useState<string|null>(null);

  useEffect(()=>{
    const sync=()=>{
      const match=/^#campaign-([0-9a-f-]{36})$/i.exec(window.location.hash);
      setSelectedId(match?match[1]:null);
    };
    sync();window.addEventListener("hashchange",sync);
    return()=>window.removeEventListener("hashchange",sync);
  },[]);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError("");
    Promise.all([
      apiGet<Campaign[]>("/campaigns"),apiGet<Summary[]>("/campaigns/results"),
    ]).then(([rows,summaries])=>{
      if(!active)return;
      rememberSnapshot("/api/admin/communication/campaigns",rows);
      setItems(rows);
      setResults(Object.fromEntries(summaries.map(row=>[row.campaign_id,row])));
    }).catch(()=>{if(active)setError("Could not load campaigns.");})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[revision,reload]);

  async function cancelPlan(item:Campaign){
    if(cancelling||!window.confirm("Cancel this campaign plan?"))return;
    setCancelling(item.id);setError("");
    try{
      await apiWrite("/campaigns/"+item.id+"/cancel","POST",{});
      setReload(n=>n+1);
    }catch(e){setError(e instanceof Error?e.message:"Could not cancel campaign.");}
    finally{setCancelling(null);}
  }
  async function openCampaignPurge(){
    setPurgeBusy(true);setError("");
    try{
      const preview=await apiGet<{campaign_count:number;in_flight_attempts:number}>(
        "/campaigns/purge-preview");
      setPurgePreview(preview);setPurgeConfirmation("");
    }catch{setError("Could not check campaigns for deletion.");}
    finally{setPurgeBusy(false);}
  }
  async function purgeCampaigns(){
    if(!purgePreview||purgeBusy||purgeConfirmation!=="DELETE ALL CAMPAIGNS"||
      purgePreview.in_flight_attempts>0)return;
    setPurgeBusy(true);setError("");setNotice("");
    try{
      const result=await apiWrite<{deleted_campaigns:number}>(
        "/campaigns/purge-all","POST",{
          confirm:"DELETE ALL CAMPAIGNS",
          expected_campaigns:purgePreview.campaign_count,
        },
      );
      setPurgePreview(null);setPurgeConfirmation("");
      setItems([]);setResults({});
      rememberSnapshot("/api/admin/communication/campaigns",[]);
      setReload(n=>n+1);
      setNotice(result.deleted_campaigns+" campaigns deleted.");
    }catch(e){
      setError(e instanceof Error?e.message:"Could not delete campaigns.");
      setPurgePreview(null);
    }finally{setPurgeBusy(false);}
  }
  const counts={
    all:items.length,
    completed:items.filter(item=>campaignState(item,results[item.id])==="Completed").length,
    planned:items.filter(item=>campaignState(item,results[item.id])==="Planned").length,
    pending:items.filter(item=>["Approved","Awaiting approval"].includes(
      campaignState(item,results[item.id]))).length,
  };
  const visible=items.filter(item=>{
    const state=campaignState(item,results[item.id]);
    return filter==="all"||filter==="completed"&&state==="Completed"||
      filter==="planned"&&state==="Planned"||
      filter==="pending"&&["Approved","Awaiting approval"].includes(state);
  });
  if(selectedId)return <CampaignResultDetails id={selectedId}
    onBack={()=>setSelectedId(null)}/>;

  return <section className="comm-panel comm-campaigns" aria-label="Communication campaigns">
    <div className="comm-panel-header comm-history-header">
      <div><h2>Campaigns</h2>
        <p>{items.length} total · {counts.completed} completed</p></div>
      <div className="comm-review-actions">
        <button type="button" className="btn btn-secondary" disabled={loading}
          onClick={()=>setReload(v=>v+1)}>{loading?"Refreshing…":"Refresh"}</button>
        <Link className="btn btn-primary" href="/communication">New campaign</Link>
      </div>
    </div>
    <div className="comm-history-toolbar" role="group" aria-label="Filter campaigns">
      {([
        ["all","All"],["completed","Completed"],["pending","In progress"],["planned","Planned"],
      ] as [Filter,string][]).map(([key,label])=>
        <button type="button" key={key} className={"comm-history-filter"+(filter===key?" active":"")}
          aria-pressed={filter===key} onClick={()=>setFilter(key)}>
          {label} <span>{counts[key]}</span>
        </button>)}
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
    <div className="comm-campaign-list">
      {loading&&!items.length?<p role="status" className="comm-empty">Loading campaigns…</p>:
       !visible.length?<div className="comm-history-empty">
         <h3>{items.length?"No campaigns in this view":"No campaigns yet"}</h3>
         <Link href="/communication">Compose a message</Link>
       </div>:
       visible.map(item=>{
         const summary=results[item.id];
         const state=campaignState(item,summary);
         const date=activity(item,summary);
         const notSent=(summary?.excluded_in_review??0)+
           (summary?.suppressed_after_approval??0);
         return <article key={item.id} className="comm-campaign-item"
           aria-label={"Campaign "+item.title}>
           <div className="comm-campaign-item-main">
             <div className="comm-campaign-item-heading">
               <h3><Link href={"/communication/campaigns#campaign-"+item.id}
                 onClick={()=>setSelectedId(item.id)}>{item.title}</Link></h3>
               <span className={"comm-state comm-state-"+state.toLowerCase().replaceAll(" ","-")}>
                 {state}</span>
             </div>
             <p className="comm-campaign-item-meta">
               {item.channel==="whatsapp"?"WhatsApp":"Email"} ·
               {" "+item.category.replace("_"," ")} ·
               {" "+item.audience+" / "+item.segment}
             </p>
           </div>
           <div className="comm-campaign-item-time">
             <span>{date.label} (IST)</span>
             <strong>{istDisplay(date.date)}</strong>
             {item.planned_for&&state==="Completed"&&
               <small>Planned: {istDisplay(item.planned_for)}</small>}
           </div>
           <div className="comm-campaign-item-metrics" aria-label="Sending summary">
             <span><strong>{summary?.submitted_unverified??0}</strong> Submitted</span>
             <span><strong>{summary?.rejected??0}</strong> Failed</span>
             <span><strong>{notSent}</strong> Not sent</span>
           </div>
           <div className="comm-campaign-item-actions">
             <Link className="comm-campaign-open"
               href={"/communication/campaigns#campaign-"+item.id}
               onClick={()=>setSelectedId(item.id)}>View details</Link>
             {state==="Awaiting approval"||state==="Planned"?
               <button type="button" className="comm-text-button"
                 disabled={cancelling===item.id}
                 onClick={()=>void cancelPlan(item)}>Cancel plan</button>:null}
           </div>
         </article>;
       })}
    </div>
    <div className="comm-history-bottom">
      <span>Submitted = accepted by the gateway, not confirmed delivered.</span>
      <button type="button" className="comm-text-button crm-danger-btn"
        disabled={purgeBusy||!items.length} onClick={()=>void openCampaignPurge()}>
        Delete all campaigns
      </button>
    </div>
    {purgePreview&&<div className="crm-dialog-scrim" role="presentation">
      <section className="crm-dialog" role="dialog" aria-modal="true"
        aria-label="Delete all campaigns">
        <div className="crm-dialog-head"><h2>Delete all campaigns?</h2>
          <button type="button" className="text-action"
            onClick={()=>setPurgePreview(null)} disabled={purgeBusy}>Close</button></div>
        <p>This permanently removes {purgePreview.campaign_count} campaign(s) and
          their results. Prospect and payment records are retained.</p>
        {purgePreview.in_flight_attempts>0?<p className="form-error" role="alert">
          {purgePreview.in_flight_attempts} attempt(s) are in progress.
          Refresh after they finish.
        </p>:<label className="field"><span className="field-label">
          Type DELETE ALL CAMPAIGNS to confirm</span>
          <input type="text" autoComplete="off" value={purgeConfirmation}
            onChange={e=>setPurgeConfirmation(e.target.value)}/></label>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" disabled={purgeBusy}
            onClick={()=>setPurgePreview(null)}>Cancel</button>
          <button type="button" className="btn btn-primary crm-danger-btn"
            disabled={purgeBusy||purgePreview.in_flight_attempts>0||
              purgeConfirmation!=="DELETE ALL CAMPAIGNS"}
            onClick={()=>void purgeCampaigns()}>
            {purgeBusy?"Deleting…":"Delete campaigns"}
          </button>
        </div>
      </section>
    </div>}
  </section>;
}
