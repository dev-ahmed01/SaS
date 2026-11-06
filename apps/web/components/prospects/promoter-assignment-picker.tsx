"use client";

import { useEffect, useId, useRef, useState } from "react";

type Promoter = {id:string;full_name:string;is_active:boolean};
type Page = {items:Promoter[];total:number};

/** One searchable assign-promoter control; never truncates assignments to a
 * fixed first-page selector. A typed query alone is never committed as an ID.
 */
export function PromoterAssignmentPicker({
  value,initialName,onChange,
}:{
  value:string;initialName?:string|null;onChange:(id:string)=>void;
}){
  const inputId=useId();
  const listId=inputId+"-results";
  const root=useRef<HTMLDivElement>(null);
  const inputRef=useRef<HTMLInputElement>(null);
  const [query,setQuery]=useState("");
  const [open,setOpen]=useState(false);
  const [items,setItems]=useState<Promoter[]>([]);
  const [count,setCount]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [label,setLabel]=useState(initialName??"");
  const [active,setActive]=useState(0);

  useEffect(()=>{
    if(!open)return;
    const controller=new AbortController();
    const timer=setTimeout(async()=>{
      setBusy(true);setError("");
      try{
        const params=new URLSearchParams({active:"true",limit:"30",q:query.trim()});
        const response=await fetch("/api/admin/promoters?"+params,{
          cache:"no-store",signal:controller.signal,
        });
        if(!response.ok)throw Error("Unable to search promoters.");
        const result=await response.json() as Page;
        if(controller.signal.aborted)return;
        setItems(result.items??[]);setCount(result.total??0);setActive(0);
      }catch{
        if(!controller.signal.aborted){setItems([]);setError("Promoter search is unavailable.");}
      }finally{
        if(!controller.signal.aborted)setBusy(false);
      }
    },query.trim()?250:0);
    return()=>{clearTimeout(timer);controller.abort();};
  },[open,query]);

  function choose(id:string,name:string){
    onChange(id);setLabel(name);setQuery("");setOpen(false);setActive(0);
    inputRef.current?.blur();
  }
  const shown=[{id:"",full_name:"Unassigned",is_active:true},...items];
  return <div className="field promoter-picker" ref={root}
    onBlur={event=>{
      if(!event.currentTarget.contains(event.relatedTarget))setOpen(false);
    }}>
    <label className="field-label" htmlFor={inputId}>Assign promoter</label>
    <div className="promoter-picker-input">
      <input ref={inputRef} id={inputId} type="text" role="combobox" aria-autocomplete="list"
        aria-controls={listId} aria-expanded={open}
        aria-activedescendant={open?listId+"-option-"+active:undefined}
        placeholder="Search or assign a promoter…" autoComplete="off"
        value={open?query:(value?label:"")}
        onFocus={()=>{setOpen(true);setQuery("");}}
        onChange={event=>{setQuery(event.target.value);setOpen(true);}}
        onKeyDown={event=>{
          if(event.key==="Escape"){event.preventDefault();setOpen(false);event.currentTarget.blur();}
          if(event.key==="ArrowDown"){event.preventDefault();setActive(n=>Math.min(n+1,shown.length-1));}
          if(event.key==="ArrowUp"){event.preventDefault();setActive(n=>Math.max(n-1,0));}
          if(event.key==="Enter"&&open&&shown[active]){
            event.preventDefault();choose(shown[active].id,shown[active].full_name);
          }
        }}/>
      <span className="promoter-picker-caret" aria-hidden="true">⌄</span>
    </div>
    {open&&<div className="promoter-picker-menu" id={listId} role="listbox"
      aria-label="Active promoters">
      {busy&&<p className="promoter-picker-status" role="status">Searching promoters…</p>}
      {!busy&&error&&<p className="promoter-picker-status" role="alert">{error}</p>}
      {!busy&&!error&&<>
        {shown.map((person,index)=><button key={person.id||"unassigned"}
          type="button" role="option" id={listId+"-option-"+index}
          aria-selected={value===person.id} className={
            "promoter-picker-option"+(index===active?" is-highlighted":"")
          } onMouseDown={event=>event.preventDefault()}
          onMouseEnter={()=>setActive(index)}
          onClick={()=>choose(person.id,person.full_name)}>
            <span>{person.full_name}</span>
            {value===person.id&&<span aria-hidden="true">✓</span>}
          </button>)}
        {!items.length&&query.trim()&&<p className="promoter-picker-status">No matching active promoters.</p>}
        {count>30&&<p className="promoter-picker-status">
          {count} matches. Refine your search to find the right promoter.
        </p>}
      </>}
    </div>}
  </div>;
}
