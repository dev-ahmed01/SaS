"use client";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "../../components/ui/icon";

export default function LoginPage() {
  const router = useRouter();
  const [email,setEmail] = useState("");
  const [password,setPassword] = useState("");
  const [showPassword,setShowPassword] = useState(false);
  const [busy,setBusy] = useState(false);
  const localDemo = process.env.NODE_ENV === "development"
    && process.env.NEXT_PUBLIC_LOCAL_DEMO_LOGIN_ENABLED === "true";
  const [error,setError] = useState("");
  useEffect(()=>{
    let active=true;
    fetch("/api/admin/session",{cache:"no-store"}).then(r=>{
      if(active && r.ok){router.replace("/dashboard");}
    }).catch(()=>{});
    return ()=>{active=false;};
  },[router]);
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(busy)return;
    setBusy(true);setError("");
    try {
      const result=await fetch("/api/admin/login",{
        method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",
        body:JSON.stringify({email,password})
      });
      if(!result.ok){
        setError(result.status===429?"Too many attempts. Please try again later.":result.status===503?"Sign-in is temporarily unavailable.":result.status===403?"Sign-in request was blocked by origin verification. Check the public URL configuration.":result.status===422?"Enter a valid email address, or enable local demo login to use Admin.":"Unable to sign in. Check your details and try again.");
        return;
      }
      router.replace("/dashboard");
      
    } catch {
      setError("Connection problem. Please try again.");
    } finally {setBusy(false);}
  }
  return <main className="login-layout">
    <section className="login-illustration" aria-label="Sponsor a Salah welcome">
      <div className="login-brand"><Icon name="moon" size={38}/><h1>Sponsor a Salah</h1><p>Masjid Charity Management</p></div>
      <div className="login-mosque" aria-hidden="true"/>
    </section>
    <section className="login-card" aria-labelledby="login-title">
      <span className="login-mark"><Icon name="moon" size={32}/></span>
      <h2 id="login-title">Welcome back</h2>
      <form onSubmit={submit}>
        <div className="login-fields">
          <label className="field"><span className="field-label">{localDemo?"Email or username":"Email address"}</span><input type={localDemo?"text":"email"} autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)} placeholder={localDemo?"Enter Admin or your email":"Enter your email address"}/></label>
          <div className="field"><label className="field-label" htmlFor="admin-password">Password</label><div className="login-password-wrap"><input id="admin-password" type={showPassword?"text":"password"} autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password"/><button className="login-password-toggle" type="button" aria-label={showPassword?"Hide password":"Show password"} aria-pressed={showPassword} title={showPassword?"Hide password":"Show password"} onClick={()=>setShowPassword(value=>!value)}><Icon name={showPassword?"eye-off":"eye"} size={19}/></button></div></div>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy?"Signing in…":"Sign In"}</button>
      </form>
      <p className="login-disclaimer">Authorized Emlen Foundation Admin access only.</p>
    </section>
  </main>;
}
