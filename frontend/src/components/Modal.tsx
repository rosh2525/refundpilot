import { useLayoutEffect, useRef, type ReactNode } from 'react';

export function Modal({titleId,busy=false,returnFocusId,onDismiss,children}:{titleId:string;busy?:boolean;returnFocusId?:string;onDismiss:()=>void;children:ReactNode}) {
 const ref=useRef<HTMLDialogElement>(null);
 useLayoutEffect(()=>{
  const dialog=ref.current!;
  const trigger=document.activeElement instanceof HTMLElement&&document.activeElement!==document.body?document.activeElement:null;
  const overflow=document.body.style.overflow;
  dialog.showModal();
  document.body.style.overflow='hidden';
  dialog.querySelector<HTMLElement>('[data-initial-focus]')?.focus();
  return ()=>{
   dialog.close();document.body.style.overflow=overflow;
   // Grid cells can be recreated while a modal opens or dashboard polling runs.
   const replacement=returnFocusId?document.querySelector<HTMLElement>(`[data-modal-trigger="${CSS.escape(returnFocusId)}"]`):null;
   const target=trigger?.isConnected?trigger:replacement||document.querySelector<HTMLElement>('[data-modal-fallback-focus]');
   target?.focus({preventScroll:true});
  };
 },[]);
 return <dialog ref={ref} className="modal-overlay accessible-dialog" aria-modal="true" aria-labelledby={titleId}
  onCancel={event=>{event.preventDefault();if(!busy)onDismiss();}}
  onClick={event=>{if(event.target===event.currentTarget&&!busy)onDismiss();}}
  onKeyDown={event=>{
   if(event.key!=='Tab')return;
   const targets=Array.from(ref.current!.querySelectorAll<HTMLElement>('button,a[href],input,select,textarea,summary,[tabindex]'))
    .filter(el=>el.tabIndex>=0&&!el.matches(':disabled')&&el.getClientRects().length>0);
   const first=targets[0],last=targets[targets.length-1];
   if(!first){event.preventDefault();ref.current?.focus();return;}
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }}><section className="modal">{children}</section></dialog>;
}
