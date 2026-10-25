"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CampaignResultDetails } from "./campaign-results";
import { apiGet, apiWrite, istDisplay } from "./types";
import type { Campaign } from "./types";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";

type CampaignSummary={
  campaign_id:string;run_status:"not_approved"|"approved"|"cancelled"|"completed";
  planned:number;submitted_unverified:number;rejected:number;unknown:number;
  queued:number;claimed:number;suppressed_after_approval:number;
  excluded_in_review:number;
  delivered:number|null;read:number|null;
};
type SaasytoRun={
  id:string;campaign_id:string;status:"approved"|"cancelled"|"completed";
  due_at:string;eligible_count:number;suppressed_count:number;
  queued:number;claimed:number;accepted_unverified:number;
  rejected:number;unknown:number;suppressed_after_approval:number;notice:string;
};
type SaasytoStatus={
  provider:string;transport:string;delivery_enabled:boolean;
  local_test_mode?:boolean;activation_cutoff?:string|null;
  sender_approved:boolean;credentials_configured:boolean;
  webhook_verified:boolean;connection_tested:boolean;notice:string;
};
type RecipientCheck={
  id:string;campaign_id:string;eligible_count:number;suppressed_count:number;
  evaluated_at:string;exclusion_reasons?:Record<string,number>;
  delivery_activated:false;
};

