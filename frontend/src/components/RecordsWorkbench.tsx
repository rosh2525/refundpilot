import { useMemo, useRef, useState, useCallback, type ReactNode } from 'react';
import { Download, Search, SlidersHorizontal } from 'lucide-react';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import { ClientSideRowModelModule, ClientSideRowModelApiModule, CsvExportModule, TextFilterModule, NumberFilterModule, QuickFilterModule, PaginationModule, TooltipModule, CellStyleModule, themeQuartz, type ColDef, type CsvExportParams } from 'ag-grid-community';
import type { Dashboard } from '../types';
import { safeCsvValue } from '../safeCsv';
import { availableCents, capturedCents } from '../paymentBalance';

type RecordKind = 'payments'|'history'|'activity';
type WorkbenchRow = {id:string;status:string;[key:string]:string|number|null};
const modules = [ClientSideRowModelModule, ClientSideRowModelApiModule, CsvExportModule, TextFilterModule, NumberFilterModule, QuickFilterModule, PaginationModule, TooltipModule, CellStyleModule];
const money = (value:unknown) => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value || 0));
const label = (value:string) => value.toLowerCase().replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const theme = themeQuartz.withParams({fontFamily:'Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',fontSize:12,accentColor:'#207260',foregroundColor:'#355851',backgroundColor:'#ffffff',headerBackgroundColor:'#f1f6f3',borderColor:'#e1e7e8',rowBorder:{color:'#edf1ef'},wrapperBorder:false,headerHeight:40,rowHeight:46});
const currencyColumn = (field:string,headerName:string):ColDef<WorkbenchRow> => ({field,headerName,filter:'agNumberColumnFilter',valueGetter:params=>Number(params.data?.[field]||0)/100,valueFormatter:params=>money(params.value),minWidth:126,type:'numericColumn'});

