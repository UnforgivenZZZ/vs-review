'use strict';
const vscode=acquireVsCodeApi();
let feedback=initial.feedback;
let drafts=initial.drafts;
let inlineDrafts=initial.inlineDrafts||{};
let activity=initial.activity||[];
let busy=false;
const statusOf=h=>feedback.hunks.find(x=>x.id===h)?.status||'pending';
const notice=text=>{document.getElementById('notice').textContent=text};
function persist(){vscode.setState({drafts})}
function updateDraft(h){
 const prior=drafts[h]||{};
 const item={...prior,body:document.getElementById('body-'+h).value,line:document.getElementById('line-'+h).value||null};
 if(!item.body.trim()&&!Object.hasOwn(item,'decision'))delete drafts[h];else drafts[h]=item;
 persist();vscode.postMessage({type:'draft',hunk:h,value:item});renderControls();
}
function setDecision(h,decision){
 const item={...(drafts[h]||{}),body:document.getElementById('body-'+h).value,line:document.getElementById('line-'+h).value||null};
 if(decision===(statusOf(h)==='pending'?null:statusOf(h)))delete item.decision;else item.decision=decision;
 drafts[h]=item;updateDraft(h);
}
function renderControls(){
 for(const h of feedback.hunks){
  const d=drafts[h.id],has=d&&Object.hasOwn(d,'decision');
  const displayed=has?(d.decision||'pending'):h.status;
  document.getElementById('status-'+h.id).textContent=`Submitted: ${h.status}${has?' → Draft: '+displayed:''}`;
  for(const a of ['accept','reject']) document.querySelector(`button[data-action="${a}"][data-hunk="${h.id}"]`).setAttribute('aria-pressed',String(displayed===(a==='accept'?'accepted':'rejected')));
 }
 document.getElementById('draft-count').textContent=(Object.keys(drafts).length+Object.keys(inlineDrafts).length)+' draft item(s)';
 document.querySelectorAll('button,input,textarea').forEach(el=>{el.disabled=busy});
 document.querySelectorAll('button[data-action="send"]').forEach(el=>{el.disabled=busy||!drafts[el.dataset.hunk]?.body?.trim()});
 document.querySelectorAll('button[data-action="submit"]').forEach(el=>{el.disabled=busy||(el.dataset.hunk==='all'?!(Object.keys(drafts).length+Object.keys(inlineDrafts).length):!drafts[el.dataset.hunk]&&!Object.values(inlineDrafts).some(c=>c.hunk===el.dataset.hunk))});
}
function fillDrafts(scope='all'){
 document.querySelectorAll('textarea[data-hunk]').forEach(el=>{const h=el.dataset.hunk;if(scope!=='all'&&scope!==h)return;el.value=drafts[h]?.body||'';document.getElementById('line-'+h).value=drafts[h]?.line||''});
}
function commentHeader(author,role,badge,meta,thinking=false){
 const header=document.createElement('div');header.className='comment-header';
 if(thinking){const dot=document.createElement('span');dot.className='status-dot';dot.setAttribute('aria-hidden','true');header.append(dot)}
 const name=document.createElement('b');name.className='comment-author';name.textContent=author;
 const label=document.createElement('span');label.className='role-badge';label.textContent=badge;
 const time=document.createElement('small');time.textContent=meta;
 header.append(name,label,time);return header;
}
function renderComments(){
 for(const c of feedback.comments){
  if(document.getElementById('comment-'+c.id))continue;
  const host=document.getElementById('comments-'+c.hunk)||document.getElementById('comments-general');if(!host)continue;
  const role=c.author==='reviewer'?'reviewer':'agent';
  const item=document.createElement('article');item.className=`comment ${role}`;item.id='comment-'+c.id;item.dataset.role=role;item.dataset.proposalRevision=String(c.proposalRevision||1);
  const meta=' · revision '+(c.proposalRevision||1)+' · '+c.at+(c.startLine?' · '+c.side+' L'+c.startLine+(c.endLine!==c.startLine?'–'+c.endLine:''):(c.line?' · proposed L'+c.line:''));
  const header=commentHeader(c.author,role,role==='reviewer'?'You · Review':'Agent',meta);
  const text=document.createElement('p');text.textContent=c.body;item.append(header,text);host.append(item);
 }
}
function renderActivity(){
 document.querySelectorAll('.activity').forEach(host=>{host.replaceChildren();host.setAttribute('aria-live','polite')});
 for(const event of activity){
  const host=document.getElementById('activity-'+event.hunk)||document.getElementById('activity-general');if(!host)continue;
  const item=document.createElement('article');item.className='comment agent thinking';item.id='activity-'+event.id;item.dataset.role='agent-thinking';
  const header=commentHeader(event.agent,'agent','Thinking',' · updating live',true);
  const text=document.createElement('p');text.textContent=event.summary;item.append(header,text);host.append(item);
 }
}
function renderInlineDrafts(){
 document.querySelectorAll('.inline-drafts').forEach(el=>el.replaceChildren());
 for(const c of Object.values(inlineDrafts)){
  const host=document.getElementById('inline-drafts-'+c.hunk);if(!host)continue;
  const item=document.createElement('article');item.className='comment reviewer';item.dataset.role='reviewer-draft';
  const header=commentHeader('reviewer','reviewer','Draft · You',` · ${c.side} L${c.startLine}–${c.endLine}`);
  const text=document.createElement('p');text.textContent=c.body;
  const hint=document.createElement('small');hint.textContent='Not sent. Edit or delete in the diff comment thread.';
  item.append(header,text,hint);host.append(item);
 }
}
document.addEventListener('input',e=>{if(!busy&&e.target.dataset.field)updateDraft(e.target.dataset.hunk)});
document.addEventListener('click',e=>{
 const b=e.target.closest('button[data-action]');if(!b||busy)return;
 const {action:a,hunk:h}=b.dataset;
 if(a==='accept'||a==='reject')setDecision(h,a==='accept'?'accepted':'rejected');
 else if(a==='undo')setDecision(h,null);
 else if(a==='discard'){delete drafts[h];persist();fillDrafts(h);vscode.postMessage({type:'discard',hunk:h});renderControls()}
 else if(a==='send'){busy=true;renderControls();vscode.postMessage({type:'sendComment',hunk:h,value:drafts[h]})}
 else if(a==='submit'){
  const selected=Object.fromEntries(Object.entries(drafts).filter(([key])=>h==='all'||h===key));
  busy=true;renderControls();vscode.postMessage({type:'submitReview',scope:h,drafts:selected});
 }else vscode.postMessage({type:a,hunk:h});
});
window.addEventListener('message',e=>{
 const msg=e.data;
 if(msg.type==='update'){
  const known=new Set(feedback.comments.map(c=>c.id));
  const incoming=msg.feedback.comments.filter(c=>!known.has(c.id)&&c.author!=='reviewer');
  feedback=msg.feedback;inlineDrafts=msg.inlineDrafts||inlineDrafts;activity=msg.activity||[];
  renderActivity();renderInlineDrafts();renderComments();renderControls();
  if(incoming.length)notice(`${incoming.at(-1).author} replied — ${incoming.length} new comment(s) shown below.`);
 }else if(msg.type==='submitted'){
  for(const h of Object.keys(drafts))if(msg.scope==='all'||msg.scope===h)delete drafts[h];
  feedback=msg.feedback;inlineDrafts=msg.inlineDrafts||{};activity=msg.activity||[];
  renderActivity();renderInlineDrafts();busy=false;persist();fillDrafts(msg.scope);renderComments();renderControls();notice('Review submitted. The agent can now read this feedback.');
 }else if(msg.type==='commentSent'){
  if(msg.draft)drafts[msg.hunk]=msg.draft;else delete drafts[msg.hunk];
  feedback=msg.feedback;activity=msg.activity||[];busy=false;persist();fillDrafts(msg.hunk);renderActivity();renderComments();renderControls();notice('Comment sent. Other review decisions remain drafts.');
 }else if(msg.type==='error'){busy=false;renderControls();notice(msg.message)}
});
fillDrafts();renderActivity();renderInlineDrafts();renderControls();renderComments();
