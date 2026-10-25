import { useState } from 'react';
import type { Case } from '../types';
const money=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
const readable=(value:string)=>value.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
export function RequestEvidence({request,busy,onAttach}:{request:Case;busy:boolean;onAttach:(file:File)=>Promise<void>}) {
 const [file,setFile]=useState<File|null>(null);
 const assessment=request.proposal?.visual_assessment;
 const economics=request.return_economics;
 return <>
 {!request.evidence&&!request.proposal&&<section className="attachment-review"><label htmlFor="retry-evidence">Optional customer photo</label><input id="retry-evidence" type="file" accept="image/jpeg,image/png" disabled={busy} onChange={event=>setFile(event.target.files?.[0]||null)}/><p>Attach or retry a JPEG/PNG photo on this saved request before reviewing it. Maximum 2 MiB / 12 megapixels. Photos do not prove authenticity, SKU, ownership, or physical damage. Sent to Gemini when analyzed; stored privately with this case.</p><button className="secondary small" disabled={!file||busy} onClick={()=>file&&onAttach(file)}>Attach photo & review</button></section>}
 {request.evidence&&<section className="attachment-review"><span className="eyebrow">CUSTOMER PHOTO · UNVERIFIED CLAIM</span><a href={request.evidence.url} target="_blank" rel="noreferrer"><img className="evidence-thumbnail" src={request.evidence.url} alt="Customer-submitted evidence for this refund request"/></a><small>{request.evidence.mime_type} · {Math.ceil(request.evidence.size_bytes/1024)} KB · metadata stripped by server</small><p>Photos cannot establish authenticity, ownership, the purchased SKU, or physical damage with certainty.</p>{assessment&&<div className="visual-assessment"><strong>AI visual observation</strong><p>{assessment.observation}</p><dl><div><dt>Visible damage</dt><dd>{readable(assessment.damage)}</dd></div><div><dt>Claim consistency</dt><dd>{readable(assessment.consistency)}</dd></div></dl></div>}</section>}
 {economics&&<section className="return-estimate"><span className="eyebrow">OPTIONAL RETURN HANDLING ESTIMATE</span><dl><div><dt>Shipping + restocking</dt><dd>{money(economics.estimated_handling_cents)}</dd></div><div><dt>Requested partial refund</dt><dd>{money(economics.partial_refund_cents)}</dd></div><div><dt>Handling minus partial refund</dt><dd>{money(economics.difference_cents)}</dd></div></dl><p>{economics.disclaimer}</p></section>}
 </>;
}
