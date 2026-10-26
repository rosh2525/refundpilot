import type { Case, Payment } from './types';
import { availableCents } from './paymentBalance.ts';
export const triageLabels={all:'All',needs_review:'Needs review',ready:'Ready',processing:'Processing',completed:'Completed',denied:'Denied'};
export type Triage=keyof typeof triageLabels;
export function caseTriage(c:Case):Triage{
 if(c.refund){if(c.refund.status==='completed')return 'completed';if(!['failed','cancelled'].includes(c.refund.status))return 'processing';return 'needs_review';}
 if(c.analysis_in_progress)return 'processing';
 if(c.proposal?.can_approve)return 'ready';
 if(c.proposal?.decision==='deny'&&c.proposal.state!=='superseded')return 'denied';
 return 'needs_review';
}
export function filterCases(cases:Case[],query:string,triage:Triage){return cases.filter(c=>(triage==='all'||caseTriage(c)===triage)&&(c.statement+' '+c.id).toLowerCase().includes(query.trim().toLowerCase()));}
export function recordsByIds<T extends {id:string}>(rows:T[],ids:string[]){const byId=new Map(rows.map(row=>[row.id,row]));return ids.flatMap(id=>{const row=byId.get(id);return row?[row]:[];});}
export function preflightWarnings(payment:Payment|undefined,amountCents:number,windowDays:number,now=Date.now()/1000){
 if(!payment)return [];
 const warnings=[];
 if(payment.captured_at===null||now-payment.captured_at>windowDays*86400)warnings.push(`Outside the ${windowDays}-day merchant refund window.`);
 if(payment.captured_at!==null&&payment.captured_at>now+60)warnings.push('Capture date needs reconciliation.');
 if(amountCents>availableCents(payment))warnings.push('Requested refund exceeds the available balance.');
 if(payment.reserved_cents>0)warnings.push('An earlier refund is reserved or unresolved.');
 if(!payment.capture_id||!['COMPLETED','PARTIALLY_REFUNDED'].includes(payment.status))warnings.push('This payment is not currently refundable.');
 return warnings;
}
