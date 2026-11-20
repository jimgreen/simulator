'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const turns=()=>new Promise(resolve=>setImmediate(resolve));
async function main() {
  const posts=[],pending=[];
  const window={addEventListener(){}};
  const context=vm.createContext({window,location:{pathname:'/workspace.html'},setTimeout,clearTimeout,
    document:{body:{dataset:{page:'workspace'}},querySelectorAll:()=>[],getElementById:()=>null,addEventListener(){}},
    MutationObserver:class {observe(){}disconnect(){}},
    fetch:async(url,options)=>{
      if(!options)return {ok:true,json:async()=>({values:{directory:'old'}})};
      posts.push(JSON.parse(options.body));
      return new Promise(resolve=>pending.push(resolve));
    }});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/nav.js'),'utf8'),context);
  const preferences=window.simulatorPreferences;
  await preferences.ready;
  preferences.update({directory:'one'});
  const saving=preferences.flush();
  await turns();
  preferences.update({directory:'two',kind:'database'});
  pending.shift()({ok:true,json:async()=>({})});
  await turns();
  assert.equal(posts.length,2);
  assert.equal(posts[1].values.directory,'two');
  pending.shift()({ok:true,json:async()=>({})});
  await saving;
  preferences.update({directory:'retry'});
  const failed=preferences.flush();
  await turns();
  pending.shift()({ok:false,json:async()=>({error:'unavailable'})});
  await failed;
  const retry=preferences.flush();
  await turns();
  assert.equal(posts.at(-1).values.directory,'retry');
  pending.shift()({ok:true,json:async()=>({})});
  await retry;
  console.log('PASS: queued selection saves preserve the latest value and retry failed writes');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
