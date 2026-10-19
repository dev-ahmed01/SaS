"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AccountingOverview } from "../accounting/accounting-overview";

type Payment = {
  id: string;
  sponsor_name: string;
  amount_paise: number;
  received_on: string;
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

export function CollectionsAllWorkspace({activeOnly=false,receivedOnly=false}:{activeOnly?:boolean;receivedOnly?:boolean}) {
  const [revision,setRevision] = useState(0);
  return <>
    {!activeOnly&&!receivedOnly&&<AccountingOverview key={revision}/>}
    <CollectionsReview activeOnly={activeOnly||receivedOnly} receivedOnly={receivedOnly} onReversed={()=>setRevision(n=>n+1)}/>
  </>;
}

export function CollectionsReview({onReversed,activeOnly=false,receivedOnly=false}:{onReversed:()=>void;activeOnly?:boolean;receivedOnly?:boolean}) {
  const [month,setMonth] = useState(()=>(activeOnly||receivedOnly)?new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit"}).format(new Date()):"");
  const [offset,setOffset] = useState(0);
  const [refresh,setRefresh] = useState(0);
  const [loading,setLoading] = useState(true);
  const [data,setData] = useState<Page|null>(null);
  const [selected,setSelected] = useState<Payment|null>(null);
  const [reason,setReason] = useState<Reason>("duplicate_entry");
  const [typed,setTyped] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const requestId = useRef<string|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    const params=new URLSearchParams({limit:"20",offset:String(offset)});
    if(month)params.set("period_month",month+"-01");
    if(activeOnly)params.set("active_only","true");
    setLoading(true);
    fetch("/api/admin/collections?"+params,{cache:"no-store",signal:controller.signal})
      .then(async response=>{
        if(!response.ok)throw Error("History unavailable");
        return await response.json() as Page;
      })
      .then(page=>{if(!controller.signal.aborted){setData(page);setError("");}})
      .catch(()=>{if(!controller.signal.aborted)setError("Collection history is temporarily unavailable.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[month,offset,refresh,activeOnly]);

  function choose(row:Payment) {
    if(row.reversed)return;
    setSelected(row);setReason("duplicate_entry");setTyped("");
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
      setNotice("Reversed the incorrect "+rupees(result.amount_paise)+
        " collection. Ledger and sponsor status were recalculated. "+
        (result.message_status==="suppressed"
          ?"Its pending WhatsApp confirmation was suppressed."
          :"An earlier provider transmission cannot be recalled. Verify recipient communication."));
      setSelected(null);setTyped("");requestId.current=null;
      setRefresh(n=>n+1);onReversed();
    } catch(err) {
      setError(err instanceof Error?err.message:"Could not confirm reversal. Refresh before retrying.");
    } finally {
      setBusy(false);
    }
  }

  return <section className="collection-review" aria-label="Collection review">
    <div className="review-heading">
      <div>
        <h2>{receivedOnly?"Received collections":activeOnly?"Active collections":"Collection history"}</h2>
      </div>
      <label className="field review-month">
        <span className="field-label">{receivedOnly?"Received month":activeOnly?"Collection month":"Filter by month"}</span>
        <input type="month" aria-label="Filter collection history by month" value={month}
          onChange={e=>{setMonth(e.target.value);setOffset(0);}}/>
      </label>
    </div>
    {notice&&<p role="status" className="form-success">{notice}</p>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="table-scroll finance-table-scroll">
      <table className="data-table">
        <thead><tr><th scope="col">Sponsor</th><th scope="col">Amount</th>
          <th scope="col">Month</th><th scope="col">Reference</th>
          <th scope="col">Entry</th><th scope="col">WhatsApp</th>
          <th scope="col">Action</th></tr></thead>
        <tbody>{loading?<tr><td colSpan={7}>Loading collection history…</td></tr>
          :!data?.items.length?<tr><td colSpan={7}>{receivedOnly?"No recorded receipts for this month.":activeOnly?"No active collections for this period.":"No manually recorded collections."}</td></tr>
          :data.items.map(row=><tr key={row.id}>
            <td><strong className="table-name">{row.sponsor_name}</strong></td>
            <td>{rupees(row.amount_paise)}</td>
            <td>{row.period_month.slice(0,7)}</td>
            <td>{row.reference_mask}</td>
            <td><span className={"status-pill "+(row.reversed?"archived":"active")}>
              {row.reversed?"Reversed":"Recorded"}</span></td>
            <td>{deliveryLabel(row.message_status)}</td>
            <td>{row.reversed?<span className="muted">No further action</span>
              :<button type="button" className="text-action" onClick={()=>choose(row)}>
                Reverse entry
              </button>}</td>
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
          <h2 id="reverse-title">Reverse collection entry</h2>

          <p className="panel-description">Reverses the record only. No refund is issued.</p>
          <div className="reversal-facts">
            <div><span>Sponsor</span><strong>{selected.sponsor_name}</strong></div>
            <div><span>Amount</span><strong>{rupees(selected.amount_paise)}</strong></div>
            <div><span>Month</span><strong>{selected.period_month.slice(0,7)}</strong></div>
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
                {busy?"Reversing…":"Confirm reversal"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>}
  </section>;
}
