'use strict';
const vscode=require('vscode');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {spawnSync}=require('node:child_process');

const project=process.env.PAIR_REVIEW_PROJECT_ROOT,root=process.env.PAIR_REVIEW_HOST_WORKSPACE,uv=process.env.PAIR_REVIEW_UV_PATH;
function python(script,...args){
 const result=spawnSync(uv,['run','--project',project,'python','-c',script,...args],{cwd:root,encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);return result.stdout.trim()?JSON.parse(result.stdout):null;
}
async function waitFor(predicate,message,timeout=20000){
 const deadline=Date.now()+timeout;
 while(Date.now()<deadline){if(await predicate())return;await new Promise(resolve=>setTimeout(resolve,200))}
 throw new Error('Timed out: '+message);
}
async function run(){
 const extension=vscode.extensions.getExtension('local-pair-review.pair-review-mcp');
 assert.ok(extension,'Pair Review was not loaded from the installed VSIX');
 await extension.activate();
 assert.notEqual(path.resolve(extension.extensionPath),path.resolve(project),'Test accidentally used extensionDevelopmentPath instead of the VSIX installation');
 assert.ok(path.resolve(extension.extensionPath).startsWith(path.resolve(process.env.PAIR_REVIEW_EXTENSIONS_DIR)+path.sep),'Extension is outside the isolated installation directory');
 console.log('INSTALLED_EXTENSION='+extension.extensionPath);
 const proposal=python('import json; from pair_review import core; print(json.dumps(core.submit(".", "a.txt", "ONE\\ntwo\\nthree\\nfour\\n", "Installed host acceptance", "host-test")))');
 const customTab=()=>vscode.window.tabGroups.all.flatMap(group=>group.tabs).find(tab=>tab.input instanceof vscode.TabInputCustom&&tab.input.viewType==='pairReview.proposal');
 await waitFor(customTab,'installed extension did not auto-open the proposal custom editor');
 await waitFor(()=>vscode.window.tabGroups.all.flatMap(group=>group.tabs).some(tab=>tab.input?.original&&tab.input?.modified),'installed extension did not open the full native diff');
 const uri=kind=>vscode.Uri.from({scheme:'pair-review',path:`/${proposal.id}/${kind}/a.txt`,query:JSON.stringify({root,id:proposal.id,kind})});
 const original=await vscode.workspace.openTextDocument(uri('original')),proposed=await vscode.workspace.openTextDocument(uri('proposed'));
 assert.equal(original.getText(),'one\ntwo\nthree\nfour\n');assert.equal(proposed.getText(),'ONE\ntwo\nthree\nfour\n');
 const thread={uri:uri('proposed'),range:new vscode.Range(0,0,0,0),comments:[]};
 await vscode.commands.executeCommand('pairReview.addInlineDraft',{thread,text:'Question from real Extension Host'});
 let review=python('import json,sys; from pair_review import core; print(json.dumps(core.feedback(".",sys.argv[1])))',proposal.id);
 assert.equal(review.comments.length,0,'Inline draft leaked before Submit');
 await vscode.commands.executeCommand('pairReview.submitInlineThread',{thread,text:''});
 review=python('import json,sys; from pair_review import core; print(json.dumps(core.feedback(".",sys.argv[1])))',proposal.id);
 assert.equal(review.comments[0].body,'Question from real Extension Host');assert.equal(review.hunks[0].status,'pending');
 assert.equal(fs.readFileSync(path.join(root,'a.txt'),'utf8'),'one\ntwo\nthree\nfour\n');
 const {PythonBridge}=require(path.join(extension.extensionPath,'vscode','bridge.js'));
 const bridge=new PythonBridge(extension.extensionPath,root,uv,message=>console.log(message));
 try{
  const threadId=review.comments[0].threadId;
  python('import sys; from pair_review import core; core.progress(".",sys.argv[1],"Checking the real host",thread_id=sys.argv[2],agent="host-test")',proposal.id,threadId);
  await waitFor(async()=>{const live=await bridge.request('reviewState',{id:proposal.id});return live.activity.some(event=>event.summary==='Checking the real host')},'installed host did not publish live activity');
  python('import sys; from pair_review import core; core.reply_thread(".",sys.argv[1],sys.argv[2],"Final host answer","host-test")',proposal.id,threadId);
  await waitFor(async()=>{const live=await bridge.request('reviewState',{id:proposal.id});return live.activity.length===0&&live.feedback.comments.some(comment=>comment.body==='Final host answer')},'formal reply did not clear live activity');
  python('import sys; from pair_review import core; core.revise(".",sys.argv[1],"REVISED\\ntwo\\nthree\\nfour\\n")',proposal.id);
  await waitFor(async()=>{const live=await bridge.request('reviewState',{id:proposal.id});return live.proposalRevision===2},'installed host did not refresh the revised proposal');
  const refreshed=await bridge.request('load',{id:proposal.id});
  assert.equal(refreshed.proposalRevision,2);assert.ok(refreshed.html.includes('Question from real Extension Host'));assert.ok(refreshed.html.includes('Final host answer'));
  const reviewTabs=vscode.window.tabGroups.all.flatMap(group=>group.tabs).filter(tab=>tab.input instanceof vscode.TabInputCustom&&tab.input.viewType==='pairReview.proposal');
  assert.equal(reviewTabs.length,1,'Revision opened a duplicate review tab');
  await bridge.request('draft',{id:proposal.id,hunk:'h1',value:{decision:'accepted',body:'Accept from installed bridge'}});
  assert.equal(fs.readFileSync(path.join(root,'a.txt'),'utf8'),'one\ntwo\nthree\nfour\n');
  await bridge.request('submitReview',{id:proposal.id,scope:'h1'});
 }finally{bridge.dispose()}
 assert.equal(fs.readFileSync(path.join(root,'a.txt'),'utf8'),'REVISED\ntwo\nthree\nfour\n');
 const resolved=await vscode.workspace.openTextDocument(uri('resolved'));assert.equal(resolved.getText(),'REVISED\ntwo\nthree\nfour\n');
 console.log('REAL_VSCODE_EXTENSION_HOST_ACCEPTANCE=PASS');
}
module.exports={run};
