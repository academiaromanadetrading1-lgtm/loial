// Validate translated strings and dictionary coverage in all nine languages.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('loial-i18n.js','utf8');
const from=source.indexOf("const langs=");
const to=source.indexOf("const dictionary=new Map",from);
assert.ok(from>0&&to>from,'Dictionary source expected');
const context=vm.createContext({});
vm.runInContext(source.slice(from,to)+'\n;globalThis.i18n={langs,rows};',context,{timeout:3000});
const {langs,rows}=context.i18n;
assert.deepEqual(Array.from(langs),['ro','en','de','fr','it','es','nl','pl','hu']);
assert.ok(rows.length>=100,'Translation dictionary unexpectedly short');
const errors=[];
for(let i=0;i<rows.length;i++){
  const row=rows[i];
  if(!Array.isArray(row)||row.length!==langs.length){
    errors.push('row '+i+' has '+(row?.length??'?')+' entries; expected '+langs.length);
    continue;
  }
  for(let j=0;j<row.length;j++)if(typeof row[j]!=='string'||!row[j].trim()){
    errors.push('row '+i+' empty '+langs[j]);
  }
}
const duplicate=new Map();
for(let i=0;i<rows.length;i++){
 const k=rows[i]?.[0];
 if(duplicate.has(k)&&JSON.stringify(duplicate.get(k))!==JSON.stringify(rows[i]))
   errors.push('conflicting translation for key '+JSON.stringify(k).slice(0,90));
 else duplicate.set(k,rows[i]);
}
const pages=['index.html','login.html','register.html','join.html','scan.html','platform.html'];
for(const page of pages){
 const html=fs.readFileSync(page,'utf8');
 if(!html.includes('/loial-i18n.js'))errors.push(page+' lacks translation loader');
}
console.log('Languages: '+langs.join(', '));
console.log('Translation rows: '+rows.length+'; distinct keys: '+duplicate.size);
if(errors.length){console.error(errors.slice(0,30).join('\n'));console.error(errors.length+' total errors');process.exitCode=1;}
else console.log('PASS: dictionary and entry page translation coverage');
