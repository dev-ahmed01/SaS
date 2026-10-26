"use client";

type Variable={
  label:string;token:string;hint:string;prospectOnly?:boolean;
};
const variables:Variable[]=[
  {label:"Name",token:"{{name}}",hint:"Registered contact name"},
  {label:"Month",token:"{{month}}",hint:"Current month in IST"},
  {label:"Sponsorship",token:"{{sponsorship}}",
    hint:"Monthly commitment, e.g. ₹500 per month (2 units)",prospectOnly:true},
  {label:"Amount",token:"{{sponsorship_amount}}",
    hint:"Monthly amount in rupees",prospectOnly:true},
  {label:"Units",token:"{{sponsorship_units}}",
    hint:"Number of ₹250 sponsorship units",prospectOnly:true},
];

export function PersonalizationTokens({
  onInsert,showSponsorship=true,
}:{
  onInsert:(token:string)=>void;showSponsorship?:boolean;
}){
  return <div className="comm-personalization" aria-label="Message personalization">
    <span className="comm-personalization-label">Personalize</span>
    <div className="comm-personalization-actions">
      {variables.filter(item=>!item.prospectOnly||showSponsorship).map(item=>
        <button type="button" key={item.token} className="comm-personalization-chip"
          title={item.hint} onClick={()=>onInsert(item.token)}>{item.label}</button>
      )}
    </div>
    <small>Values come from each recipient&apos;s CRM record.</small>
  </div>;
}
