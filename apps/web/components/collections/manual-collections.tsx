"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Prospect={id:string;full_name:string;mobile_number:string;monthly_contribution_paise:number;
  lifecycle_status:string;whatsapp_opt_in:boolean};
type Entry={id:string;sponsor_name:string;amount_paise:number;received_on:string;
  period_month:string;reference_mask:string;message_status:string;payment_method:string};
type Page={items:Entry[];total:number};
const deliveryLabel=(value:string):string=>({
  awaiting_integration:"Awaiting provider setup",
  suppressed:"Not eligible",
  claimed:"Dispatch in progress",
  accepted:"Provider accepted",
  unknown:"Unconfirmed",
  failed:"Provider rejected",
  cancelled:"Cancelled",
  sent:"Sent (confirmed)",
  delivered:"Delivered (confirmed)",
}[value]??"Unknown");

const amount=(value:number)=>(value/100).toLocaleString("en-IN",{style:"currency",currency:"INR"});
const istDate=()=>new Intl.DateTimeFormat("en-CA",{
  timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit",
}).format(new Date());

export function ManualCollections(){
  const [search,setSearch]=useState("");
  const [results,setResults]=useState<Prospect[]>([]);
  const [selected,setSelected]=useState<Prospect|null>(null);
  const [rupees,setRupees]=useState("");
  const [receivedOn,setReceivedOn]=useState(istDate);
  const [period,setPeriod]=useState(()=>istDate().slice(0,7));
  const [method,setMethod]=useState("upi");
  const [reference,setReference]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [success,setSuccess]=useState("");
  const [records,setRecords]=useState<Page|null>(null);
  const [refresh,setRefresh]=useState(0);
  const requestId=useRef<string|null>(null);
  useEffect(()=>{
    fetch("/api/admin/collections?limit=10",{cache:"no-store"})
      .then(async r=>{if(!r.ok)throw Error("Unable to load");return await r.json() as Page;})
      .then(setRecords).catch(()=>setRecords(null));
  },[refresh]);
  useEffect(()=>{
    if(search.trim().length<2||selected){setResults([]);return;}
    const controller=new AbortController();
    const timeout=setTimeout(()=>{
      fetch("/api/admin/prospects?"+new URLSearchParams({q:search.trim(),limit:"15"}),{
        cache:"no-store",signal:controller.signal,
      }).then(async r=>{if(!r.ok)throw Error("Search unavailable");return await r.json();})
        .then(data=>{if(!controller.signal.aborted)setResults(data.items as Prospect[]);})
        .catch(()=>{if(!controller.signal.aborted)setResults([]);});
    },250);
    return ()=>{clearTimeout(timeout);controller.abort();};
  },[search,selected]);

  function select(prospect:Prospect){
    setSelected(prospect);setSearch(prospect.full_name);setResults([]);
    setRupees((prospect.monthly_contribution_paise/100).toFixed(2));setError("");
    requestId.current=null;
  }
  function update(){setError("");setSuccess("");requestId.current=null;}
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(saving)return;
    if(!selected){setError("Select an existing sponsor.");return;}
    const trimmed=rupees.trim();
    if(!/^\d{1,8}(?:\.\d{1,2})?$/.test(trimmed)){setError("Enter a valid amount in rupees.");return;}
    const [whole,fraction=""]=trimmed.split(".");
    const paise=Number(whole)*100+Number(fraction.padEnd(2,"0"));
    if(!Number.isSafeInteger(paise)||paise<1||paise>1_000_000_000){
      setError("Enter a positive amount within the allowed limit.");return;
    }
    if(!confirmed){setError("Please confirm that the Foundation has actually received the funds.");return;}
    setSaving(true);setError("");setSuccess("");
    if(!requestId.current)requestId.current=crypto.randomUUID();
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const {csrf_token}=await session.json();
      const result=await fetch("/api/admin/collections",{
        method:"POST",credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
        body:JSON.stringify({
          request_id:requestId.current,prospect_id:selected.id,
          amount_paise:paise,period_month:period+"-01",received_on:receivedOn,
          payment_method:method,receipt_reference:reference.trim(),
          funds_confirmed:true,
        }),
      });
      if(!result.ok){
        if(result.status===409){
          setError("This receipt or request may already be recorded. Check the recent collections before trying again.");
        }else if(result.status===422){
          setError("Check the billing month, receipt date, reference and amount.");
        }else{
          setError("The collection was not confirmed. Check the recent list before retrying.");
        }
        return;
      }
      const data:Entry=await result.json();
      setSuccess("Recorded "+amount(data.amount_paise)+" for "+data.sponsor_name+
        ". "+(data.message_status==="awaiting_integration"
          ?"WhatsApp confirmation is awaiting provider setup; it has not been sent."
          :"WhatsApp confirmation suppressed because consent is missing."));
      setSelected(null);setSearch("");setRupees("");setReference("");
      setConfirmed(false);requestId.current=null;setRefresh(x=>x+1);
    }catch{setError("Connection interrupted. Check the recent list before retrying.");}
    finally{setSaving(false);}
  }
  return <div className="manual-collections-workspace">
    <section className="content-panel" aria-label="Record a manual collection">
      <h2>Record Collection</h2>
      <p className="panel-description">Only enter money already received and checked by the Foundation. Saving records the payment and prepares a confirmation if WhatsApp consent exists.</p>
      <form onSubmit={submit}>
        <div className="form-grid">
          <div className="form-cell full">
            <label className="field"><span className="field-label">Sponsor <span className="required">*</span></span>
              <input aria-label="Search sponsor" autoComplete="off" required value={search}
                placeholder="Search by name or mobile number"
                onChange={e=>{setSearch(e.target.value);setSelected(null);update();}}/>
            </label>
            {selected&&<p className="manual-selected">Selected: {selected.full_name} · {selected.mobile_number}
              · {selected.whatsapp_opt_in?"WhatsApp consent recorded":"No WhatsApp consent"}</p>}
            {!selected&&results.length>0&&<div className="manual-search-results" role="listbox" aria-label="Matching sponsors">
              {results.map(candidate=><button type="button" key={candidate.id}
                role="option" aria-selected={false} onClick={()=>select(candidate)}>
                <strong>{candidate.full_name}</strong><span>{candidate.mobile_number}</span>
              </button>)}
            </div>}
          </div>
          <label className="field"><span className="field-label">Amount received (₹) *</span>
            <input aria-label="Amount received (₹)" required type="text" inputMode="decimal" value={rupees}
              placeholder="500.00" onChange={e=>{setRupees(e.target.value);update();}}/></label>
          <label className="field"><span className="field-label">Payment method *</span>
            <select aria-label="Payment method" value={method} onChange={e=>{setMethod(e.target.value);update();}}>
              <option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
            </select></label>
          <label className="field"><span className="field-label">Received date (IST) *</span>
            <input aria-label="Received date (IST)" required type="date" max={istDate()}
              value={receivedOn} onChange={e=>{setReceivedOn(e.target.value);update();}}/></label>
          <label className="field"><span className="field-label">Sponsorship month *</span>
            <input aria-label="Sponsorship month" required type="month" max={istDate().slice(0,7)}
              value={period} onChange={e=>{setPeriod(e.target.value);update();}}/></label>
          <label className="field form-cell full"><span className="field-label">UPI transaction ID / bank reference / numbered receipt *</span>
            <input aria-label="Transaction reference" required minLength={6} maxLength={100}
              value={reference} placeholder="Enter a unique reference"
              onChange={e=>{setReference(e.target.value);update();}}/></label>
          <label className="checkbox-field form-cell full"><input type="checkbox"
            checked={confirmed} onChange={e=>{setConfirmed(e.target.checked);update();}}/>
            <span>I have checked the Foundation's records and confirm these funds were received.</span></label>
        </div>
        {error&&<p className="form-error" role="alert">{error}</p>}
        {success&&<p className="form-success" role="status">{success}</p>}
        <div className="form-actions"><button type="submit" disabled={saving||!confirmed||!selected}
          className="btn btn-primary">{saving?"Recording…":"Save Collection"}</button></div>
      </form>
    </section>
    <section className="content-panel" aria-label="Recent manual collections">
      <h2>Recently Recorded</h2>
      <p className="panel-description">Admin-attested entries, not bank-imported records. Corrections require a separately audited workflow.</p>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Sponsor</th><th>Amount</th><th>Month</th><th>Reference</th><th>WhatsApp</th></tr></thead>
        <tbody>{!records?.items.length?<tr><td colSpan={5}>No manual collections recorded yet.</td></tr>
          :records.items.map(item=><tr key={item.id}><td>{item.sponsor_name}</td>
            <td>{amount(item.amount_paise)}</td><td>{item.period_month.slice(0,7)}</td>
            <td>{item.reference_mask}</td>
            <td>{deliveryLabel(item.message_status)}</td></tr>)}</tbody>
      </table></div>
    </section>
  </div>;
}
