"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Month = {
  period_month:string;due_paise:number;contributions_paise:number;
  payout_planned_paise:number;payout_disbursed_paise:number;
};
type Activity = {
  kind:string;title:string;amount_paise:number|null;at:string;href:string;
};
type Overview = {
  as_of_ist:string;period_month:string;sponsors_total:number;
  sponsors_new:number;sponsors_active:number;sponsors_inactive:number;
  promoters_active:number;fully_paid_sponsors:number;unpaid_sponsors:number;
  due_paise:number;recorded_contributions_paise:number;outstanding_paise:number;
  recurring_payouts_active:number;payout_planned_paise:number;
  payout_disbursed_paise:number;payout_outstanding_paise:number;
  reminder_batches_prepared:number;acknowledgments_awaiting_setup:number;
  whatsapp_deliveries_confirmed:number;months:Month[];activity:Activity[];
  notice:string;
};
const money=(paise:number)=>(paise/100).toLocaleString("en-IN",{
  style:"currency",currency:"INR",minimumFractionDigits:2,maximumFractionDigits:2,
});
const monthLabel=(value:string)=>new Intl.DateTimeFormat("en-IN",{
  month:"short",year:"numeric",timeZone:"UTC",
}).format(new Date(value.slice(0,10)+"T00:00:00Z"));
const dateLabel=(value:string)=>new Intl.DateTimeFormat("en-IN",{
  dateStyle:"medium",timeZone:"Asia/Kolkata",
}).format(new Date(value));
const barWidth=(value:number,maximum:number)=>{
  return (maximum>0?Math.round(value/maximum*100):0)+"%";
};

function Metric({label,value,detail,href}:{
  label:string;value:string;detail:string;href:string;
}){
  return <Link className="dashboard-metric" href={href}>
    <span>{label}</span><strong>{value}</strong><small>{detail}</small>
  </Link>;
}

