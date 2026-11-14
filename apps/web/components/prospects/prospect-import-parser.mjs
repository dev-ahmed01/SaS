export const COLUMNS=["First name","Last name","Country Code","Mobile(Whatsapp)","Email","City","Sponsorship","Start Month","Promoter"];
const aliases=new Map([["first name","first"],["last name","last"],["country code","code"],["mobile(whatsapp)","mobile"],["mobile (whatsapp)","mobile"],["mobile","mobile"],["email","email"],["city","city"],["sponsorship","amount"],["sponsorship inr","amount"],["start month","month"],["promoter","promoter"],["name","name"]]);

function parseCSV(input){
  const text=input.replace(/^\uFEFF/,"");
  const rows=[];
  let values=[],cell="",inside=false;
  for(let i=0;i<text.length;i++){
    const char=text[i];
    if(char==='"'){
      if(inside&&text[i+1]==='"'){cell+='"';i++;}
      else if(!inside&&!cell){inside=true;}
      else if(inside){inside=false;}
      else throw Error("Unexpected quote in CSV. Use doubled quotes inside quoted cells.");
    }else if(char===","&&!inside){values.push(cell);cell="";}
    else if((char==="\n"||char==="\r")&&!inside){
      if(char==="\r"&&text[i+1]==="\n")i++;
      values.push(cell);cell="";
      if(values.some(value=>value.trim()))rows.push(values);
      values=[];
    }else{cell+=char;}
  }
  if(inside)throw Error("CSV has an unclosed quoted field.");
  values.push(cell);
  if(values.some(value=>value.trim()))rows.push(values);
  return rows;
}

const months=["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
function normalizeMonth(raw){
  let match=raw.match(/^(\d{4})-(\d{2})(?:-01)?$/);
  if(match&&Number(match[2])>=1&&Number(match[2])<=12)return match[1]+"-"+match[2]+"-01";
  match=raw.match(/^([A-Za-z]+)[\s-]+(\d{2}|\d{4})$/);
  if(match){
    const index=months.indexOf(match[1].slice(0,3).toLowerCase());
    if(index>=0)return (match[2].length===2?"20"+match[2]:match[2])+"-"+String(index+1).padStart(2,"0")+"-01";
  }
  throw Error("Start Month must be YYYY-MM, YYYY-MM-01 or a month name such as Nov-26.");
}

export function parsePeople(input){
  const text=input.replace(/^\uFEFF/,"");
  const first=text.split(/\r?\n/,1)[0];
  const matrix=first.includes("\t")&&!first.includes(",")
    ?text.replace(/\r/g,"").split("\n").filter(row=>row.trim()).map(row=>row.split("\t"))
    :parseCSV(text);
  if(matrix.length<2)throw Error("Enter a header and at least one person.");
  if(matrix.length>101)throw Error("Use a maximum of 100 people in one import.");
  const header=matrix[0].map(s=>aliases.get(s.trim().toLowerCase().replace(/\s+/g," ")));
  if(header.some(h=>!h)||new Set(header).size!==header.length)throw Error("Use the template columns without unknown or repeated headers.");
  const legacy=header.includes("name");
  if(!header.includes("mobile")||legacy&&header.includes("first")||!legacy&&(!header.includes("first")||!header.includes("code")))throw Error("First name, Country Code and Mobile(Whatsapp) are required (or legacy Name and Mobile).");
  return matrix.slice(1).map((values,index)=>{
    try{
      if(values.length!==header.length)throw Error("Wrong column count.");
      const record=Object.fromEntries(header.map((key,i)=>[key,values[i].trim()]));
      const first=(record.first??"").replace(/\s+/g," ");
      const last=(record.last??"").replace(/\s+/g," ");
      const full=legacy?(record.name??"").replace(/\s+/g," "):[first,last].filter(Boolean).join(" ");
      let mobile=(record.mobile??"").replace(/[\s()-]/g,"");
      if(!legacy){
        const code=(record.code??"").replace(/^\+/,"");
        if(!/^[1-9]\d{0,2}$/.test(code))throw Error("Country Code must be like 91 or +91.");
        if(mobile.startsWith("+")){
          if(!mobile.startsWith("+"+code))throw Error("Mobile country code does not match Country Code.");
        }else{
          if(!/^\d+$/.test(mobile))throw Error("Mobile must contain digits only.");
          mobile="+"+code+mobile;
        }
      }
      if((!legacy&&(first.length<2||first.length>80||last.length>80))||full.length<2||full.length>160||!/^\+[1-9]\d{7,14}$/.test(mobile))throw Error("Enter a valid name and international phone.");
      const person={full_name:full,mobile_number:mobile,area_city:record.city??""};
      if(!legacy){person.first_name=first;if(last)person.last_name=last;}
      if(record.email)person.email=record.email;
      if(record.promoter)person.promoter=record.promoter.replace(/\s+/g," ");
      if(record.amount){
        const raw=record.amount;
        if(!/^\d+$/.test(raw))throw Error("Sponsorship must be a whole rupee amount.");
        const rupees=Number(raw);
        if(!Number.isSafeInteger(rupees)||rupees<=0||rupees>10000000||rupees%250!==0)throw Error("Sponsorship must be ₹250 or a multiple of ₹250.");
        person.monthly_contribution_paise=rupees*100;
      }
      if(record.month)person.start_month=normalizeMonth(record.month);
      return person;
    }catch(error){throw Error("Row "+(index+2)+": "+error.message);}
  });
}
