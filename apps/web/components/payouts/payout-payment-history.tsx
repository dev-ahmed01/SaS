"use client";

import {FormEvent,useEffect,useRef,useState} from "react";
import {formatCRMDate} from "../../lib/crm-dates";
import {useDialogFocus} from "../../lib/dialog-focus";

type Payment={
  id:string;plan_id:string;payee_name:string;period_month:string;paid_on:string;
  amount_paise:number;payment_method:string;reference_mask:string;
  reversed:boolean;reversal_reason:string|null;
};
type PaymentPage={items:Payment[];total:number;offset:number;limit:number};
const reasons=[
  ["duplicate_entry","Duplicate entry"],["wrong_payee","Wrong payee"],
  ["wrong_amount","Wrong amount"],["funds_not_disbursed","Funds never left the account"],
  ["wrong_reference","Wrong reference"],["other","Other entry error"]
] as const;
const money=(value:number)=>(value/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",
});
export function PayoutPaymentHistory({onCorrected}:{onCorrected:()=>void}){
  const [page,setPage]=useState<PaymentPage|null>(null);
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [selected,setSelected]=useState<Payment|null>(null);
  const [reason,setReason]=useState<string>("duplicate_entry");
  const [typed,setTyped]=useState("");
  const [acknowledged,setAcknowledged]=useState(false);
  const [saving,setSaving]=useState(false);
  const requestId=useRef<string|null>(null);

  useEffect(()=>{
    const ctrl=new AbortController();
    setLoading(true);
    fetch("/api/admin/payouts/payments?"+new URLSearchParams({
      limit:"20",offset:String(offset)
    }),{cache:"no-store",signal:ctrl.signal})
      .then(async res=>{if(!res.ok)throw Error("Payment history unavailable.");return res.json();})
      .then((data:PaymentPage)=>{if(!ctrl.signal.aborted){setPage(data);setError("");}})
      .catch(()=>{if(!ctrl.signal.aborted)setError("Unable to load the payment history.");})
      .finally(()=>{if(!ctrl.signal.aborted)setLoading(false);});
    return ()=>ctrl.abort();
  },[offset,revision]);

  function open(item:Payment){
    if(item.reversed)return;
    setSelected(item);setReason("duplicate_entry");setTyped("");
    setAcknowledged(false);setError("");setNotice("");requestId.current=null;
  }
  function close(){if(!saving){setSelected(null);setTyped("");requestId.current=null;}}
  async function reverse(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!selected||typed!=="REVERSE"||!acknowledged||saving)return;
    setSaving(true);setError("");requestId.current??=crypto.randomUUID();
    try{
      const res=await fetch("/api/admin/session",{cache:"no-store"});
      if(!res.ok)throw Error("Admin session expired.");
      const token=(await res.json()).csrf_token;
      const response=await fetch("/api/admin/payouts/payments/"+selected.id+"/reverse",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":token},
        body:JSON.stringify({request_id:requestId.current,
          confirmation:"REVERSE",reason})
      });
      if(!response.ok)throw Error(response.status===409
        ?"Payment has already been corrected. Refresh the list."
        :"Correction could not be confirmed. Check payment history before retrying.");
      setNotice("Ledger entry reversed and audited. No bank transfer or refund was initiated.");
      setSelected(null);requestId.current=null;setRevision(v=>v+1);onCorrected();
    }catch(e){
      setError(e instanceof Error?e.message:"Unable to reverse the ledger entry.");
    }finally{setSaving(false);}
  }
  const paymentDialogRef=useDialogFocus<HTMLElement>(Boolean(selected),()=>{if(!saving)close();});
  return <section className="content-panel payout-payment-history" aria-label="Recorded payouts and corrections">
    <h2>Recorded outgoing payments</h2>
    <p className="panel-description">These records are administrative attestations, not bank transfers.
      Corrections keep the original entry and its audit history.</p>
    {notice&&<p role="status" className="form-success">{notice}</p>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr>{["Payee","Date paid","Amount","Method","Reference","Status","Action"]
          .map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{loading&&!page?<tr><td colSpan={7}>Loading payments…</td></tr>:
          !page?.items.length?<tr><td colSpan={7}>No outgoing payments recorded.</td></tr>:
          page.items.map(item=><tr key={item.id}>
            <td>{item.payee_name}</td>
            <td>{formatCRMDate(item.paid_on)}</td>
            <td>{money(item.amount_paise)}</td>
            <td>{item.payment_method.replaceAll("_"," ")}</td>
            <td>{item.reference_mask}</td>
            <td>{item.reversed?"Reversed":"Recorded"}</td>
            <td>{item.reversed?"Original retained":<button type="button"
              className="text-action" onClick={()=>open(item)}>Correct record</button>}</td>
          </tr>)}</tbody>
      </table>
    </div>
    <div className="table-footer paging-footer">
      <span>{page?page.total+" payment records":"Waiting for records"}</span>
      <div className="paging-actions">
        <button className="btn btn-secondary" type="button" disabled={loading||offset===0}
          onClick={()=>setOffset(v=>Math.max(0,v-20))}>Previous</button>
        <button className="btn btn-secondary" type="button"
          disabled={loading||!page||offset+20>=page.total}
          onClick={()=>setOffset(v=>v+20)}>Next</button>
      </div>
    </div>
    {selected&&<div className="modal-scrim" onMouseDown={event=>{
      if(event.target===event.currentTarget)close();
    }}><section className="edit-modal payout-dialog" role="dialog"
      aria-modal="true" aria-labelledby="payout-reversal-heading" ref={paymentDialogRef} tabIndex={-1}>
      <div className="modal-topline"><span>Financial correction</span>
        <button type="button" className="text-action" onClick={close}
          disabled={saving}>Close</button></div>
      <h2 id="payout-reversal-heading">Reverse recorded payout</h2>
      <p className="panel-description">Correct the CRM ledger only. The application does not return
        funds, cancel an external bank payment, or delete the original record.</p>
      <p><strong>{selected.payee_name}</strong> · {money(selected.amount_paise)}
        {" · "}{selected.reference_mask}</p>
      <form onSubmit={reverse}>
        <label className="field"><span className="field-label">Reason *</span>
          <select aria-label="Payout reversal reason" value={reason}
            onChange={e=>{setReason(e.target.value);requestId.current=null;}}>
            {reasons.map(([value,label])=><option key={value} value={value}>{label}</option>)}
          </select></label>
        <label className="checkbox-field"><input type="checkbox"
          checked={acknowledged} onChange={e=>setAcknowledged(e.target.checked)}/>
          <span>I checked the Foundation's bank records. This is an administrative correction only.</span>
        </label>
        <label className="field"><span className="field-label">Type REVERSE to confirm *</span>
          <input required aria-label="Type REVERSE to confirm"
            value={typed} onChange={e=>setTyped(e.target.value)}
            autoComplete="off" maxLength={7}/></label>
        {error&&<p role="alert" className="form-error">{error}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={close}
            disabled={saving}>Cancel</button>
          <button type="submit" className="btn btn-danger"
            disabled={saving||typed!=="REVERSE"||!acknowledged}>
            {saving?"Reversing…":"Reverse ledger entry"}
          </button>
        </div>
      </form>
    </section></div>}
  </section>;
}
