"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiWrite, istDisplay } from "./types";

type Status="not_approved"|"approved"|"cancelled"|"completed";
type Summary={
  campaign_id:string;run_status:Status;planned:number;
  submitted_unverified:number;rejected:number;unknown:number;
  last_attempt_at:string|null;
  queued:number;claimed:number;suppressed_after_approval:number;
  excluded_in_review:number;
  delivered:number|null;read:number|null;
};
type Recipient={
  recipient_kind:"prospect"|"promoter";recipient_id:string;
  name:string;phone:string;status:string;reason:string|null;
  finished_at:string|null;
};
type CampaignDetails={
  campaign_id:string;title:string;audience:string;segment:string;category:string;
  channel:string;planned_for:string|null;created_at:string;
  summary:Summary;latest_review_at:string|null;
  page_offset:number;page_limit:number;
  eligible_in_review:number;excluded_in_review:number;
  excluded_reasons:Record<string,number>;
  recipients:Recipient[];eligible_recipients:Recipient[];
  excluded_recipients:Recipient[];
  delivery_notice:string;
};
type Review={
  id:string;eligible_count:number;suppressed_count:number;
  evaluated_at:string;exclusion_reasons?:Record<string,number>;
};
type DeliveryRun={
  id:string;status:Status;queued:number;eligible_count:number;
  accepted_unverified:number;rejected:number;unknown:number;suppressed_after_approval:number;
};
type Provider={
  delivery_enabled:boolean;local_test_mode?:boolean;local_dynamic_mode?:boolean;
  activation_cutoff?:string|null;
};
type Readiness={
  ready:boolean;code:string;message:string;eligible_count:number;
  local_test_mode:boolean;permitted_phone:string|null;permitted_phones?:string[];
  max_recipients?:number;
};
const reasons:Record<string,string>={
  no_general_consent:"General-message permission not recorded",
  no_whatsapp_consent:"WhatsApp permission not recorded",
  no_email_consent:"No documented email permission",
  missing_address:"No contact number",
  opted_out:"Contact opted out",
  inactive_reminder:"Inactive contact cannot receive reminders",
  duplicate_address:"Duplicate contact number",
  campaign_cancelled:"Campaign cancelled before submission",
  consent_or_status_changed:"Consent, status or phone changed before sending",
  rejected:"Saasyto rejected the submission",
  unknown:"Sending result unverified",
  provider_rejected:"Saasyto rejected the request",
  provider_http_error:"Saasyto returned an HTTP error",
  unverified_provider_reply:"Saasyto response did not confirm acceptance",
  network_error:"Could not verify Saasyto response",
  provider_timeout:"Saasyto did not answer in time",
};
const statuses:Record<string,string>={
  queued:"Queued — not submitted",
  claimed:"Claimed — outcome pending/uncertain",
  accepted_unverified:"Accepted by Saasyto · delivery unconfirmed",
  rejected:"Rejected by Saasyto",
  unknown:"Outcome unverified",
  suppressed:"Not sent",
  excluded:"Not eligible at recipient check",
  eligible_in_review:"Eligible · not yet sent",
};
function Metric({name,value,help}:{
  name:string;value:number|string;help?:string;
}){
  return <div className="crm-summary-tile">
    <span className="crm-muted">{name}</span>
    <strong>{value}</strong>
    {help&&<small className="comm-muted">{help}</small>}
  </div>;
}
function RecipientTable({title,rows}:{
  title:string;rows:Recipient[];
}){
  return <section className="comm-recipient-review comm-result-people"
    role="region" aria-label={title}>
    <div className="comm-review-heading"><h3>{title}</h3>
      <span className="comm-muted">{rows.length}</span></div>
    {rows.length===0?<p className="comm-muted">None</p>:
      <ul className="comm-result-list">{rows.map(row=>
        <li key={row.recipient_kind+row.recipient_id} className="comm-result-person">
          <div className="comm-result-person-main">
            <Link href={row.recipient_kind==="prospect"
              ?"/prospects/"+row.recipient_id:"/promoters/"+row.recipient_id}>
              {row.name}</Link>
            <small>{row.phone}</small>
          </div>
          <div className="comm-result-person-outcome">
            <strong>{statuses[row.status]??row.status}</strong>
            {(row.reason||row.finished_at)&&<small>{
              row.reason?(reasons[row.reason]??row.reason.replaceAll("_"," ")):
              row.finished_at?istDisplay(row.finished_at):""}</small>}
          </div>
        </li>)}</ul>}
  </section>;
}

