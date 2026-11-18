/** @typedef {{id:number,name:string,sensors:object[],readings:object[]}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,steps:object[]}} Plan */
/** @typedef {{id:number,name:string,status:'queued'|'running'|'completed'|'failed',result:object|null,evidence:object|null}} Trace */
/** @typedef {{level:'full'|'counts'|'summary'|'missing',degraded:boolean,entries:{n:number,reading_row:number,sensor_row:number|null}[]|null,row_counts:object|null,page:{offset:number,limit:number,returned:number,next_cursor:string|null}|null,notice:string|null}} LineagePage */
export {};
