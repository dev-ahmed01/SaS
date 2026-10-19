"use client";

import { useEffect, useState } from "react";
import { apiGet, apiWrite, istDisplay } from "./types";
import type { Campaign } from "./types";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";

type RecipientCheck={
  id:string;campaign_id:string;eligible_count:number;suppressed_count:number;
  evaluated_at:string;delivery_activated:false;
};

export function CommunicationCampaigns({revision}:{revision:number}){
  const [items,setItems]=useState<Campaign[]>(()=>recentSnapshot<Campaign[]>("/api/admin/communication/campaigns")??[]);
  const [loading,setLoading]=useState(()=>!recentSnapshot<Campaign[]>("/api/admin/communication/campaigns"));
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState("");
  const [reload,setReload]=useState(0);
  const [reviewId,setReviewId]=useState<string|null>(null);
  const [check,setCheck]=useState<RecipientCheck|null>(null);
  const [checking,setChecking]=useState(false);
  const [reviewError,setReviewError]=useState("");
  useEffect(()=>{
    const cached=recentSnapshot<Campaign[]>("/api/admin/communication/campaigns");
    if(cached)setItems(cached);
    setLoading(!cached);
    apiGet<Campaign[]>("/campaigns").then(rows=>{
      rememberSnapshot("/api/admin/communication/campaigns",rows);setItems(rows);
    })
      .catch(()=>setError("Could not load saved campaigns."))
      .finally(()=>setLoading(false));
  },[revision,reload]);
  async function openReview(item:Campaign){
    if(reviewId===item.id){setReviewId(null);setCheck(null);return;}
    setReviewId(item.id);setCheck(null);setReviewError("");
    setChecking(true);
    try{
      const history=await apiGet<RecipientCheck[]>(
        "/campaigns/"+item.id+"/preparations"
      );
      setCheck(history[0]??null);
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
  return <section className="comm-panel" aria-label="Communication campaigns">
    <div className="comm-panel-header"><div><h2>Campaigns</h2>
      <p>Drafts and plans across all audiences.</p></div>
      <button type="button" className="btn btn-secondary" onClick={()=>setReload(x=>x+1)}>
        Refresh</button>
    </div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="form-success" role="status">{notice}</p>}
    <div className="comm-campaign-table-scroll"><table className="data-table comm-campaign-table">
      <thead><tr>{["Campaign","Channel","Audience","At draft","Planned IST","Status","Action"].map(h=>
        <th key={h} scope="col">{h}</th>)}</tr></thead>
      <tbody>{loading&&items.length===0?<tr><td colSpan={7}>Loading campaigns…</td></tr>:!items.length?
        <tr><td colSpan={7} className="comm-empty">No saved campaigns yet. Start in Compose.</td></tr>:
        items.map(item=><tr key={item.id}>
          <td><div className="comm-campaign-title"><strong>{item.title}</strong>
            <span>{item.category.replace("_"," ")}</span></div></td>
          <td>{item.channel==="whatsapp"?"WhatsApp":"Email"}</td>
          <td>{item.audience} · {item.segment}</td>
          <td>{item.eligible_snapshot}/{item.candidate_snapshot}</td>
          <td>{item.planned_for?istDisplay(item.planned_for):"—"}</td>
          <td><span className={"status-pill "+(item.status==="cancelled"?"inactive":"scheduled")}>
            {item.status==="scheduled"?"Planned":item.status==="cancelled"?"Cancelled":"Draft"}
          </span></td>
          <td><div className="comm-review-actions">
            {item.status==="cancelled"?"—":<>
              <button type="button" className="comm-text-button"
                aria-expanded={reviewId===item.id}
                onClick={()=>openReview(item)}>{reviewId===item.id?"Close review":"Review"}</button>
              <button type="button" className="comm-text-button"
                disabled={busy===item.id} onClick={()=>cancel(item)}>Cancel</button>
            </>}
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
        {check&&<div className="comm-review-counts" aria-label="Previous recipient check">
          <span><strong>{check.eligible_count}</strong> Eligible</span>
          <span><strong>{check.suppressed_count}</strong> Excluded</span>
          <span>{istDisplay(check.evaluated_at)}</span>
        </div>}
        {reviewError&&<p className="form-error" role="alert">{reviewError}</p>}
        {!check&&!checking&&!reviewError&&<p className="comm-muted">
          Not checked yet.</p>}
        <div className="comm-review-footer">
          <span className="comm-muted">Simulation only · no messages sent.</span>
          <button type="button" className="btn btn-primary"
            disabled={checking} onClick={()=>{
              const item=items.find(row=>row.id===reviewId);
              if(item)void runCheck(item);
            }}>{checking?"Checking…":"Check recipients"}</button>
        </div>
      </section>}
    <p className="comm-muted comm-history-footnote">
      Planned dates are saved in IST, but plans are not automatically sent.
      Provider delivery must be configured and explicitly activated separately.
    </p>
  </section>;
}