export function CampaignResultDetails({id,onBack}:{
  id:string;onBack?:()=>void;
}){
  const [details,setDetails]=useState<CampaignDetails|null>(null);
  const [review,setReview]=useState<Review|null>(null);
  const [run,setRun]=useState<DeliveryRun|null>(null);
  const [provider,setProvider]=useState<Provider|null>(null);
  const [readiness,setReadiness]=useState<Readiness|null>(null);
  const [loading,setLoading]=useState(true);
  const [offset,setOffset]=useState(0);
  const pageSize=100;
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [activeTab,setActiveTab]=useState<"results"|"review"|null>(null);
  const refresh=useCallback(async()=>{
    // Results must remain visible even if optional provider/readiness APIs
    // cannot be reached. These read failures never authorize delivery.
    const result=await apiGet<CampaignDetails>(
      "/campaigns/"+id+"/results?offset="+offset+"&limit="+pageSize
    );
    setDetails(result);
    const [checks,dispatch,availability,approvalCheck]=await Promise.allSettled([
      apiGet<Review[]>("/campaigns/"+id+"/preparations"),
      apiGet<DeliveryRun|null>("/campaigns/"+id+"/saasyto"),
      apiGet<Provider>("/provider/saasyto"),
      apiGet<Readiness>("/campaigns/"+id+"/saasyto/readiness"),
    ]);
    setReview(checks.status==="fulfilled"?(checks.value[0]??null):null);
    setRun(dispatch.status==="fulfilled"?dispatch.value:null);
    setProvider(availability.status==="fulfilled"?availability.value:null);
    setReadiness(approvalCheck.status==="fulfilled"?approvalCheck.value:null);
    if(checks.status==="rejected"||dispatch.status==="rejected"||
      availability.status==="rejected"||approvalCheck.status==="rejected"){
      setNotice("Campaign results loaded, but some delivery settings are unavailable. "+
        "Live approval is disabled until those settings can be verified.");
    }
  },[id,offset]);
  useEffect(()=>{
    let active=true;
    setLoading(true);
    refresh().catch(()=>{if(active)setError("Campaign results could not be loaded.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[refresh]);
  useEffect(()=>{
    // Approved campaigns are processed by a separate private worker.
    // Poll read-only status while queued, without ever initiating a send.
    if(run?.status!=="approved")return;
    const timer=setInterval(()=>{
      if(document.visibilityState==="visible"){
        void refresh().catch(()=>setError("Could not refresh sending results."));
      }
    },15000);
    return ()=>clearInterval(timer);
  },[run?.status,refresh]);

  async function checkRecipients(){
    if(busy)return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/preparations","POST",{
        request_id:crypto.randomUUID(),simulation_only:true,
      });
      await refresh();setNotice("Recipient check updated. No messages were sent.");
    }catch(e){setError(e instanceof Error?e.message:"Could not check recipients.");}
    finally{setBusy(false);}
  }
  const localImmediate=Boolean(provider?.local_test_mode&&!details?.planned_for);
  const localLimit=readiness?.max_recipients??readiness?.permitted_phones?.length??1;
  const futurePlan=Boolean(details?.planned_for&&
    new Date(details.planned_for).getTime()>Date.now());
  async function approve(){
    if(busy||!review||!readiness?.ready||!provider?.delivery_enabled||
      review.eligible_count<1||run)return;
    const immediate=localImmediate;
    if(!window.confirm(immediate
      ? "Send "+review.eligible_count+" WhatsApp message(s) now to the authorized test contacts? "+
        "The request will reach Saasyto immediately. Gateway acceptance is not delivery."
      : "Approve "+review.eligible_count+
        " eligible recipient(s)? Messages will be queued for the private sender. "+
        "Gateway acceptance does not confirm delivery."))return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/saasyto","POST",{
        preparation_id:review.id,expected_eligible:review.eligible_count,
        confirm_send:true,
      });
      if(immediate){
        try{
          const attempt=await apiWrite<DeliveryRun>(
            "/campaigns/"+id+"/saasyto/send-now","POST",{}
          );
          await refresh();
          setNotice(attempt.accepted_unverified+" accepted by Saasyto · "+
            attempt.rejected+" rejected · "+attempt.unknown+" unknown · "+
            attempt.suppressed_after_approval+" suppressed. Check each WhatsApp; "+
            "acceptance is not delivery.");
        }catch{
          await refresh();
          setError("Approved, but immediate submission could not be verified. "+
            "Review results before taking another action. Do not resend this campaign.");
        }
      }else{
        await refresh();
        setNotice("Approved and queued. The private sending worker must be running "+
          "for the message to reach Saasyto when due.");
      }
    }catch(e){setError(e instanceof Error?e.message:"Unable to approve campaign.");}
    finally{setBusy(false);}
  }
  async function sendPendingLocal(){
    if(busy||!provider?.local_test_mode||!provider.delivery_enabled||
      !run||run.status!=="approved"||run.queued<1||run.queued>localLimit||futurePlan)return;
    if(!window.confirm("Submit "+run.queued+" pending WhatsApp message(s) now? "+
      "This cannot be undone and will never be automatically retried."))return;
    setBusy(true);setError("");setNotice("");
    try{
      const attempt=await apiWrite<DeliveryRun>(
        "/campaigns/"+id+"/saasyto/send-now","POST",{}
      );
      await refresh();
      setNotice(attempt.accepted_unverified+" accepted by Saasyto · "+
        attempt.rejected+" rejected · "+attempt.unknown+" unknown. "+
        "Check the per-recipient outcomes; acceptance is not delivery.");
    }catch{
      await refresh();
      setError("Could not verify submission. Check the recipient attempt status; "+
        "do not automatically send again.");
    }finally{setBusy(false);}
  }
  async function cancel(){
    if(busy||!run||run.status!=="approved"||
      !window.confirm("Stop not-yet-submitted messages? Already submitted messages cannot be recalled."))
      return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/saasyto/cancel","POST",{});
      await refresh();setNotice("Pending submissions cancelled.");
    }catch(e){setError(e instanceof Error?e.message:"Unable to stop pending sends.");}
    finally{setBusy(false);}
  }
  const older=Boolean(
    provider?.activation_cutoff&&details&&
    new Date(details.created_at).getTime()<new Date(provider.activation_cutoff).getTime()
  );
  const s=details?.summary;
  const completed=s?.run_status==="completed";
  const shownTab=activeTab??(completed?"results":"review");
  const pageTotal=shownTab==="results"?(s?.planned??0):Math.max(
    details?.eligible_in_review??0, details?.excluded_in_review??0
  );
  return <section className="comm-panel comm-detail-page" aria-label="Campaign results detail">
    <div className="comm-panel-header comm-detail-header">
      <div>
        <Link href="/communication/campaigns" className="back-link" onClick={onBack}>
          All campaigns
        </Link>
        <h2>{details?.title??"Campaign details"}</h2>
        {details&&<p>
          {details.channel==="whatsapp"?"WhatsApp":"Email"} ·
          {" "+details.category.replace("_"," ")} ·
          {" "+details.audience+" / "+details.segment}
        </p>}
      </div>
      <div className="comm-review-actions">
        <button type="button" className="btn btn-secondary" disabled={busy||loading}
          onClick={()=>{setError("");void refresh().catch(()=>setError("Could not refresh results."));}}>
          Refresh
        </button>
        <Link className="btn btn-primary" href="/communication">New campaign</Link>
      </div>
    </div>
    {loading&&!details&&<p role="status">Loading campaign…</p>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    {notice&&<p role="status" className="form-success">{notice}</p>}
    {details&&s&&<>
      <div className="comm-detail-overview">
        <div className="comm-detail-overview-title">
          <span className={"comm-state comm-state-"+s.run_status.replaceAll("_","-")}>
            {s.run_status==="not_approved"?"Awaiting approval":
              s.run_status==="approved"?"Approved":
              s.run_status==="completed"?"Completed":"Cancelled"}
          </span>
          <span className="comm-detail-trust">Delivery/read unverified</span>
        </div>
        <div className="comm-detail-dates">
          <div><span>Created</span><strong>{istDisplay(details.created_at)}</strong></div>
          {details.planned_for&&<div><span>Planned</span>
            <strong>{istDisplay(details.planned_for)}</strong></div>}
          {s.last_attempt_at&&<div><span>Last attempt</span>
            <strong>{istDisplay(s.last_attempt_at)}</strong></div>}
        </div>
      </div>
      <div className="comm-result-stats">
        <Metric name="Submitted" value={s.submitted_unverified}/>
        <Metric name="Failed" value={s.rejected}/>
        <Metric name="Not sent" value={s.suppressed_after_approval+s.excluded_in_review}/>
        <Metric name="Pending / unknown" value={s.queued+s.claimed+s.unknown}/>
      </div>
      {older&&!run&&<p role="alert" className="form-error">
        This campaign predates sending activation. Create a new campaign.
      </p>}
      {provider?.local_test_mode&&!provider.local_dynamic_mode&&!run&&
        details.eligible_in_review>localLimit&&<p className="form-error" role="alert">
          This local pilot permits at most {localLimit} recipients.
        </p>}
      {!run&&readiness&&!readiness.ready&&<p className="form-error" role="alert">
        {readiness.message}
      </p>}
      {!run&&!readiness&&provider?.delivery_enabled&&
        <p className="form-error" role="alert">
          Sending requirements could not be verified. Refresh.
        </p>}
      <div className="comm-detail-tabs" role="group" aria-label="Campaign detail views">
        <button type="button" className={shownTab==="results"?"active":""}
          aria-pressed={shownTab==="results"} onClick={()=>setActiveTab("results")}>
          Sending results <span>{s.planned}</span>
        </button>
        <button type="button" className={shownTab==="review"?"active":""}
          aria-pressed={shownTab==="review"} onClick={()=>setActiveTab("review")}>
          Recipient review <span>{details.eligible_in_review+details.excluded_in_review}</span>
        </button>
      </div>
      {shownTab==="results"?<div className="comm-detail-section">
        <RecipientTable title="Sending results by contact" rows={details.recipients}/>
        {!details.recipients.length&&
          <p className="comm-muted">Check recipients and approve to begin sending.</p>}
      </div>:<div className="comm-detail-section">
        <section className="comm-recipient-review comm-detail-review" role="region"
          aria-label="Recipient approval">
          <div className="comm-review-heading">
            <h3>Recipient check</h3>
            {review&&<span className="comm-muted">
              {istDisplay(review.evaluated_at)}</span>}
          </div>
          <div className="comm-review-counts">
            <span><strong>{details.eligible_in_review}</strong> Eligible</span>
            <span><strong>{details.excluded_in_review}</strong> Excluded</span>
          </div>
          {Object.keys(details.excluded_reasons).length>0&&
            <p className="comm-muted">Excluded: {Object.entries(details.excluded_reasons)
              .map(([key,count])=>
                (reasons[key]??key.replaceAll("_"," "))+" ("+count+")"
              ).join(" · ")}</p>}
          {run?.status==="approved"&&<p className="comm-muted" role="status">
            {s.queued} pending · {s.claimed} processing
            {futurePlan?" · Scheduled for later":""}
          </p>}
          <div className="comm-review-footer">
            {!run&&<button type="button" className="btn btn-secondary"
              disabled={busy} onClick={()=>void checkRecipients()}>
              {busy?"Checking…":"Check recipients"}
            </button>}
            {run?.status==="approved"&&run.queued>0&&run.queued<=localLimit&&
              provider?.local_test_mode&&provider.delivery_enabled&&!futurePlan&&
              <button type="button" className="btn btn-primary" disabled={busy}
                onClick={()=>void sendPendingLocal()}>
                {busy?"Sending…":"Send pending WhatsApp now"}
              </button>}
            {!run&&provider?.delivery_enabled&&<button type="button"
              className="btn btn-primary" disabled={
                busy||older||!review||!readiness?.ready||review.eligible_count===0||
                Boolean(provider.local_test_mode&&review.eligible_count>localLimit)
              } onClick={()=>void approve()}>
                {busy?"Working…":localImmediate?"Send WhatsApp now":"Approve sending"}
              </button>}
            {run?.status==="approved"&&<button type="button" className="btn btn-secondary"
              disabled={busy} onClick={()=>void cancel()}>Stop pending</button>}
          </div>
        </section>
        {!run&&<RecipientTable title="Eligible contacts" rows={details.eligible_recipients}/>}
        {!!details.excluded_recipients.length&&
          <RecipientTable title="Excluded contacts" rows={details.excluded_recipients}/>}
      </div>}
      {pageTotal>pageSize&&<div className="comm-review-actions"
        role="navigation" aria-label="Campaign recipient pages">
        <span className="comm-muted">
          Showing {Math.min(offset+1,pageTotal)}–{Math.min(offset+pageSize,pageTotal)}
          {" "}of {pageTotal}
        </span>
        <button type="button" className="btn btn-secondary" disabled={offset===0}
          onClick={()=>setOffset(Math.max(0,offset-pageSize))}>Previous</button>
        <button type="button" className="btn btn-secondary"
          disabled={offset+pageSize>=pageTotal}
          onClick={()=>setOffset(offset+pageSize)}>Next</button>
      </div>}
    </>}
  </section>;
}
