"use client";

import { useEffect, useState } from "react";

export function IstClock(){
  const [current,setCurrent]=useState<Date|null>(null);
  const [verified,setVerified]=useState(false);
  useEffect(()=>{
    let disposed=false;
    let serverTime=0;
    let syncedAt=0;
    async function sync(){
      try{
        const r=await fetch("/api/admin/communication/clock",{cache:"no-store"});
        if(!r.ok)throw Error("clock unavailable");
        const body=await r.json() as {now_ist:string};
        const epoch=Date.parse(body.now_ist);
        if(!Number.isFinite(epoch))throw Error("invalid server clock");
        if(!disposed){
          serverTime=epoch;syncedAt=performance.now();setVerified(true);
          setCurrent(new Date(epoch));
        }
      }catch{
        if(!disposed){setVerified(false);setCurrent(new Date());}
      }
    }
    void sync();
    const interval=setInterval(()=>{
      if(disposed)return;
      setCurrent(serverTime?new Date(serverTime+performance.now()-syncedAt):new Date());
    },15000);
    const onVisible=()=>{if(document.visibilityState==="visible")void sync();};
    document.addEventListener("visibilitychange",onVisible);
    return ()=>{
      disposed=true;clearInterval(interval);
      document.removeEventListener("visibilitychange",onVisible);
    };
  },[]);
  const time=current?.toLocaleString("en-IN",{
    timeZone:"Asia/Kolkata",day:"2-digit",month:"short",year:"numeric",
    hour:"2-digit",minute:"2-digit",hour12:true,
  })??"Loading time";
  return <time className="topbar-ist-clock" dateTime={current?.toISOString()}
    title={verified?"Time synchronized with Foundation server (Asia/Kolkata)":
      "Showing device time in Asia/Kolkata until server sync is available"}>
    <span className="topbar-clock-dot" aria-hidden="true"/>
    {time} <span className="topbar-ist-label">IST</span>
  </time>;
}
