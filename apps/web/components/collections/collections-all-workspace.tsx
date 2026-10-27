"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { recentSnapshot, rememberSnapshot } from "../../lib/module-snapshots";
import { AccountingOverview } from "../accounting/accounting-overview";
import { formatCRMDate } from "../../lib/crm-dates";

type Payment = {
  id: string;
  sponsor_name: string;
  sponsor_mobile: string;
  amount_paise: number;
  received_on: string;
  recorded_at: string;
  period_month: string;
  payment_method: string;
  reference_mask: string;
  message_status: string;
  reversed: boolean;
  reversal_reason: string | null;
};
type Page = {items: Payment[]; total: number; limit: number; offset: number};
type Reason = "duplicate_entry"|"wrong_sponsor"|"wrong_amount"|"funds_not_received"|"other";
const reasons: {value:Reason;label:string}[] = [
  {value:"duplicate_entry",label:"Duplicate entry"},
  {value:"wrong_sponsor",label:"Wrong sponsor"},
  {value:"wrong_amount",label:"Wrong amount"},
  {value:"funds_not_received",label:"Funds were not received"},
  {value:"other",label:"Other entry error"},
];
const deliveryLabel=(value:string):string=>({
  awaiting_integration:"Awaiting provider setup",
  suppressed:"Suppressed",
  claimed:"Dispatch in progress",
  accepted:"Provider accepted",
  unknown:"Unconfirmed",
  failed:"Provider rejected",
  cancelled:"Cancelled",
  sent:"Sent (confirmed)",
  delivered:"Delivered (confirmed)",
}[value]??"Unknown");

const rupees = (paise:number) => (paise/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",
});

export function CollectionsAllWorkspace({activeOnly=false}:{activeOnly?:boolean}) {
  const [revision,setRevision] = useState(0);
  return <>
    {!activeOnly&&<AccountingOverview key={revision}/>}
    {activeOnly&&<CollectionsReview activeOnly onReversed={()=>setRevision(n=>n+1)}/>}
  </>;
}

