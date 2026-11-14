import test from "node:test";
import assert from "node:assert/strict";
import {COLUMNS,parsePeople} from "../components/prospects/prospect-import-parser.mjs";
test("nine-column Excel-shaped import retains fields and normalizes dates and country codes",()=>{
 const header=COLUMNS.join("\t");
 const rows=parsePeople(header+"\nSample\tMulti Word\t91\t9876543210\tsample@example.com\tBengaluru\t250\tNov-26\tTest Promoter");
 assert.deepEqual(rows,[{full_name:"Sample Multi Word",first_name:"Sample",last_name:"Multi Word",mobile_number:"+919876543210",email:"sample@example.com",area_city:"Bengaluru",monthly_contribution_paise:25000,start_month:"2026-11-01",promoter:"Test Promoter"}]);
});
test("legacy CSV remains compatible and full international phone is not prefixed twice",()=>{
 assert.equal(parsePeople("Name,Mobile,City,Email,Sponsorship INR,Start Month\nSample Person,+919876543210,,,500,2026-11")[0].monthly_contribution_paise,50000);
 assert.equal(parsePeople(COLUMNS.join(",")+"\nSample,Person,+91,+919876543210,,,500,2026-11-01,")[0].mobile_number,"+919876543210");
});
test("invalid code, mismatched international phone, amount, or month gives a row error",()=>{
 for(const row of ["Sample,Person,0,9876543210,,,250,Nov-26,","Sample,Person,44,+919876543210,,,250,Nov-26,","Sample,Person,91,9876543210,,,125,Nov-26,","Sample,Person,91,9876543210,,,250,2026-14,"]) assert.throws(()=>parsePeople(COLUMNS.join(",")+"\n"+row),/Row 2:/);
});
