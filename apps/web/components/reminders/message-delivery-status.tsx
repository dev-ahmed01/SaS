"use client";

import { useEffect, useState } from "react";

type ProviderReadiness = {
  provider:string;
  transport:string;
  delivery_enabled:boolean;
  sender_approved:boolean;
  worker_enabled:boolean;
  monthly_reminders_enabled:boolean;
  credentials_configured:boolean;
  webhook_verified:boolean;
  connection_tested:boolean;
  notice:string;
};

export function MessageDeliveryStatus(){
  const [state,setState]=useState<ProviderReadiness|null>(null);
  const [error,setError]=useState(false);
  const [reload,setReload]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    fetch("/api/admin/communication/provider/saasyto",{
      cache:"no-store",signal:controller.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("Saasyto status unavailable");
      return await response.json() as ProviderReadiness;
    }).then(data=>{if(!controller.signal.aborted)setState(data);})
      .catch(()=>{if(!controller.signal.aborted)setError(true);});
    return ()=>controller.abort();
  },[reload]);
  return <section className="delivery-status" aria-label="Saasyto WhatsApp connection">
    <div className="review-heading"><div>
      <h3>Saasyto WhatsApp campaigns</h3>
      <p>One sending provider for approved campaigns and monthly reminders.</p>
    </div>
      <button type="button" className="btn btn-secondary"
        onClick={()=>{setReload(n=>n+1);setError(false);}}>
        Refresh status
      </button>
    </div>
    {error&&<p role="alert" className="form-error">
      Saasyto readiness unavailable. Do not assume messages were sent.
    </p>}
    {state&&<>
      <p className="delivery-availability" role="status">
        {state.delivery_enabled&&state.sender_approved
          ?"Saasyto transport enabled — submission is not confirmed delivery."
          :"Saasyto sending is disabled. Campaign review remains available."}
      </p>
      <p className="comm-muted">{state.notice}</p>
      <div className="delivery-metrics">
        {[
          ["Sender approved",state.sender_approved?"Yes":"No"],
          ["Monthly 5th/20th scheduler",state.monthly_reminders_enabled?"Enabled":"Off"],
          ["Private sender worker",state.worker_enabled?"Enabled":"Off"],
          ["Credentials configured",state.credentials_configured?"Yes":"No"],
          ["Delivery webhook verified",state.webhook_verified?"Yes":"No"],
        ].map(([label,value])=><div className="delivery-metric" key={label}>
          <span>{label}</span><strong>{value}</strong>
        </div>)}
      </div>
    </>}
  </section>;
}