const reasonLabels:Record<string,string>={
  missing_address:"Missing WhatsApp/mobile number",
  opted_out:"Recipient opted out",
  inactive_reminder:"Inactive for reminders",
  no_email_consent:"No documented email permission",
  no_whatsapp_consent:"WhatsApp permission checkbox is off",
  no_general_consent:"No recorded Communication opt-in with evidence",
  duplicate_address:"Duplicate WhatsApp number in the audience",
};
export function CommunicationCampaigns({revision}:{revision:number}){
  const [items,setItems]=useState<Campaign[]>(()=>recentSnapshot<Campaign[]>("/api/admin/communication/campaigns")??[]);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [loading,setLoading]=useState(()=>!recentSnapshot<Campaign[]>("/api/admin/communication/campaigns"));
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState("");
  const [reload,setReload]=useState(0);
  const [provider,setProvider]=useState<SaasytoStatus|null>(null);
  const [results,setResults]=useState<Record<string,CampaignSummary>>({});
  const [run,setRun]=useState<SaasytoRun|null>(null);
  const [runBusy,setRunBusy]=useState(false);
  const [reviewId,setReviewId]=useState<string|null>(null);
  const [check,setCheck]=useState<RecipientCheck|null>(null);
  const [checking,setChecking]=useState(false);
  const [reviewError,setReviewError]=useState("");
  useEffect(()=>{
    // A fragment is never forwarded to the server. Deep-link to a detailed
    // campaign view without conflicting with the existing dynamic module route.
    const sync=()=>{
      const match=/^#campaign-([0-9a-f-]{36})$/i.exec(window.location.hash);
      setSelectedId(match?match[1]:null);
    };
    sync();
    window.addEventListener("hashchange",sync);
    return ()=>window.removeEventListener("hashchange",sync);
  },[]);
  useEffect(()=>{
    const cached=recentSnapshot<Campaign[]>("/api/admin/communication/campaigns");
    if(cached)setItems(cached);
    setLoading(!cached);
    Promise.all([
      apiGet<Campaign[]>("/campaigns"),apiGet<CampaignSummary[]>("/campaigns/results"),
    ]).then(([rows,summaries])=>{
      rememberSnapshot("/api/admin/communication/campaigns",rows);setItems(rows);
      setResults(Object.fromEntries(summaries.map(item=>[item.campaign_id,item])));
    }).catch(()=>setError("Could not load current campaign results."))
      .finally(()=>setLoading(false));
  },[revision,reload]);
  useEffect(()=>{
    let mounted=true;
    apiGet<SaasytoStatus>("/provider/saasyto")
      .then(state=>{if(mounted)setProvider(state);})
      .catch(()=>{if(mounted)setProvider(null);});
    return()=>{mounted=false;};
  },[revision,reload]);
  async function openReview(item:Campaign){
    if(reviewId===item.id){setReviewId(null);setCheck(null);return;}
    setReviewId(item.id);setCheck(null);setRun(null);setReviewError("");
    setChecking(true);
    try{
      const history=await apiGet<RecipientCheck[]>(
        "/campaigns/"+item.id+"/preparations"
      );
      setCheck(history[0]??null);
      setRun(await apiGet<SaasytoRun|null>("/campaigns/"+item.id+"/saasyto"));
    }catch{
      setReviewError("Recipient checks unavailable.");
    }finally{setChecking(false);}
  }
  async function runCheck(item:Campaign){
    if(checking)return;
    setChecking(true);setReviewError("");
    try{
      const result=await apiWrite<RecipientCheck>(
        "/campaigns/"+item.id+"/preparations","POST",{
          request_id:crypto.randomUUID(),simulation_only:true,
        }
      );
      setCheck(result);
    }catch(e){
      setReviewError(e instanceof Error?e.message:"Recipient check failed.");
    }finally{setChecking(false);}
  }
  async function approve(item:Campaign){
    if(!check||run||runBusy||!provider?.delivery_enabled)return;
    if(!window.confirm(
      "Approve Saasyto delivery to "+check.eligible_count+
      " eligible recipient(s)? This authorizes a one-attempt-only queue. "+
      "Gateway acceptance is not confirmed WhatsApp delivery."
    ))return;
    setRunBusy(true);setReviewError("");
    try{
      const result=await apiWrite<SaasytoRun>(
        "/campaigns/"+item.id+"/saasyto","POST",{
          preparation_id:check.id,expected_eligible:check.eligible_count,
          confirm_send:true,
        }
      );
      setRun(result);
      setReload(x=>x+1);
      setNotice(provider?.local_test_mode
        ? "Approved for local sending. The localhost worker must be running to submit the message."
        : "Campaign approved for the private delivery runner; messages are not automatically sent from this browser.");
    }catch(e){setReviewError(e instanceof Error?e.message:"Approval was not confirmed.");}
    finally{setRunBusy(false);}
  }
  async function cancelRun(item:Campaign){
    if(!run||runBusy||!window.confirm(
      "Cancel all not-yet-claimed Saasyto messages? Messages already submitted cannot be recalled."
    ))return;
    setRunBusy(true);setReviewError("");
    try{
      setRun(await apiWrite<SaasytoRun>(
        "/campaigns/"+item.id+"/saasyto/cancel","POST",{}
      ));
    }catch(e){setReviewError(e instanceof Error?e.message:"Unable to cancel dispatch.");}
    finally{setRunBusy(false);}
  }
  async function cancel(item:Campaign){
    if(!window.confirm("Cancel this communication plan? It will remain in the audit log."))return;
    setBusy(item.id);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+item.id+"/cancel","POST",{});
      setNotice("Campaign plan cancelled. No messages were dispatched.");
      setReload(x=>x+1);
    }catch(e){setError(e instanceof Error?e.message:"Could not cancel.");}
    finally{setBusy("");}
  }
  if(selectedId)return <CampaignResultDetails id={selectedId}/>;
  return <section className="comm-panel" aria-label="Communication campaigns">
    <div className="comm-panel-header"><div><h2>Campaigns</h2>
      <p>Open any campaign to see its recipient checks, failed submissions and
        sending outcomes.</p></div>
      <button type="button" className="btn btn-secondary" onClick={()=>setReload(x=>x+1)}>
        Refresh</button>
    </div>
    <div className="comm-provider-status" role="status">
      <strong>WhatsApp delivery · Saasyto</strong>
      <span>{provider
        ? provider.delivery_enabled
          ? provider.local_test_mode
            ? "Local test · one permitted recipient · delivery callbacks unverified"
            : "Provider configuration enabled · delivery callbacks unverified"
          : "Not connected for sending · campaigns remain drafts or plans"
        : "Provider configuration not verified"}
      </span>
      <small>{provider?.notice??"No WhatsApp message is sent from this campaign screen."}</small>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
    <div className="comm-campaign-table-scroll"><table className="data-table comm-campaign-table">
      <thead><tr>{["Campaign","Audience","Planned IST","Status","Submitted","Rejected","Not sent","Read","Details"].map(h=>
        <th key={h} scope="col">{h}</th>)}</tr></thead>
      <tbody>{loading&&items.length===0?<tr><td colSpan={9}>Loading campaigns…</td></tr>:!items.length?
        <tr><td colSpan={9} className="comm-empty">No campaigns yet. Start in Compose.</td></tr>:
        items.map(item=><tr key={item.id}>
          <td><div className="comm-campaign-title">
            <strong><Link href={"/communication/campaigns#campaign-"+item.id}>{item.title}</Link></strong>
            <span>{item.channel==="whatsapp"?"WhatsApp":"Email"} ·
              {" "+item.category.replace("_"," ")}</span></div></td>
          <td>{item.audience} · {item.segment}</td>
          <td>{item.planned_for?istDisplay(item.planned_for):"Awaiting approval"}</td>
          <td><span className={"status-pill "+(item.status==="cancelled"?"inactive":"scheduled")}>
            {item.status==="cancelled"?"Cancelled":
              results[item.id]?.run_status==="completed"?"Completed":
              results[item.id]?.run_status==="approved"?"Approved":
              item.status==="scheduled"?"Planned":"Awaiting approval"}
          </span></td>
          <td>{results[item.id]?.submitted_unverified??0}</td>
          <td>{results[item.id]?.rejected??0}</td>
          <td>{results[item.id]
            ?results[item.id].suppressed_after_approval+results[item.id].excluded_in_review
            :0}</td>
          <td>{results[item.id]?.read??"Unavailable"}</td>
          <td className="comm-sticky-actions"><div className="comm-review-actions">
            <Link className="comm-action-primary"
              href={"/communication/campaigns#campaign-"+item.id}>
              View results</Link>
            {item.status!=="cancelled"&&
              results[item.id]?.run_status!=="completed"&&
              results[item.id]?.run_status!=="approved"&&
              <button type="button" className="comm-text-button"
                disabled={busy===item.id} onClick={()=>cancel(item)}>Cancel plan</button>}
          </div></td>
        </tr>)}</tbody>
    </table></div>
    {reviewId&&items.some(item=>item.id===reviewId&&item.status!=="cancelled")&&
      <section className="comm-recipient-review" aria-label="Recipient review">
        <div className="comm-review-heading">
          <h3>Recipient check</h3>
          <button className="btn btn-secondary" type="button"
            onClick={()=>setReviewId(null)}>Close</button>
        </div>
        {checking&&!check?<p role="status">Checking…</p>:null}
        {provider?.activation_cutoff&&
          items.some(item=>item.id===reviewId&&new Date(item.created_at).getTime()<
            new Date(provider.activation_cutoff as string).getTime())&&
          <p className="form-error" role="status">
            This campaign was created before WhatsApp activation. Create a new
            campaign in Compose after activation; older drafts cannot be approved.
          </p>}
        {check?.exclusion_reasons&&Object.keys(check.exclusion_reasons).length>0&&
          <div className="comm-provider-status" role="status">
            <strong>Why recipients were excluded</strong>
            <ul>{Object.entries(check.exclusion_reasons).map(([reason,count])=>
              <li key={reason}>{reasonLabels[reason]??reason.replaceAll("_"," ")}: {count}</li>
            )}</ul>
            <small>To update a contact's permission, open their Prospect or Promoter
              details and select Communication permissions. Only attest opt-in if
              the recipient explicitly authorized WhatsApp messages.</small>
          </div>}
        {check&&<div className="comm-review-counts" aria-label="Previous recipient check">
          <span><strong>{check.eligible_count}</strong> Eligible</span>
          <span><strong>{check.suppressed_count}</strong> Excluded</span>
          <span>{istDisplay(check.evaluated_at)}</span>
        </div>}
        {run&&<div className="comm-provider-status" aria-label="Saasyto dispatch results">
          <strong>Saasyto · {run.status}</strong>
          <span>Queued {run.queued} · Accepted by gateway {run.accepted_unverified} ·
            Unknown {run.unknown} · Rejected {run.rejected} ·
            Excluded {run.suppressed_after_approval}</span>
          <small>Scheduled {istDisplay(run.due_at)}. {run.notice}</small>
        </div>}
        {run&&<button className="btn btn-secondary" type="button"
          disabled={runBusy} onClick={()=>{
            void apiGet<SaasytoRun>(
              "/campaigns/"+run.campaign_id+"/saasyto"
            ).then(result=>setRun(result))
              .catch(()=>setReviewError("Unable to refresh the attempt status."));
          }}>Refresh delivery attempts</button>}
        {reviewError&&<p className="form-error" role="alert">{reviewError}</p>}
        {!check&&!checking&&!reviewError&&<p className="comm-muted">
          Not checked yet.</p>}
        <div className="comm-review-footer">
          <span className="comm-muted">{run
            ? "Messages are queued only after approval."
            : "Recipient check is a preview; no messages sent."}</span>
          {run?.status==="approved"&&<button className="btn btn-secondary"
            type="button" disabled={runBusy} onClick={()=>{
              const item=items.find(row=>row.id===reviewId);
              if(item)void cancelRun(item);
            }}>{runBusy?"Working…":"Stop pending sends"}</button>}
          {!run&&check&&provider?.delivery_enabled&&<button
            className="btn btn-primary" type="button" disabled={
              checking||runBusy||!check.eligible_count||
              Boolean(provider?.activation_cutoff&&items.some(item=>
                item.id===reviewId&&new Date(item.created_at).getTime()<
                  new Date(provider.activation_cutoff as string).getTime()))
            } onClick={()=>{
              const item=items.find(row=>row.id===reviewId);
              if(item)void approve(item);
            }}>{runBusy?"Approving…":"Approve WhatsApp delivery"}</button>}
          <button type="button" className="btn btn-primary"
            disabled={checking||Boolean(run)} onClick={()=>{
              const item=items.find(row=>row.id===reviewId);
              if(item)void runCheck(item);
            }}>{checking?"Checking…":"Check recipients"}</button>
        </div>
      </section>}
    <p className="comm-muted comm-history-footnote">
      Submitted means accepted by Saasyto, not delivered or read. "Not sent" above
      includes the latest recipient-check exclusions plus people suppressed
      after approval. These categories are explained individually in each
      campaign's detailed results. Planned dates use IST.
      Creating a campaign never sends WhatsApp messages.
      An approved campaign requires the private dispatch worker. Local pilots
      can send only to the number explicitly permitted in API settings.
    </p>
  </section>;
}
