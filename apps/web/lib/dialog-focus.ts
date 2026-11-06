"use client";

import { useEffect, useRef } from "react";

/** Keep keyboard focus inside a destructive-action dialog and return it to the
 * opener when the dialog closes. Works for native buttons, inputs and links.
 * The dialog must have role="dialog", aria-modal and a heading label.
 */
export function useDialogFocus<T extends HTMLElement>(
  isOpen: boolean, onEscape: () => void,
){
  const dialogRef=useRef<T>(null);
  const closeRef=useRef(onEscape);
  closeRef.current=onEscape;
  useEffect(()=>{
    if(!isOpen)return;
    const opener=document.activeElement instanceof HTMLElement?document.activeElement:null;
    const root=dialogRef.current;
    if(!root)return;
    const focusable=()=>Array.from(root.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),'+
      'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
    )).filter(element=>{
      const style=getComputedStyle(element);
      return style.visibility!=="hidden"&&style.display!=="none"&&element.getClientRects().length>0;
    });
    (focusable()[0]??root).focus({preventScroll:true});
    const onKey=(event:KeyboardEvent)=>{
      if(event.key==="Escape"){
        event.preventDefault();event.stopPropagation();
        closeRef.current();return;
      }
      if(event.key!=="Tab")return;
      const items=focusable();
      if(!items.length){event.preventDefault();root.focus();return;}
      const first=items[0],last=items[items.length-1];
      if(event.shiftKey && (document.activeElement===first||!root.contains(document.activeElement))){
        event.preventDefault();last.focus();
      }else if(!event.shiftKey&&(document.activeElement===last||!root.contains(document.activeElement))){
        event.preventDefault();first.focus();
      }
    };
    document.addEventListener("keydown",onKey,true);
    return()=>{
      document.removeEventListener("keydown",onKey,true);
      if(opener?.isConnected)opener.focus({preventScroll:true});
    };
  },[isOpen]);
  return dialogRef;
}
