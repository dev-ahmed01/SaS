/** Visible CRM dates are DD/MM/YY; API and database dates remain ISO 8601. */
export function formatCRMDate(value:string|null|undefined):string {
  if(!value)return "—";
  const parsed=new Date(/^\d{4}-\d{2}-\d{2}$/.test(value)?value+"T12:00:00Z":value);
  if(Number.isNaN(parsed.getTime()))return "—";
  return new Intl.DateTimeFormat("en-GB",{
    day:"2-digit",month:"2-digit",year:"2-digit",timeZone:"Asia/Kolkata",
  }).format(parsed);
}

export function dateInputFromISO(value:string):string {
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return "";
  const [year,month,day]=value.split("-");
  return `${day}/${month}/${year.slice(2)}`;
}

export function dateInputToISO(value:string):string|null {
  const match=/^(\d{2})\/(\d{2})\/(\d{2})$/.exec(value.trim());
  if(!match)return null;
  const day=Number(match[1]),month=Number(match[2]),year=2000+Number(match[3]);
  const check=new Date(Date.UTC(year,month-1,day));
  if(check.getUTCFullYear()!==year||check.getUTCMonth()!==month-1||check.getUTCDate()!==day)return null;
  return `${year}-${match[2]}-${match[1]}`;
}

export function todayISTISO():string {
  const parts=new Intl.DateTimeFormat("en-GB",{
    timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit",
  }).formatToParts(new Date());
  const field=(name:string)=>parts.find(p=>p.type===name)?.value??"";
  return `${field("year")}-${field("month")}-${field("day")}`;
}
