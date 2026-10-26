import test from 'node:test';
import assert from 'node:assert/strict';
import {readApiResponse,ApiError,OperationLock} from '../src/api.ts';
import {caseTriage,filterCases,recordsByIds,preflightWarnings} from '../src/reviewState.ts';
test('HTML and empty gateway responses give recoverable errors without parser internals',async()=>{
 for(const response of [new Response('<html>Temporary outage</html>',{status:503}),new Response('',{status:502}),new Response('',{status:200})]){
  await assert.rejects(readApiResponse(response,true),e=>e instanceof ApiError&&e.uncertain&&!e.message.includes('Unexpected token')&&e.status===response.status);
 }
 assert.deepEqual(await readApiResponse(new Response('{"ok":true}')),{ok:true});
 await assert.rejects(readApiResponse(new Response('{"detail":"Payment changed."}',{status:409}),true),e=>e.status===409&&e.message==='Payment changed.'&&!e.uncertain);
});
test('operation owner survives unrelated refresh and outdated releases',()=>{
 const lock=new OperationLock(),first=lock.claim();assert.ok(first);assert.equal(lock.claim(),null);
 lock.release(Symbol());assert.equal(lock.claim(),null);lock.release(first);const next=lock.claim();assert.ok(next);lock.release(first);assert.equal(lock.claim(),null);lock.release(next);assert.ok(lock.claim());
});
test('triage and visible selection scope distinguish ready, stale, blocked and refunds',()=>{
 const rows=[{id:'a',statement:'Alpha',proposal:{can_approve:true}},{id:'b',statement:'Beta',proposal:{state:'stale'}},{id:'c',statement:'Gamma',refund:{status:'completed'}},{id:'d',statement:'Delta',analysis_in_progress:true},{id:'e',statement:'Epsilon',proposal:{decision:'deny',state:'blocked'}}];
 assert.deepEqual(rows.map(caseTriage),['ready','needs_review','completed','processing','denied']);
 assert.deepEqual(filterCases(rows,'beta','all').map(r=>r.id),['b']);assert.deepEqual(filterCases(rows,'no-match','all'),[]);assert.deepEqual(filterCases(rows,'','ready').map(r=>r.id),['a']);
});
test('simple records retain the filtered workbench order',()=>{assert.deepEqual(recordsByIds([{id:'a'},{id:'b'},{id:'c'}],['c','a']),[{id:'c'},{id:'a'}]);});
test('preflight warns about age, balance and reservation while retaining the claim',()=>{
 const now=20000000,p={capture_id:'test',captured_at:now-31*86400,status:'COMPLETED',amount_cents:2000,refunded_cents:1000,reserved_cents:500};
 const warnings=preflightWarnings(p,1000,30,now);assert.equal(warnings.length,3);assert.ok(warnings.some(w=>w.includes('30-day')));assert.equal(p.amount_cents,2000);
});
