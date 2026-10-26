export class ApiError extends Error {
 status:number; uncertain:boolean;
 constructor(message:string,status:number,uncertain=false){super(message);this.name='ApiError';this.status=status;this.uncertain=uncertain;}
}
export async function readApiResponse<T>(response:Response, mutation=false):Promise<T>{
 let raw:string;try{raw=await response.text();}catch{throw new ApiError('Connection interrupted while reading the response. Refresh to check saved progress before trying again.',response.status,mutation);}
 let data:unknown;
 try{data=raw?JSON.parse(raw):null;}catch{/* Gateway pages are not application errors. */}
 if(!response.ok){
  const detail=data&&typeof data==='object'&&'detail' in data?data.detail:null;
  const message=typeof detail==='string'?detail:response.status===401?'Sign in to the merchant workspace again.':response.status===429?'Too many requests. Please wait before trying again.':response.status>=500?'The service is temporarily unavailable. Refresh to check saved progress before trying again.':`The request could not be completed (HTTP ${response.status}). Check the form and try again.`;
  throw new ApiError(message,response.status,mutation&&response.status>=500);
 }
 if(data===undefined||data===null)throw new ApiError('The service returned an incomplete response. Refresh to check saved progress before trying again.',response.status,mutation);
 return data as T;
}
export class OperationLock {
 private active:symbol|null=null;
 claim(){if(this.active)return null;return this.active=Symbol();}
 release(token:symbol){if(this.active===token)this.active=null;}
}
