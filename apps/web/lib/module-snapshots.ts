/** Memory-only, short-lived CRM list snapshots used during client navigation.
 * Never stored on disk, never used as an authorization/financial decision,
 * and every mount still makes a fresh no-store request to the protected API.
 * Sign-out forces a full navigation, clearing this module-scoped memory.
 */
const MAX_AGE_MS=30_000;
const MAX_ITEMS=32;
type Snapshot={value:unknown;at:number};
const snapshots=new Map<string,Snapshot>();

export function recentSnapshot<T>(key:string):T|null {
  const entry=snapshots.get(key);
  if(!entry)return null;
  if(Date.now()-entry.at>MAX_AGE_MS){
    snapshots.delete(key);return null;
  }
  return entry.value as T;
}

export function rememberSnapshot<T>(key:string,value:T):void {
  snapshots.delete(key);
  snapshots.set(key,{value,at:Date.now()});
  if(snapshots.size>MAX_ITEMS){
    const oldest=snapshots.keys().next().value;
    if(oldest!==undefined)snapshots.delete(oldest);
  }
}

export function invalidateSnapshots(prefix:string):void {
  for(const key of snapshots.keys())if(key.startsWith(prefix))snapshots.delete(key);
}
