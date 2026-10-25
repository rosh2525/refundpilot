import { useState } from 'react';
import type { Case } from '../types';
const money=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
const readable=(value:string)=>value.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
export function RequestEvidence({request,busy,onAttach,onRemove}:{request:Case;busy:boolean;onAttach:(file:File)=>Promise<void>;onRemove:()=>Promise<void>}) {
 const [file,setFile]=useState<File|null>(null);
 const [removing,setRemoving]=useState(false);
 const assessment=request.proposal?.state!=='superseded'?request.proposal?.visual_assessment:null;
 const economics=request.return_economics;
 const inputId=`retry-evidence-${request.id}`;
 return <>
 {request.evidence&&<section className="attachment-review"><span className="eyebrow">CUSTOMER PHOTO · UNVERIFIED CLAIM</span><a href={request.evidence.url} target="_blank" rel="noreferrer"><img className="evidence-thumbnail" src={`${request.evidence.url}?v=${request.evidence.sha256}`} alt="Customer-submitted evidence for this refund request"/></a><small>{request.evidence.mime_type} · {Math.ceil(request.evidence.size_bytes/1024)} KB · metadata stripped by server</small><p>Photos cannot establish authenticity, ownership, the purchased SKU, or physical damage with certainty.</p>{assessment&&<div className="visual-assessment"><strong>AI visual observation</strong><p>{assessment.observation}</p><dl><div><dt>Visible damage</dt><dd>{readable(assessment.damage)}</dd></div><div><dt>Claim consistency</dt><dd>{readable(assessment.consistency)}</dd></div></dl></div>}</section>}
 {!request.refund&&<section className="attachment-review">
  <label htmlFor={inputId}>{request.evidence?'Replace customer photo':request.evidence_replacement_required?'Replacement customer photo':'Optional customer photo'}</label>
  <input id={inputId} type="file" accept="image/jpeg,image/png" disabled={busy} onChange={event=>setFile(event.target.files?.[0]||null)}/>
  <p>JPEG/PNG · maximum 2 MiB / 12 megapixels. Photos are unverified customer claims. Sent to Gemini when analyzed; stored privately with this case. Changing a photo invalidates earlier recommendations and requires a fresh review.</p>
  {request.evidence_replacement_required&&<p role="status">The previous photo was removed. Attach a replacement before this case can be approved; removal does not enable text-only approval.</p>}
  <button className="secondary small" disabled={!file||busy} onClick={()=>file&&onAttach(file)}>{request.evidence?'Replace photo & review':'Attach photo & review'}</button>
  {request.evidence&&(!removing?<button className="text-button" disabled={busy} onClick={()=>setRemoving(true)}>Remove photo</button>:<div><p>Remove the stored photo? Its hash remains in the audit trail. This case will require a replacement photo and fresh review before approval.</p><button className="secondary small" disabled={busy} onClick={onRemove}>Confirm photo removal</button><button className="text-button" disabled={busy} onClick={()=>setRemoving(false)}>Keep photo</button></div>)}
 </section>}
 {economics&&<section className="return-estimate"><span className="eyebrow">OPTIONAL RETURN HANDLING ESTIMATE</span><dl><div><dt>Shipping + restocking</dt><dd>{money(economics.estimated_handling_cents)}</dd></div><div><dt>Requested partial refund</dt><dd>{money(economics.partial_refund_cents)}</dd></div><div><dt>Handling minus partial refund</dt><dd>{money(economics.difference_cents)}</dd></div></dl><p>{economics.disclaimer}</p></section>}
 </>;
}