export function RecordsWorkbench({kind,data,children,onPaymentAction}:{kind:RecordKind;data:Dashboard;children:(ids:string[])=>ReactNode;onPaymentAction?:(id:string)=>void}) {
 const [view,setView] = useState<'grid'|'table'>('grid');
 const [query,setQuery] = useState('');
 const [status,setStatus] = useState('');
 const [displayIds,setDisplayIds]=useState<string[]>([]);
 const captureScope=useCallback((event:{api:{forEachNodeAfterFilterAndSort:(callback:(node:{data?:WorkbenchRow})=>void)=>void}})=>{const ids:string[]=[];event.api.forEachNodeAfterFilterAndSort(node=>{if(node.data)ids.push(node.data.id);});setDisplayIds(previous=>previous.length===ids.length&&previous.every((id,i)=>id===ids[i])?previous:ids);},[]);
 const grid = useRef<AgGridReact<WorkbenchRow>>(null);
 const rows = useMemo<WorkbenchRow[]>(()=>{
  if(kind==='payments')return data.payments.map(p=>({id:p.id,title:p.title,reference:p.capture_id||p.order_id,status:p.status,amount_cents:capturedCents(p),refunded_cents:p.refunded_cents,available_cents:availableCents(p),reserved_cents:p.reserved_cents,action_label:!p.capture_id&&p.approval_url?'Complete checkout':'Review request',can_open:(!p.capture_id&&p.approval_url)||availableCents(p)>0?1:0,date:new Date((p.captured_at||p.created_at)*1000).toISOString()}));
  if(kind==='history')return data.refunds.map(r=>({id:r.id,status:r.status,amount_cents:r.amount_cents,reference:r.paypal_refund_id||'Awaiting confirmation',request_id:r.request_id,date:new Date(r.created_at*1000).toISOString(),customer_request:data.cases.find(c=>c.proposal?.id===r.proposal_id)?.statement||'',payment:data.payments.find(p=>p.id===r.payment_id)?.title||r.payment_id,last_error:r.last_error||''}));
  return data.audit.map(a=>({id:a.id,status:a.action,action:label(a.action),details:Object.entries(a.details).map(([key,value])=>`${key.replaceAll('_',' ')}: ${typeof value==='object'?JSON.stringify(value):String(value)}`).join(' · '),date:new Date(a.created_at*1000).toISOString()}));
 },[kind,data]);
 const statuses = useMemo(()=>[...new Set(rows.map(r=>r.status))].sort(),[rows]);
 const visibleRows = useMemo(()=>rows.filter(row=>!status||row.status===status),[rows,status]);
 const columns = useMemo<ColDef<WorkbenchRow>[]>(()=>{
  const date:ColDef<WorkbenchRow> = {field:'date',headerName:'Date & time',minWidth:185,valueFormatter:p=>p.value?new Date(String(p.value)).toLocaleString():''};
  const statusColumn:ColDef<WorkbenchRow> = {field:'status',headerName:kind==='activity'?'Event type':'Status',minWidth:145,valueFormatter:p=>label(String(p.value||'')),cellRenderer:(p:{value:string})=><span className={'badge '+(p.value?.toLowerCase()==='completed'?'green':['failed','unknown'].includes(p.value)?'amber':'neutral')}>{label(p.value||'')}</span>};
  if(kind==='payments')return [{field:'title',headerName:'Payment',minWidth:215,flex:1.5},{field:'reference',headerName:'Capture / order ID',minWidth:220},currencyColumn('amount_cents','Captured (USD)'),currencyColumn('refunded_cents','Refunded (USD)'),currencyColumn('available_cents','Available (USD)'),currencyColumn('reserved_cents','Reserved (USD)'),statusColumn,date,{colId:'actions',headerName:'Action',minWidth:170,pinned:'right',sortable:false,filter:false,floatingFilter:false,cellRenderer:(p:{data:WorkbenchRow})=><button data-modal-trigger={'payment-'+p.data.id} className="text-button" disabled={!p.data.can_open} onClick={()=>onPaymentAction?.(p.data.id)}>{p.data.action_label} ↗</button>}];
  if(kind==='history')return [{field:'id',headerName:'Operation ID',minWidth:240},currencyColumn('amount_cents','Refund (USD)'),statusColumn,{field:'reference',headerName:'Provider refund ID',minWidth:230},{field:'payment',headerName:'Payment',minWidth:210},{field:'customer_request',headerName:'Customer request',minWidth:320,tooltipField:'customer_request'},{field:'request_id',headerName:'Idempotency key',minWidth:250},{field:'last_error',headerName:'Processing note',minWidth:250},date];
  return [statusColumn,{field:'details',headerName:'Event details',minWidth:410,flex:2,tooltipField:'details'},date,{field:'id',headerName:'Event ID',minWidth:240}];
 },[kind,onPaymentAction]);
 const csvParams = useMemo<CsvExportParams>(()=>({fileName:`refundpilot-${kind}.csv`,exportedRows:'filteredAndSorted',columnKeys:columns.filter(c=>c.field).map(c=>c.field!),processCellCallback:p=>safeCsvValue(p.value),processHeaderCallback:p=>safeCsvValue(p.column.getColDef().headerName||p.column.getColId())}),[kind,columns]);
 return <div className="records-workbench">
  <div className="workbench-controls">
   <div className="view-toggle" role="group" aria-label="Records view"><button className={view==='grid'?'selected':''} onClick={()=>setView('grid')}>Workbench</button><button className={view==='table'?'selected':''} onClick={()=>setView('table')}>Simple view</button></div>
   <><div className="workbench-search"><Search size={15}/><input aria-label={`Search ${kind==='activity'?'audit events':kind}`} placeholder="Search all columns…" value={query} onChange={e=>setQuery(e.target.value)}/></div><select aria-label={kind==='activity'?'Filter event type':'Filter status'} value={status} onChange={e=>setStatus(e.target.value)}><option value="">{kind==='activity'?'All event types':'All statuses'}</option>{statuses.map(value=><option key={value} value={value}>{label(value)}</option>)}</select><button className="secondary small" disabled={!rows.length} onClick={()=>grid.current?.api.exportDataAsCsv(csvParams)}><Download size={14}/> Export CSV</button></>
  </div>
  <div hidden={view!=='grid'}><p className="workbench-hint"><SlidersHorizontal size={13}/> Sort column headings, resize columns, and filter text or USD amounts below. Export includes filtered rows across pages; formula-like cells are escaped.</p><AgGridProvider modules={modules}><div className="workbench-grid"><AgGridReact<WorkbenchRow> ref={grid} onGridReady={captureScope} onModelUpdated={captureScope} theme={theme} rowData={visibleRows} columnDefs={columns} defaultColDef={{sortable:true,resizable:true,filter:'agTextColumnFilter',floatingFilter:true,minWidth:145,flex:1}} quickFilterText={query} pagination paginationPageSize={10} paginationPageSizeSelector={[10,20,50]} getRowId={p=>p.data.id} defaultCsvExportParams={csvParams} enableCellTextSelection ensureDomOrder tooltipShowDelay={300}/></div></AgGridProvider>{kind==='activity'&&<p className="workbench-footnote">Audit records are limited to the latest 40 events returned by the server.</p>}</div>{view==='table'&&<><p className="workbench-hint">{displayIds.length} matching records across all pages, in workbench sort order. Column filters remain active. Switch to Workbench to adjust them.</p>{children(displayIds)}</>}
 </div>;
}
