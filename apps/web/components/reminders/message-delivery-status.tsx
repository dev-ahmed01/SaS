"use client";

import {useEffect,useState} from "react";

type Readiness = {
  delivery_enabled:boolean;
  operationally_enabled:boolean;
  awaiting_confirmation_intents:number;
  prepared_reminder_intents:number;
  accepted_by_provider:number;
  sent_confirmed:number;
  delivered_confirmed:number;
  unresolved_attempts:number;
  notice:string;
};

export function MessageDeliveryStatus() {
  const [state,setState]=useState<Readiness|null>(null);
  const [error,setError]=useState(false);
  const [reload,setReload]=useState(0);

  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/admin/messaging/status",{
      cache:"no-store",signal:controller.signal,
    }).then(async result=>{
      if(!result.ok)throw Error("status unavailable");
      return await result.json() as Readiness;
    }).then(data=>{if(!controller.signal.aborted)setState(data);})
      .catch(()=>{if(!controller.signal.aborted)setError(true);});
    return ()=>controller.abort();
  },[reload]);

  return <section className="delivery-status" aria-label="WhatsApp delivery status">
    <div className="review-heading">
      <div>
        <h3>Payment confirmations &amp; delivery</h3>
      </div>
      <button type="button" className="btn btn-secondary" onClick={()=>{setReload(n=>n+1);setError(false);}}>
        Refresh status
      </button>
    </div>
    {error&&<p className="form-error" role="alert">Delivery status unavailable. No messages should be assumed sent.</p>}
    {state&&<>
      <p className="delivery-availability" role="status">
        {state.operationally_enabled
          ?"WhatsApp sending: enabled."
          :"WhatsApp sending: off."}
      </p>
      <div className="delivery-metrics">
        {[
          ["Confirmation intents",state.awaiting_confirmation_intents],
          ["Prepared reminders",state.prepared_reminder_intents],
          ["Provider accepted",state.accepted_by_provider],
          ["Confirmed delivered",state.delivered_confirmed],
          ["Unresolved attempts",state.unresolved_attempts],
        ].map(([label,value])=><div className="delivery-metric" key={label}>
          <span>{label}</span><strong>{value}</strong>
        </div>)}
      </div>
    </>}
  </section>;
}
