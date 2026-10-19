"use client";
import { useEffect,useState } from "react";

type AccountRow={prospect_id:string;name:string;status:string;due_paise:number;verified_paise:number;outstanding_paise:number;fully_paid:boolean};
type Overview={period_month:string;as_of:string;total_sponsors:number;due_paise:number;verified_paise:number;outstanding_paise:number;fully_paid_sponsors:number;items:AccountRow[];offset:number;limit:number};
const money=(paise:number)=>(paise/100).toLocaleString("en-IN",{style:"currency",currency:"INR"});

export function AccountingOverview({outstandingOnly=false}:{outstandingOnly?:boolean}){
  const [month,setMonth]=useState("");
  const [offset,setOffset]=useState(0);
  const [revision,setRevision]=useState(0);
  const [data,setData]=useState<Overview|null>(null);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    const query=new URLSearchParams({limit:"20",offset:String(offset)});
    if(outstandingOnly)query.set("outstanding_only","true");
    if(month)query.set("month",month);
    setLoading(true);
    fetch("/api/admin/accounting/overview?"+query,{cache:"no-store",signal:controller.signal})
      .then(async r=>{if(!r.ok)throw Error("Ledger unavailable");return await r.json() as Overview;})
      .then(v=>{if(!controller.signal.aborted){setData(v);setError("");}})
      .catch(()=>{if(!controller.signal.aborted)setError("Unable to load the monthly ledger.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[month,offset,revision,outstandingOnly]);
  async function refreshStatuses(){
    if(saving)return;
    setSaving(true);setError("");setMessage("");
    try{
      const session=await fetch("/api/admin/session",{cache:"no-store"});
      if(!session.ok)throw Error("Session expired");
      const {csrf_token}=await session.json();
      const result=await fetch("/api/admin/accounting/refresh-statuses",{
        method:"POST",credentials:"same-origin",headers:{"X-CSRF-Token":csrf_token},
      });
      if(!result.ok)throw Error("Refresh unsuccessful");
      const outcome=await result.json();
      setMessage("Checked "+outcome.evaluated+" sponsors; "+outcome.changed+" statuses updated.");
      setRevision(n=>n+1);
    }catch{setError("Status refresh was not confirmed. Please try again.");}
    finally{setSaving(false);}
  }
  return <section className="accounting-workspace" aria-label="Monthly sponsorship ledger">
    <div className="accounting-heading">
      <div><h2>{outstandingOnly?"Outstanding sponsorships":"Monthly sponsorship ledger"}</h2>
</div>
      <label className="field account-month-picker"><span className="field-label">Accounting month (IST)</span>
        <input aria-label="Accounting month (IST)" type="month" max={data?.as_of.slice(0,7)}
          value={month||data?.period_month.slice(0,7)||""}
          onChange={event=>{setMonth(event.target.value);setOffset(0);}}/></label>
    </div>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {message&&<p role="status" className="form-success">{message}</p>}
    <div className="accounting-metrics">
      {[
        ["Monthly commitment",data?money(data.due_paise):"—"],
        ["Verified collections",data?money(data.verified_paise):"—"],
        ["Outstanding",data?money(data.outstanding_paise):"—"],
        ["Fully paid sponsors",data?String(data.fully_paid_sponsors):"—"],
      ].map(([label,value])=><div key={label} className="accounting-metric">
        <span>{label}</span><strong>{value}</strong>
      </div>)}
    </div>
    <div className="accounting-details">
      <div className="accounting-list-heading"><div>
        <h3>{outstandingOnly?"Due from sponsors":"Sponsor commitments"}</h3>
      </div><button type="button" className="btn btn-secondary" disabled={saving||loading}
        onClick={refreshStatuses}>{saving?"Updating…":"Refresh sponsor statuses"}</button></div>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Sponsor</th><th>Due</th><th>Received</th>
          <th>Outstanding</th><th>Lifecycle</th><th>Fully paid</th></tr></thead>
        <tbody>{loading?<tr><td colSpan={6}><div className="empty-state" role="status">Loading monthly accounting…</div></td></tr>
        :!data?.items.length?<tr><td colSpan={6}><div className="empty-state"><h3>No sponsorships for this month</h3><p>No outstanding commitments for this month.</p></div></td></tr>
        :data.items.map(row=><tr key={row.prospect_id}>
          <td><strong className="table-name">{row.name}</strong></td>
          <td>{money(row.due_paise)}</td><td>{money(row.verified_paise)}</td>
          <td>{money(row.outstanding_paise)}</td>
          <td><span className={"status-pill "+row.status}>{row.status==="new"?"New":row.status==="active"?"Active":row.status==="archived"?"Archived":"Inactive"}</span></td>
          <td>{row.fully_paid?"Yes":"No"}</td>
        </tr>)}</tbody>
      </table></div>
      <div className="table-footer paging-footer">
        <span>{data?"Showing "+(data.total_sponsors===0?0:offset+1)+"–"+Math.min(offset+20,data.total_sponsors)+" of "+data.total_sponsors+" sponsors":"Waiting for records"}</span>
        <div className="paging-actions">
          <button type="button" className="btn btn-secondary" disabled={loading||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-20))}>Previous</button>
          <button type="button" className="btn btn-secondary" disabled={loading||!data||offset+20>=data.total_sponsors} onClick={()=>setOffset(v=>v+20)}>Next</button>
        </div>
      </div>
    </div>
  </section>;
}