export function CollectionsReview({onReversed,activeOnly=false}:{onReversed:()=>void;activeOnly?:boolean}) {
  const [month,setMonth] = useState(()=>activeOnly?new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit"}).format(new Date()):"");
  const [offset,setOffset] = useState(0);
  const [refresh,setRefresh] = useState(0);
  const [loading,setLoading] = useState(true);
  const [data,setData] = useState<Page|null>(null);
  const [selected,setSelected] = useState<Payment|null>(null);
  const [action,setAction] = useState<"edit"|"delete">("delete");
  const [correctionReady,setCorrectionReady] = useState(false);
  const [resendBusy,setResendBusy] = useState<string|null>(null);
  const resendRequests=useRef<Record<string,string>>({});
  const [reason,setReason] = useState<Reason>("duplicate_entry");
  const [typed,setTyped] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const requestId = useRef<string|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    const params=new URLSearchParams({limit:"20",offset:String(offset)});
    if(month)params.set(activeOnly?"received_month":"period_month",month+"-01");
    // This-month receipts include all sponsors, not only currently Active CRM sponsors.
    const key="/api/admin/collections?"+params;
    const cached=recentSnapshot<Page>(key);
    setData(cached);setLoading(!cached);
    fetch(key,{cache:"no-store",signal:controller.signal})
      .then(async response=>{
        if(!response.ok)throw Error("History unavailable");
        return await response.json() as Page;
      })
      .then(page=>{if(!controller.signal.aborted){rememberSnapshot(key,page);setData(page);setError("");}})
      .catch(()=>{if(!controller.signal.aborted)setError("Collection history is temporarily unavailable.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[month,offset,refresh,activeOnly]);

  function choose(row:Payment,kind:"edit"|"delete") {
    if(row.reversed)return;
    setSelected(row);setAction(kind);
    setReason(kind==="edit"?"wrong_amount":"duplicate_entry");
    setTyped("");setCorrectionReady(false);
    setError("");setNotice("");requestId.current=null;
  }
  function close() {
    if(busy)return;
    setSelected(null);setTyped("");requestId.current=null;
  }

  async function reverse(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(!selected||typed!=="REVERSE"||busy)return;
    setBusy(true);setError("");
    if(!requestId.current)requestId.current=crypto.randomUUID();
    try {
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const token=(await session.json()).csrf_token;
      const response=await fetch("/api/admin/collections/"+selected.id+"/reverse",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":token},
        body:JSON.stringify({
          request_id:requestId.current, reason_code:reason, confirmation:"REVERSE",
        }),
      });
      if(!response.ok) {
        if(response.status===409)throw Error("This record may already have been reversed. Refresh before retrying.");
        throw Error("Reversal was not confirmed. Check records before retrying.");
      }
      const result=await response.json();
      setNotice((action==="edit"?"Original collection reversed. Record the corrected payment next. ":
        "Entry removed from net totals (original audit record preserved). ")+
        "Ledger and sponsor status were recalculated. "+
        (result.message_status==="suppressed"
          ?"Pending WhatsApp confirmation was suppressed."
          :"An earlier provider transmission cannot be recalled.")); 
      setCorrectionReady(action==="edit");
      setSelected(null);setTyped("");requestId.current=null;
      setRefresh(n=>n+1);onReversed();
    } catch(err) {
      setError(err instanceof Error?err.message:"Could not confirm reversal. Refresh before retrying.");
    } finally {
      setBusy(false);
    }
  }

  async function resend(row:Payment){
    if(resendBusy||busy||row.reversed)return;
    setResendBusy(row.id);setError("");setNotice("");setCorrectionReady(false);
    resendRequests.current[row.id]??=crypto.randomUUID();
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const {csrf_token}=await session.json();
      const response=await fetch(
        "/api/admin/collections/"+row.id+"/resend-confirmation",{
          method:"POST",credentials:"same-origin",
          headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
          body:JSON.stringify({
            request_id:resendRequests.current[row.id],confirmation:"RESEND",
          }),
        }
      );
      const payload=await response.json().catch(()=>null);
      if(!response.ok)throw Error(
        typeof payload?.detail==="string"?payload.detail:
        response.status===503?"Approved WhatsApp receipt sending is not configured.":
        "Resend could not be queued. Check messaging status."
      );
      setNotice(payload.notice??"Receipt resend queued. Delivery is not confirmed.");
      setRefresh(n=>n+1);
    }catch(e){
      setError(e instanceof Error?e.message:"Could not request receipt resend.");
    }finally{setResendBusy(null);}
  }

  return <section className="collection-review" aria-label="Collection review">
    <div className="review-heading">
      <div>
        <h2>{activeOnly?"Received this month":"Collection history"}</h2>
      </div>
      <label className="field review-month">
        <span className="field-label">{activeOnly?"Date paid month":"Sponsorship month"}</span>
        <input type="month" aria-label="Filter collection history by month" value={month}
          onChange={e=>{setMonth(e.target.value);setOffset(0);}}/>
      </label>
    </div>
    {notice&&<p role="status" className="form-success">{notice}
      {correctionReady&&<span> <Link href="/collections/add">Record corrected collection</Link></span>}
    </p>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th scope="col">Sponsor</th><th scope="col">Amount</th>
          <th scope="col">Month</th><th scope="col">Reference</th>
          <th scope="col">Recorded</th><th scope="col">Status</th><th scope="col">WhatsApp</th>
          <th scope="col">Action</th></tr></thead>
        <tbody>{loading&&!data?<tr><td colSpan={8}>Loading collection history…</td></tr>
          :!data?.items.length?<tr><td colSpan={7}>{activeOnly?"No receipts recorded for this month.":"No manually recorded collections."}</td></tr>
          :data.items.map(row=><tr key={row.id}>
            <td><strong className="table-name">{row.sponsor_name}</strong><span className="table-subtitle">{row.sponsor_mobile}</span></td>
            <td>{rupees(row.amount_paise)}</td>
            <td>{formatCRMDate(row.period_month)}</td>
            <td>{row.reference_mask}</td>
            <td title={"Recorded at "+new Date(row.recorded_at).toLocaleString("en-IN",{timeZone:"Asia/Kolkata"})}>
              {formatCRMDate(row.recorded_at)}</td>
            <td><span className={"status-pill "+(row.reversed?"archived":"active")}>
              {row.reversed?"Reversed":"Recorded"}</span></td>
            <td>{deliveryLabel(row.message_status)}</td>
            <td>{row.reversed?<span className="muted">No further action</span>
              :<div className="collection-row-actions">
                <button type="button" className="text-action"
                  disabled={busy||resendBusy!==null}
                  onClick={()=>choose(row,"edit")}>Edit</button>
                <button type="button" className="text-action"
                  disabled={busy||resendBusy!==null}
                  onClick={()=>choose(row,"delete")}>Delete</button>
                <button type="button" className="text-action"
                  disabled={busy||resendBusy!==null}
                  onClick={()=>void resend(row)}>
                  {resendBusy===row.id?"Queuing…":"Resend confirmation"}
                </button>
              </div>}</td>
          </tr>)}</tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{data?data.total+" recorded collections":"Waiting for records"}</span>
      <div className="paging-actions">
        <button type="button" className="btn btn-secondary" disabled={loading||offset===0}
          onClick={()=>setOffset(n=>Math.max(0,n-20))}>Previous</button>
        <button type="button" className="btn btn-secondary"
          disabled={loading||!data||offset+20>=data.total}
          onClick={()=>setOffset(n=>n+20)}>Next</button>
      </div>
    </div>

    {selected&&<div className="modal-scrim" onMouseDown={event=>{
      if(event.target===event.currentTarget)close();
    }}>
      <section role="dialog" aria-modal="true" aria-labelledby="reverse-title"
        className="edit-modal reversal-dialog">
        <div className="modal-topline">
          <span>Financial correction</span>
          <button type="button" className="text-action" onClick={close} disabled={busy}
            aria-label="Close reversal dialog">Close</button>
        </div>
        <div className="content-panel">
          <h2 id="reverse-title">{action==="edit"?"Correct collection":"Delete collection entry"}</h2>

          <p className="panel-description">{action==="edit"
            ?"Corrections preserve the original record: reverse this entry, then record the corrected payment."
            :"Removes this entry from totals by recording a reversal. The original stays in the audit trail; no refund occurs."}</p>
          <div className="reversal-facts">
            <div><span>Sponsor</span><strong>{selected.sponsor_name}</strong></div>
            <div><span>Amount</span><strong>{rupees(selected.amount_paise)}</strong></div>
            <div><span>Month</span><strong>{formatCRMDate(selected.period_month)}</strong></div>
            <div><span>Reference</span><strong>{selected.reference_mask}</strong></div>
          </div>
          <form onSubmit={reverse} aria-label="Confirm collection reversal">
            <label className="field"><span className="field-label">Reason for reversal *</span>
              <select required aria-label="Reason for reversal"
                value={reason} onChange={e=>{setReason(e.target.value as Reason);requestId.current=null;}}>
                {reasons.map(item=><option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label className="field"><span className="field-label">Type REVERSE to confirm *</span>
              <input autoFocus required aria-label="Type REVERSE to confirm"
                autoComplete="off" value={typed} onChange={e=>setTyped(e.target.value)}
                placeholder="REVERSE"/>
            </label>
            {error&&<p className="form-error" role="alert">{error}</p>}
            <div className="form-actions">
              <button className="btn btn-secondary" type="button" onClick={close}
                disabled={busy}>Cancel</button>
              <button type="submit" className="btn btn-danger" disabled={busy||typed!=="REVERSE"}>
                {busy?"Reversing…":action==="edit"?"Reverse & correct":"Confirm deletion (reversal)"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>}
  </section>;
}
