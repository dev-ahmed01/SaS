"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiWrite, istDisplay } from "./types";

type Status="not_approved"|"approved"|"cancelled"|"completed";
type Summary={
  campaign_id:string;run_status:Status;planned:number;
  submitted_unverified:number;rejected:number;unknown:number;
  queued:number;claimed:number;suppressed_after_approval:number;
  excluded_in_review:number;
  delivered:number|null;read:number|null;
};
type Recipient={
  recipient_kind:"prospect"|"promoter";recipient_id:string;
  name:string;phone_masked:string;status:string;reason:string|null;
  finished_at:string|null;
};
type CampaignDetails={
  campaign_id:string;title:string;audience:string;segment:string;category:string;
  channel:string;planned_for:string|null;created_at:string;
  summary:Summary;latest_review_at:string|null;
  eligible_in_review:number;excluded_in_review:number;
  excluded_reasons:Record<string,number>;
  recipients:Recipient[];excluded_recipients:Recipient[];
  delivery_notice:string;
};
type Review={
  id:string;eligible_count:number;suppressed_count:number;
  evaluated_at:string;exclusion_reasons?:Record<string,number>;
};
type DeliveryRun={
  id:string;status:Status;queued:number;eligible_count:number;
};
type Provider={
  delivery_enabled:boolean;local_test_mode?:boolean;
  activation_cutoff?:string|null;
};
const reasons:Record<string,string>={
  no_general_consent:"No documented permission for general updates",
  no_whatsapp_consent:"WhatsApp permission checkbox is off",
  no_email_consent:"No documented email permission",
  missing_address:"No contact number",
  opted_out:"Contact opted out",
  inactive_reminder:"Inactive contact cannot receive reminders",
  duplicate_address:"Duplicate contact number",
  campaign_cancelled:"Campaign cancelled before submission",
  consent_or_status_changed:"Consent, status or phone changed before sending",
  rejected:"Saasyto rejected the submission",
  unknown:"Submission outcome unknown; not safe to retry",
};
const statuses:Record<string,string>={
  queued:"Queued — not submitted",
  claimed:"Claimed — outcome pending/uncertain",
  accepted_unverified:"Submitted to Saasyto — not verified delivered",
  rejected:"Rejected by Saasyto",
  unknown:"Unknown — do not retry automatically",
  suppressed:"Not sent",
  excluded:"Not eligible at recipient check",
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
  return <section className="comm-recipient-review" aria-label={title}>
    <div className="comm-review-heading"><h3>{title}</h3>
      <span className="comm-muted">{rows.length} contacts</span></div>
    {rows.length===0?<p className="comm-muted">No recorded contacts in this section.</p>:
      <div className="comm-campaign-table-scroll">
        <table className="data-table comm-campaign-table">
          <thead><tr>
            <th scope="col">Contact</th><th scope="col">Phone</th>
            <th scope="col">Result</th><th scope="col">Reason / time</th>
          </tr></thead>
          <tbody>{rows.map(row=><tr key={row.recipient_kind+row.recipient_id}>
            <td><Link href={row.recipient_kind==="prospect"
              ?"/prospects/"+row.recipient_id:"/promoters/"+row.recipient_id}>
              {row.name}</Link></td>
            <td>{row.phone_masked}</td>
            <td>{statuses[row.status]??row.status}</td>
            <td>{row.reason?(reasons[row.reason]??row.reason.replaceAll("_"," ")):
              row.finished_at?istDisplay(row.finished_at):"—"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
  </section>;
}

export function CampaignResultDetails({id}:{id:string}){
  const [details,setDetails]=useState<CampaignDetails|null>(null);
  const [review,setReview]=useState<Review|null>(null);
  const [run,setRun]=useState<DeliveryRun|null>(null);
  const [provider,setProvider]=useState<Provider|null>(null);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const refresh=useCallback(async()=>{
    const [result,checks,dispatch,availability]=await Promise.all([
      apiGet<CampaignDetails>("/campaigns/"+id+"/results"),
      apiGet<Review[]>("/campaigns/"+id+"/preparations"),
      apiGet<DeliveryRun|null>("/campaigns/"+id+"/saasyto"),
      apiGet<Provider>("/provider/saasyto"),
    ]);
    setDetails(result);setReview(checks[0]??null);
    setRun(dispatch);setProvider(availability);
  },[id]);
  useEffect(()=>{
    let active=true;
    setLoading(true);
    refresh().catch(()=>{if(active)setError("Campaign results could not be loaded.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[refresh]);
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
  async function approve(){
    if(busy||!review||!provider?.delivery_enabled||review.eligible_count<1||run)return;
    if(!window.confirm("Approve "+review.eligible_count+
      " eligible recipient(s)? This queues a single attempt per contact. "+
      "Gateway acceptance does not confirm delivery."))return;
    setBusy(true);setError("");setNotice("");
    try{
      await apiWrite("/campaigns/"+id+"/saasyto","POST",{
        preparation_id:review.id,expected_eligible:review.eligible_count,
        confirm_send:true,
      });
      await refresh();
      setNotice("Approved. The private sending worker will process the campaign when due.");
    }catch(e){setError(e instanceof Error?e.message:"Unable to approve campaign.");}
    finally{setBusy(false);}
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
  return <section className="comm-panel" aria-label="Campaign results detail">
      <div className="comm-panel-header">
        <div><Link href="/communication/campaigns" className="back-link">
          All campaigns</Link>
          <h2>{details?.title??"Campaign results"}</h2>
          {details&&<p>{details.channel==="whatsapp"?"WhatsApp":"Email"} ·
            {" "+details.audience+" / "+details.segment} ·
            {" Created "+istDisplay(details.created_at)}</p>}
        </div>
        <button type="button" className="btn btn-secondary" disabled={busy||loading}
          onClick={()=>{setError("");void refresh().catch(()=>setError("Could not refresh results."));}}>
          Refresh results</button>
      </div>
      {loading&&<p role="status">Loading campaign results…</p>}
      {error&&<p role="alert" className="form-error">{error}</p>}
      {notice&&<p role="status" className="form-success">{notice}</p>}
      {details&&s&&<>
        <p className="comm-muted">
          {details.planned_for?"Planned for "+istDisplay(details.planned_for):
            "Ready for manual approval (not yet scheduled)"}
          {" · "}Campaign state: {s.run_status.replaceAll("_"," ")}
        </p>
        <div className="crm-summary-strip">
          <Metric name="Approved recipients" value={s.planned}/>
          <Metric name="Submitted to gateway" value={s.submitted_unverified}
            help="Delivery unverified"/>
          <Metric name="Rejected" value={s.rejected}/>
          <Metric name="Not sent / excluded"
            value={s.suppressed_after_approval+s.excluded_in_review}
            help="Latest preflight and later suppression"/>
          <Metric name="Pending" value={s.queued+s.claimed}/>
          <Metric name="Unknown" value={s.unknown} help="No automatic retry"/>
          <Metric name="Delivered" value={s.delivered??"Unavailable"}
            help="Provider callback not verified"/>
          <Metric name="Read / seen" value={s.read??"Unavailable"}
            help="Provider callback not verified"/>
        </div>
        <div className="comm-provider-status" role="status">
          <strong>Message delivery evidence</strong>
          <small>{details.delivery_notice}</small>
        </div>
        {older&&!run&&<p className="form-error" role="status">
          This campaign predates Saasyto activation. Create a new campaign
          to obtain a valid delivery approval.</p>}
        <div className="comm-recipient-review" aria-label="Recipient approval">
          <div className="comm-review-heading">
            <h3>Recipient review</h3>
            <span className="comm-muted">
              {review?istDisplay(review.evaluated_at):"Not checked yet"}
            </span>
          </div>
          <div className="comm-review-counts">
            <span><strong>{details.eligible_in_review}</strong> Eligible</span>
            <span><strong>{details.excluded_in_review}</strong> Excluded</span>
          </div>
          {Object.keys(details.excluded_reasons).length>0&&
            <div className="comm-provider-status">
              <strong>Exclusions during latest check</strong>
              <ul>{Object.entries(details.excluded_reasons).map(([key,count])=>
                <li key={key}>{reasons[key]??key.replaceAll("_"," ")}: {count}</li>)}</ul>
            </div>}
          <div className="comm-review-footer">
            <span className="comm-muted">Checking does not send messages.</span>
            {!run&&<button type="button" className="btn btn-secondary"
              disabled={busy} onClick={()=>void checkRecipients()}>
              {busy?"Working…":"Check recipients"}</button>}
            {!run&&provider?.delivery_enabled&&<button type="button"
              className="btn btn-primary" disabled={
                busy||older||!review||review.eligible_count===0||
                Boolean(provider.local_test_mode&&review.eligible_count!==1)
              } onClick={()=>void approve()}>Approve WhatsApp delivery</button>}
            {run?.status==="approved"&&<button type="button" className="btn btn-secondary"
              disabled={busy} onClick={()=>void cancel()}>Stop pending sends</button>}
          </div>
        </div>
        <RecipientTable title="Sending results by contact" rows={details.recipients}/>
        <RecipientTable title="Excluded before sending (latest review)"
          rows={details.excluded_recipients}/>
        <p className="comm-muted">
          Numbers are masked. A recipient excluded during the latest check was
          not submitted by that check. Never interpret submitted-to-gateway as
          delivered or seen without verified callbacks.
        </p>
      </>}
  </section>;
}