export function DashboardLive(){
  const [data,setData]=useState<Overview|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError("");
    fetch("/api/admin/dashboard",{cache:"no-store",signal:controller.signal})
      .then(async response=>{
        if(!response.ok)throw Error("Dashboard unavailable");
        return await response.json() as Overview;
      })
      .then(result=>{if(!controller.signal.aborted)setData(result);})
      .catch(()=>{
        if(!controller.signal.aborted){
          setData(null);setError("Unable to load the current Dashboard. Please retry.");
        }
      })
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[revision]);

  if(error){
    return <section className="dashboard-error" aria-label="Foundation dashboard">
      <p role="alert">{error}</p>
      <button type="button" className="btn btn-primary"
        onClick={()=>setRevision(x=>x+1)}>Retry</button>
    </section>;
  }
  if(loading||!data){
    return <section className="dashboard-loading" role="status"
      aria-label="Foundation dashboard">Loading current records…</section>;
  }
  const scale=Math.max(1,...data.months.map(m=>Math.max(
    m.due_paise,m.contributions_paise,m.payout_planned_paise,
    m.payout_disbursed_paise,
  )));
  return <section className="dashboard-live" aria-label="Foundation dashboard">
    <div className="dashboard-topline">
      <div>
        <h2>Overview <span className="dashboard-period">· {monthLabel(data.period_month)}</span></h2>
        <p>Figures are calculated from recorded Foundation activity, as of {data.as_of_ist} (IST).</p>
      </div>
      <button className="btn btn-secondary" type="button"
        onClick={()=>setRevision(x=>x+1)}>Refresh figures</button>
    </div>
    <div className="dashboard-metrics">
      <Metric label="Registered sponsors" value={String(data.sponsors_total)}
        detail={data.sponsors_active+" active · "+data.sponsors_new+" new"}
        href="/prospects/all"/>
      <Metric label="Recorded contributions" value={money(data.recorded_contributions_paise)}
        detail="Applied to this month · excluding reversals" href="/collections/all"/>
      <Metric label="Outstanding sponsorships" value={money(data.outstanding_paise)}
        detail={data.unpaid_sponsors+" currently unpaid sponsors"} href="/collections/all"/>
      <Metric label="Active recurring payouts" value={String(data.recurring_payouts_active)}
        detail={money(data.payout_planned_paise)+" planned this month"} href="/payouts/active"/>
    </div>
    <div className="dashboard-dual">
      <section className="dashboard-panel" aria-label="Sponsorship finances">
        <div className="dashboard-section-head">
          <h3>Incoming commitments</h3><Link href="/collections/all">View collections →</Link>
        </div>
        <dl className="dashboard-facts">
          <div><dt>Monthly amount due</dt><dd>{money(data.due_paise)}</dd></div>
          <div><dt>Admin-recorded contributions</dt><dd>{money(data.recorded_contributions_paise)}</dd></div>
          <div><dt>Fully paid sponsors</dt><dd>{data.fully_paid_sponsors}</dd></div>
        </dl>
        <p className="dashboard-caption">An unpaid commitment can remain outstanding after a valid ₹250-tier receipt. These are Admin-attested entries, not independently reconciled bank balances.</p>
      </section>
      <section className="dashboard-panel" aria-label="Outgoing payouts">
        <div className="dashboard-section-head">
          <h3>Outgoing commitments</h3><Link href="/payouts/all">View payouts →</Link>
        </div>
        <dl className="dashboard-facts">
          <div><dt>Planned for this month</dt><dd>{money(data.payout_planned_paise)}</dd></div>
          <div><dt>Disbursements attested</dt><dd>{money(data.payout_disbursed_paise)}</dd></div>
          <div><dt>Not yet recorded as paid</dt><dd>{money(data.payout_outstanding_paise)}</dd></div>
        </dl>
        <p className="dashboard-caption">Creating a payout plan does not send funds. Payments are recorded separately by Admin.</p>
      </section>
    </div>
    <section className="dashboard-panel dashboard-trends" aria-label="Six-month financial trends">
      <div className="dashboard-section-head"><h3>Last six months</h3>
        <span>INR · monthly commitments and evidence</span></div>
      <div className="dashboard-legend">
        <span><i className="dashboard-dot due"/> Sponsorship due</span>
        <span><i className="dashboard-dot collected"/> Recorded contributions</span>
        <span><i className="dashboard-dot planned"/> Planned payout</span>
        <span><i className="dashboard-dot disbursed"/> Attested disbursement</span>
      </div>
      <div className="dashboard-trend-rows">
        {data.months.map(item=><div className="dashboard-trend-row" key={item.period_month}>
          <span>{monthLabel(item.period_month)}</span>
          <div className="dashboard-bars" aria-label={
            monthLabel(item.period_month)+": due "+money(item.due_paise)+
            ", recorded "+money(item.contributions_paise)+
            ", payout planned "+money(item.payout_planned_paise)+
            ", disbursed "+money(item.payout_disbursed_paise)
          }>
            {[
              ["due",item.due_paise],["collected",item.contributions_paise],
              ["planned",item.payout_planned_paise],["disbursed",item.payout_disbursed_paise],
            ].map(([kind,value])=><div className="dashboard-track" key={kind}>
              <span className={"dashboard-bar "+kind}
                style={{width:barWidth(Number(value),scale)}}/>
            </div>)}
          </div>
          <strong>{money(item.contributions_paise)}</strong>
        </div>)}
      </div>
      <p className="dashboard-caption">Bars use one consistent scale; the right column shows recorded incoming contributions.</p>
    </section>
    <div className="dashboard-dual dashboard-bottom">
      <section className="dashboard-panel" aria-label="Recent activity">
        <div className="dashboard-section-head"><h3>Recent activity</h3></div>
        {data.activity.length===0?
          <p className="dashboard-empty">No financial or reminder activity has been recorded yet.</p>
          :<ul className="dashboard-activity">{data.activity.map((entry,index)=>
            <li key={entry.at+entry.kind+index}>
              <Link href={entry.href}>
                <span><strong>{entry.title}</strong>
                  <small>{dateLabel(entry.at)}</small></span>
                {entry.amount_paise!==null?<b>{money(entry.amount_paise)}</b>:null}
              </Link>
            </li>)}</ul>}
      </section>
      <section className="dashboard-panel" aria-label="Operational status">
        <div className="dashboard-section-head"><h3>Operations</h3></div>
        <dl className="dashboard-facts">
          <div><dt>Inactive sponsors</dt><dd>{data.sponsors_inactive}</dd></div>
          <div><dt>Active promoters</dt><dd>{data.promoters_active}</dd></div>
          <div><dt>Reminder batches prepared this month</dt><dd>{data.reminder_batches_prepared}</dd></div>
          <div><dt>Confirmation intents awaiting setup</dt><dd>{data.acknowledgments_awaiting_setup}</dd></div>
          <div><dt>Provider-confirmed WhatsApp deliveries (all time)</dt>
            <dd>{data.whatsapp_deliveries_confirmed}</dd></div>
        </dl>
        <p className="dashboard-caption">Preparing a reminder or a confirmation is not equivalent to delivery.</p>
        <Link className="dashboard-reminder-link" href="/reminders/whatsapp">
          Review reminders and delivery →
        </Link>
      </section>
    </div>
    <p className="dashboard-disclaimer">{data.notice}</p>
  </section>;
}
