"use client";
import { FormEvent, useEffect, useRef, useState } from "react";

type Plan={id:string;payee_name:string;purpose:string;amount_paise:number;
 frequency:"recurring"|"one_time";start_month:string;status:"active"|"paused"|"closed";
 notes:string|null;recorded_periods:number};
type Disbursement={id:string;plan_id:string;payee_name:string;period_month:string;
 paid_on:string;amount_paise:number;payment_method:string;reference_mask:string};
type Page<T>={items:T[];total:number;offset:number;limit:number};
const money=(p:number)=>(p/100).toLocaleString("en-IN",{style:"currency",currency:"INR"});
const today=()=>new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Kolkata"});
const month=()=>today().slice(0,7);
const initial={payee_name:"",purpose:"",amount:"500",frequency:"recurring",
 start_month:month(),notes:""};

export function PayoutWorkspace({view}:{view:"add"|"active"|"all"}){
  const [form,setForm]=useState(initial);
  const [plans,setPlans]=useState<Plan[]>([]);
  const [history,setHistory]=useState<Disbursement[]>([]);
  const [revision,setRevision]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [selected,setSelected]=useState<Plan|null>(null);
  const [period,setPeriod]=useState(month());
  const [paidOn,setPaidOn]=useState(today());
  const [method,setMethod]=useState("upi");
  const [reference,setReference]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const requestId=useRef<string|null>(null);
  useEffect(()=>{
    let cancelled=false;
    Promise.all([
      fetch("/api/admin/payouts?limit=100",{cache:"no-store"}).then(async r=>{
        if(!r.ok)throw Error("Unable to load payouts");
        return await r.json() as Page<Plan>;
      }),
      fetch("/api/admin/payouts/disbursements?limit=100",{cache:"no-store"}).then(async r=>{
        if(!r.ok)throw Error("Unable to load outgoing payment history");
        return await r.json() as Page<Disbursement>;
      }),
    ]).then(([p,h])=>{if(!cancelled){setPlans(p.items);setHistory(h.items);}})
      .catch(e=>{if(!cancelled)setError(e.message);});
    return ()=>{cancelled=true;};
  },[revision]);
  async function post(url:string,body:object){
    const session=await fetch("/api/admin/session",{cache:"no-store"});
    if(!session.ok)throw Error("Admin session expired");
    const {csrf_token}=await session.json();
    const result=await fetch(url,{
      method:"POST",credentials:"same-origin",
      headers:{"Content-Type":"application/json","X-CSRF-Token":csrf_token},
      body:JSON.stringify(body),
    });
    if(!result.ok){
      const data=await result.json().catch(()=>({detail:"Request failed"}));
      throw Error(typeof data.detail==="string"?data.detail:"Unable to save changes");
    }
    return result.json();
  }
  async function create(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(busy)return;
    setBusy(true);setError("");setMessage("");
    if(!requestId.current)requestId.current=crypto.randomUUID();
    try{
      const amount=Number(form.amount);
      if(!Number.isFinite(amount)||amount<=0||Math.round(amount*100)!==amount*100)
        throw Error("Enter an amount in rupees with at most two decimals");
      await post("/api/admin/payouts",{
        request_id:requestId.current,payee_name:form.payee_name,
        purpose:form.purpose,amount_paise:Math.round(amount*100),
        frequency:form.frequency,start_month:form.start_month+"-01",
        notes:form.notes||null,
      });
      setForm({...initial,start_month:month()});requestId.current=null;
      setMessage("Payout plan saved. No money has been transferred.");
      setRevision(n=>n+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to save payout");}
    finally{setBusy(false);}
  }
  async function changeStatus(plan:Plan,status:"active"|"paused"|"closed"){
    if(busy)return;setBusy(true);setError("");setMessage("");
    try{
      await post("/api/admin/payouts/"+plan.id+"/status",{status});
      setMessage("Recurring payout status updated.");
      setRevision(n=>n+1);
    }catch(e){setError(e instanceof Error?e.message:"Status update failed");}
    finally{setBusy(false);}
  }
  function choose(plan:Plan){
    setSelected(plan);setPeriod(plan.start_month.slice(0,7));
    setPaidOn(today());setMethod("upi");setReference("");setConfirmed(false);
    requestId.current=null;setError("");setMessage("");
  }
  async function record(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(!selected||busy||!confirmed)return;
    setBusy(true);setError("");
    if(!requestId.current)requestId.current=crypto.randomUUID();
    try{
      await post("/api/admin/payouts/"+selected.id+"/disbursements",{
        request_id:requestId.current,period_month:period+"-01",
        paid_on:paidOn,amount_paise:selected.amount_paise,
        payment_method:method,receipt_reference:reference,
        funds_sent_confirmed:true,
      });
      setSelected(null);requestId.current=null;
      setMessage("Outgoing payment recorded from Admin-checked evidence. No transfer was initiated.");
      setRevision(n=>n+1);
    }catch(e){setError(e instanceof Error?e.message:"Unable to record outgoing payment");}
    finally{setBusy(false);}
  }
  const visible=plans.filter(p=>view!=="active"||
    (p.frequency==="recurring"&&p.status==="active"));
  return <div className="payout-workspace">
    <p className="accounting-footnote">Payouts are recorded after an Admin verifies the
      external transfer. This app does not send money or initiate UPI payments.</p>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {message&&<p role="status" className="form-success">{message}</p>}
    {view==="add"&&<section className="content-panel">
      <h2>Add payout</h2><p className="panel-description">
        Create a recurring monthly obligation or a one-time payout plan.
      </p>
      <form onSubmit={create} aria-label="Add payout plan">
        <div className="form-grid">
          <label className="field"><span className="field-label">Payee name *</span>
            <input required maxLength={160} value={form.payee_name}
              onChange={e=>setForm({...form,payee_name:e.target.value})}/></label>
          <label className="field"><span className="field-label">Purpose *</span>
            <input required maxLength={240} value={form.purpose}
              onChange={e=>setForm({...form,purpose:e.target.value})}/></label>
          <label className="field"><span className="field-label">Amount (₹) *</span>
            <input required type="number" min=".01" step=".01" value={form.amount}
              onChange={e=>setForm({...form,amount:e.target.value})}/></label>
          <label className="field"><span className="field-label">Frequency *</span>
            <select value={form.frequency}
              onChange={e=>setForm({...form,frequency:e.target.value})}>
              <option value="recurring">Monthly recurring</option>
              <option value="one_time">One-time</option>
            </select></label>
          <label className="field"><span className="field-label">Start month *</span>
            <input required type="month" value={form.start_month}
              onChange={e=>setForm({...form,start_month:e.target.value})}/></label>
          <label className="field"><span className="field-label">Notes (optional)</span>
            <input maxLength={1000} value={form.notes}
              onChange={e=>setForm({...form,notes:e.target.value})}/></label>
        </div>
        <div className="form-actions"><button className="btn btn-primary"
          type="submit" disabled={busy}>{busy?"Saving…":"Save payout plan"}</button></div>
      </form>
    </section>}
    {view!=="add"&&<section className="content-panel" aria-label="Payout plans">
      <h2>{view==="active"?"Active recurring payouts":"All payout plans"}</h2>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Payee</th><th>Purpose</th><th>Amount</th><th>Frequency</th>
          <th>Status</th><th>Recorded</th><th>Actions</th></tr></thead>
        <tbody>{visible.length===0?<tr><td colSpan={7}>No payout plans yet.</td></tr>:
          visible.map(p=><tr key={p.id}><td>{p.payee_name}</td><td>{p.purpose}</td>
            <td>{money(p.amount_paise)}</td><td>{p.frequency==="recurring"?"Monthly":"One-time"}</td>
            <td>{p.status}</td><td>{p.recorded_periods}</td>
            <td><div className="payout-actions">
              {p.status==="active"&&(p.frequency==="recurring"||p.recorded_periods===0)&&
                <button className="text-action" type="button" onClick={()=>choose(p)}>
                  Record payment</button>}
              {p.frequency==="recurring"&&p.status!=="closed"&&<>
                <button className="text-action" disabled={busy} type="button"
                  onClick={()=>changeStatus(p,p.status==="active"?"paused":"active")}>
                  {p.status==="active"?"Pause":"Resume"}</button>
                <button className="text-action" disabled={busy} type="button"
                  onClick={()=>{if(window.confirm("Close this recurring payout permanently?"))
                    void changeStatus(p,"closed");}}>Close</button>
              </>}
            </div></td></tr>)}</tbody>
      </table></div>
    </section>}
    {view==="all"&&<section className="content-panel" aria-label="Outgoing payment history">
      <h2>Outgoing payment history</h2>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Payee</th><th>Amount</th><th>Period</th><th>Paid on</th>
          <th>Method</th><th>Reference</th></tr></thead>
        <tbody>{history.length===0?<tr><td colSpan={6}>No outgoing payments recorded.</td></tr>:
          history.map(p=><tr key={p.id}><td>{p.payee_name}</td>
            <td>{money(p.amount_paise)}</td><td>{p.period_month.slice(0,7)}</td>
            <td>{p.paid_on}</td><td>{p.payment_method.replace("_"," ")}</td>
            <td>{p.reference_mask}</td></tr>)}</tbody>
      </table></div>
    </section>}
    {selected&&<div className="modal-scrim"><section role="dialog" aria-modal="true"
      aria-labelledby="payout-record-title" className="edit-modal reversal-dialog">
      <div className="content-panel">
        <h2 id="payout-record-title">Record outgoing payment</h2>
        <p className="panel-description">{selected.payee_name} · {money(selected.amount_paise)}
          . Only record a transfer already completed outside this app.</p>
        <form onSubmit={record} aria-label="Record outgoing payout">
          <label className="field"><span className="field-label">Payout month *</span>
            <input type="month" required value={period} onChange={e=>setPeriod(e.target.value)}/></label>
          <label className="field"><span className="field-label">Paid on *</span>
            <input type="date" required value={paidOn} max={today()}
              onChange={e=>setPaidOn(e.target.value)}/></label>
          <label className="field"><span className="field-label">Method *</span>
            <select value={method} onChange={e=>setMethod(e.target.value)}>
              <option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
            </select></label>
          <label className="field"><span className="field-label">Unique transaction/receipt reference *</span>
            <input required minLength={6} maxLength={100} value={reference}
              onChange={e=>setReference(e.target.value)}/></label>
          <label className="field"><input type="checkbox" checked={confirmed}
            onChange={e=>setConfirmed(e.target.checked)}/>
            <span className="field-label">I verified the money was sent externally.</span></label>
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" disabled={busy}
              onClick={()=>{setSelected(null);requestId.current=null;}}>Cancel</button>
            <button type="submit" className="btn btn-primary"
              disabled={!confirmed||busy}>{busy?"Recording…":"Record payout"}</button>
          </div>
        </form>
      </div>
    </section></div>}
  </div>;
}
