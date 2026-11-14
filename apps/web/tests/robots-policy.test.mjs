import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const read=path=>readFileSync(new URL(path,import.meta.url),"utf8");

test("CRM robots.txt forbids compliant crawler access",()=>{
  assert.equal(read("../public/robots.txt"),"User-agent: *\nDisallow: /\n");
});
test("CRM root layout disallows indexing, following, previews and image indexing",()=>{
  const layout=read("../app/layout.tsx");
  for(const rule of ["index: false","follow: false","noarchive: true","nosnippet: true","noimageindex: true"]) assert.ok(layout.includes(rule),rule);
});
test("web and reference ingress send restrictive robots headers",()=>{
  const policy="noindex, nofollow, noarchive, nosnippet, noimageindex";
  assert.ok(read("../next.config.ts").includes('{key:"X-Robots-Tag",value:"'+policy+'"}'));
  assert.ok(read("../../../ops/shared-vps/Caddyfile").includes('X-Robots-Tag "'+policy+'"'));
});
