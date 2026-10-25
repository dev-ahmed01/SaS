export type Channel="whatsapp"|"email";
export type Audience="prospects"|"promoters"|"both";
export type Segment="all"|"active"|"inactive"|"unpaid";
export type Category="update"|"reminder"|"announcement"|"thank_you"|"invitation"|"other";
export type Template={
  id:string;name:string;channel:Channel;category:Category;
  subject:string|null;body:string;provider_template_id:string|null;
  version:number;archived:boolean;created_at:string;
};
export type Campaign={
  id:string;title:string;channel:Channel;audience:Audience;segment:Segment;
  category:Category;subject:string|null;body:string;
  planned_for:string|null;status:"draft"|"scheduled"|"cancelled";
  eligible_snapshot:number;candidate_snapshot:number;created_at:string;
};
export type Rule={
  id:string;name:string;trigger_kind:string;channel:Channel;
  audience:Audience;segment:Segment;template_id:string;
  active:false;created_at:string;
};
export type Preview={
  candidate_count:number;eligible_count:number;suppressed_count:number;
  sample_names:string[];channel_ready:boolean;notice:string;as_of_ist:string;
};
export const categoryOptions:[
  Category,string
][]=[
  ["update","Update"],["reminder","Reminder"],["announcement","Announcement"],
  ["thank_you","Thank-you"],["invitation","Invitation"],["other","Other"],
];
export const audienceOptions:[Audience,string][]=[
  ["prospects","Prospects"],["promoters","Promoters"],["both","Both"],
];
export const segmentOptions:[Segment,string][]=[
  ["all","All contacts"],["active","Active"],["inactive","Inactive"],
  ["unpaid","Unpaid / follow-up"],
];
export const triggerOptions:[string,string][]=[
  ["monthly_sponsor","Monthly sponsor follow-up (5th IST)"],
  ["monthly_promoter","Promoter summary (20th IST)"],
  ["payment_received","Payment recorded"],
  ["prospect_stage_changed","Prospect stage changed"],
  ["scheduled_date","Scheduled date"],
  ["manual","Manual event"],
];
export async function apiGet<T>(path:string):Promise<T>{
  const res=await fetch("/api/admin/communication"+path,{cache:"no-store"});
  if(!res.ok)throw Error("Could not load communication information.");
  return await res.json() as T;
}
export async function apiWrite<T>(
  path:string,method:"POST"|"PATCH"|"DELETE",payload?:unknown,
):Promise<T>{
  const session=await fetch("/api/admin/session",{cache:"no-store"});
  if(!session.ok)throw Error("Session expired. Please sign in again.");
  const csrf=(await session.json()).csrf_token as string;
  const response=await fetch("/api/admin/communication"+path,{
    method,credentials:"same-origin",
    headers:{"X-CSRF-Token":csrf,...(payload!==undefined?{"Content-Type":"application/json"}:{})},
    body:payload===undefined?undefined:JSON.stringify(payload),
  });
  if(!response.ok){
    // The API uses fixed, safe error descriptions for Saasyto approval.
    // Only surface this narrow allowlist; never display provider replies,
    // API tokens, contact numbers, or arbitrary backend error strings.
    if(path.includes("/saasyto")&&[409,503].includes(response.status)){
      const safeReasons:Record<string,string>={
        "Local pilot requires one consented, allowlisted recipient":
          "The eligible contact is not the one permitted in local WhatsApp test settings. Check SAASYTO_LOCAL_TEST_PHONE and the contact's WhatsApp number.",
        "Older campaigns require new approval plans":
          "This campaign was created before WhatsApp sending was enabled. Create a new campaign.",
        "Refresh recipient check before approval":
          "Your recipient check is missing or expired. Click Check recipients again.",
        "Audience changed; review again":
          "The eligible audience changed. Click Check recipients again.",
        "Campaign already approved or completed":
          "This campaign already has a send approval or attempt. Check results before doing anything else.",
        "Saasyto dispatch is disabled":
          "WhatsApp sending is disabled in the API configuration.",
        "Saasyto sending is disabled":
          "WhatsApp sending is disabled in the API configuration.",
        "Manual send requires local test mode":
          "Manual sending is only available in the guarded local WhatsApp test.",
        "Campaign not eligible for one-phone send":
          "Only one approved, pending local test contact can be sent immediately.",
        "Already attempted or no pending send":
          "The message was already attempted, or there is nothing pending. Check results instead of resending.",
        "Scheduled campaign is not yet due":
          "This campaign is scheduled for later and cannot be sent now.",
        "Approve the campaign before sending":
          "Check recipients and approve this campaign before submitting it.",
        "Campaign cannot use Saasyto":
          "This campaign cannot be sent through Saasyto.",
      };
      try {
        const body=await response.json() as {detail?:unknown};
        if(typeof body.detail==="string"&&safeReasons[body.detail]){
          throw Error(safeReasons[body.detail]);
        }
      }catch(error){if(error instanceof Error&&error.message!==""){
        if(Object.values(safeReasons).includes(error.message))throw error;
      }}
    }
    if(response.status===409)throw Error("This record was changed or already exists. Refresh and retry.");
    if(response.status===422)throw Error("Please review the message, audience and schedule.");
    throw Error("The action could not be confirmed.");
  }
  return response.status===204?null as T:await response.json() as T;
}
export function istDisplay(date:string|null|undefined){
  if(!date)return "—";
  return new Date(date).toLocaleString("en-GB",{
    day:"2-digit",month:"2-digit",year:"2-digit",hour:"2-digit",minute:"2-digit",
    timeZone:"Asia/Kolkata",hour12:true,
  })+" IST";
}
export function istLocalInput(date:Date){
  return new Intl.DateTimeFormat("sv-SE",{
    timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit",
    hour:"2-digit",minute:"2-digit",hourCycle:"h23",
  }).format(date).replace(" ","T");
}
