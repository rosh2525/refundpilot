import { useEffect, useState } from 'react';
import { AlertTriangle, Check, FlaskConical, LoaderCircle, Play, XCircle } from 'lucide-react';

type ScenarioId='duplicate_approval'|'competing_approvals'|'stale_policy'|'prompt_injection';
type Scenario={id:ScenarioId;label:string;description:string};
type LabInfo={environment:'isolated_simulation';disclaimer:string;scenarios:Scenario[]};
type LabResult={scenario:ScenarioId;passed:boolean;checks:{label:string;passed:boolean;detail:string}[];requests:{status:number|string;operation_id?:string}[];summary:string;environment:'isolated_simulation';disclaimer:string};
type Api=<T>(path:string,options?:RequestInit)=>Promise<T>;

export function SafetyLab({api}:{api:Api}) {
 const [info,setInfo]=useState<LabInfo|null>(null);
 const [result,setResult]=useState<LabResult|null>(null);
 const [running,setRunning]=useState<ScenarioId|null>(null);
 const [error,setError]=useState('');
 useEffect(()=>{let cancelled=false;api<LabInfo>('/api/lab').then(value=>{if(!cancelled)setInfo(value);}).catch(e=>{if(!cancelled)setError(e.message);});return()=>{cancelled=true;};},[api]);
 async function run(scenario:ScenarioId){setRunning(scenario);setError('');setResult(null);try{setResult(await api<LabResult>('/api/lab/run',{method:'POST',body:JSON.stringify({scenario})}));}catch(e){setError(e instanceof Error?e.message:'The isolated test could not run.');}finally{setRunning(null);}}
 return <section className="safety-lab"><div className="lab-disclosure"><FlaskConical size={22}/><div><strong>Isolated simulation · no PayPal or Gemini calls</strong><p>{info?.disclaimer||'Uses temporary fictional records to exercise approval controls. Merchant records and funds are not changed.'}</p></div></div>{error&&<div className="error" role="alert">{error}</div>}{!info&&!error&&<p className="lab-loading"><LoaderCircle className="spin" size={16}/> Preparing the lab…</p>}<div className="lab-scenarios">{info?.scenarios.map(scenario=><article className="card lab-scenario" key={scenario.id}><h2>{scenario.label}</h2><p>{scenario.description}</p><button className="secondary" disabled={!!running} onClick={()=>run(scenario.id)}>{running===scenario.id?<LoaderCircle className="spin" size={15}/>:<Play size={15}/>} Run simulation</button></article>)}</div>{result&&<section className="card lab-result" aria-live="polite"><div className="section-heading"><h2>{result.passed?<Check size={19}/>:<XCircle size={19}/>} {result.passed?'Checks passed':'Check needs attention'}</h2><span className="badge">Simulated</span></div><div className="lab-result-body"><p>{result.summary}</p><ul>{result.checks.map((check,index)=><li key={index} className={check.passed?'passed':'failed'}>{check.passed?<Check size={16}/>:<AlertTriangle size={16}/>}<div><strong>{check.label}</strong><p>{check.detail}</p></div></li>)}</ul>{result.requests.length>0&&<div className="lab-response-list"><strong>Request outcomes</strong>{result.requests.map((request,index)=><code key={index}>Request {index+1}: {request.status}{request.operation_id?` · operation ${request.operation_id}`:''}</code>)}</div>}<p className="lab-result-disclaimer">{result.disclaimer}</p></div></section>}</section>;
}
