'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..');
function render(){
 const proposal={id:'demo',title:'Review',path:'example.ts',agent:'qwen',before:'// note\nconst userName = "Ada";\n\nfunction greet(name: string) {\n  return "Hello " + name;\n}\n',after:'// note\nconst userName = "Grace";\n\nfunction greet(name: string) {\n  // explain intent\n  return `Welcome ${name}`;\n}\n'};
 const script='import json,sys; from pair_review import core; from pair_review.views import render_html; p=json.loads(sys.argv[1]); p["hunks"]=core.diff(p["before"],p["after"]); f={"id":"demo","hunks":[{"id":h["id"],"status":"pending"} for h in p["hunks"]],"comments":[],"revision":"1"}; print(render_html(p,{"decisions":{}},f))';
 const result=spawnSync('uv',['run','python','-c',script,JSON.stringify(proposal)],{cwd:root,encoding:'utf8',maxBuffer:10*1024*1024});
 assert.equal(result.status,0,result.stderr);return result.stdout;
}
const page=render();
function setup(t){
 const feedback={id:'demo',hunks:[{id:'h1',status:'pending'},{id:'h2',status:'pending'}],comments:[],revision:'1'};
 const sent=[],errors=[],console=new VirtualConsole();console.on('jsdomError',error=>errors.push(error.message));
 const dom=new JSDOM(page,{runScripts:'dangerously',virtualConsole:console,beforeParse(window){window.acquireVsCodeApi=()=>({postMessage:message=>sent.push(JSON.parse(JSON.stringify(message))),setState:()=>{},getState:()=>null})}});
 t.after(()=>dom.window.close());const window=dom.window,document=window.document;
 const click=(action,hunk)=>document.querySelector(`button[data-action="${action}"][data-hunk="${hunk}"]`).click();
 const input=(hunk,text)=>{const field=document.getElementById('body-'+hunk);field.value=text;field.dispatchEvent(new window.Event('input',{bubbles:true}))};
 const update=message=>window.dispatchEvent(new window.MessageEvent('message',{data:message}));
 return{window,document,sent,errors,feedback,click,input,update};
}

test('accept/reject/comment remain drafts and undo preserves text',t=>{
 const x=setup(t);x.click('accept','h1');x.input('h1','Why?');
 assert.match(x.document.getElementById('status-h1').textContent,/Draft: accepted/);
 assert.equal(x.sent.some(message=>message.type==='submitReview'),false);
 x.click('undo','h1');assert.doesNotMatch(x.document.getElementById('status-h1').textContent,/Draft: accepted/);
 assert.equal(x.document.getElementById('body-h1').value,'Why?');assert.deepEqual(x.errors,[]);
});

test('live reply preserves focused text and collapsed diff state',t=>{
 const x=setup(t);x.input('h2','Keep this unsent text');const field=x.document.getElementById('body-h2');field.focus();
 const details=x.document.querySelector('details');details.open=false;
 x.update({type:'update',feedback:{...x.feedback,comments:[{id:'reply',hunk:'h1',body:'Here is my explanation',author:'qwen',at:'2026-11-11'}],revision:'2'}});
 assert.equal(x.document.activeElement,field);assert.equal(field.value,'Keep this unsent text');assert.equal(details.open,false);
 assert.match(x.document.getElementById('comments-h1').textContent,/Here is my explanation/);
 assert.match(x.document.getElementById('notice').textContent,/qwen replied/);assert.deepEqual(x.errors,[]);
});

test('single submit selects and clears only its own draft',t=>{
 const x=setup(t);x.click('accept','h1');x.input('h1','first comment');x.input('h2','second comment');x.click('submit','h1');
 const message=x.sent.find(item=>item.type==='submitReview');assert.deepEqual(Object.keys(message.drafts),['h1']);
 assert.equal(message.drafts.h1.decision,'accepted');assert.equal(x.document.getElementById('body-h2').disabled,true);
 x.update({type:'submitted',scope:'h1',feedback:{...x.feedback,hunks:[{id:'h1',status:'accepted'},{id:'h2',status:'pending'}]}});
 assert.equal(x.document.getElementById('body-h1').value,'');assert.equal(x.document.getElementById('body-h2').value,'second comment');
 x.click('undo','h1');assert.match(x.document.getElementById('status-h1').textContent,/Submitted: accepted → Draft: pending/);
 assert.equal(x.sent.at(-1).value.decision,null);assert.deepEqual(x.errors,[]);
});

test('failed submit preserves text and decision for retry',t=>{
 const x=setup(t);x.click('accept','h1');x.input('h1','Must not be lost');x.click('submit','all');
 x.update({type:'error',message:'Conflict: source changed'});
 assert.equal(x.document.getElementById('body-h1').value,'Must not be lost');
 assert.match(x.document.getElementById('status-h1').textContent,/Draft: accepted/);
 assert.equal(x.document.querySelector('button[data-action="submit"][data-hunk="all"]').disabled,false);
});

test('Python syntax highlighting includes keywords strings comments and themes',t=>{
 const x=setup(t);assert.ok(x.document.querySelector('.hljs-keyword'));assert.ok(x.document.querySelector('.hljs-string'));assert.ok(x.document.querySelector('.hljs-comment'));
 assert.match(x.document.querySelector('.diff').textContent,/userName/);
 const css=x.document.querySelector('style').textContent;for(const token of['--kw:','--str:','--id:','--comment:','body.vscode-light'])assert.ok(css.includes(token));
 assert.deepEqual(x.errors,[]);
});

test('inline drafts enable scoped submit without replacing panel drafts',t=>{
 const x=setup(t);x.input('h2','Keep my panel draft');
 x.update({type:'update',feedback:x.feedback,inlineDrafts:{draft1:{id:'draft1',hunk:'h1',side:'original',startLine:2,endLine:3,body:'Inline review'}}});
 assert.equal(x.document.querySelector('button[data-action="submit"][data-hunk="h1"]').disabled,false);
 x.click('submit','h1');const message=x.sent.find(item=>item.type==='submitReview');assert.equal(message.scope,'h1');assert.deepEqual(message.drafts,{});
 x.update({type:'submitted',scope:'h1',feedback:x.feedback,inlineDrafts:{}});
 assert.equal(x.document.getElementById('inline-drafts-h1').textContent,'');assert.equal(x.document.getElementById('body-h2').value,'Keep my panel draft');
});

test('Send comment leaves Accept and all other drafts private',t=>{
 const x=setup(t);x.click('accept','h1');x.input('h1','Can you explain?');x.input('h2','Private question');x.click('send','h1');
 const message=x.sent.find(item=>item.type==='sendComment');assert.equal(message.value.body,'Can you explain?');
 assert.equal(x.sent.some(item=>item.type==='submitReview'),false);
 x.update({type:'commentSent',hunk:'h1',feedback:{...x.feedback,comments:[{id:'sent',hunk:'h1',body:'Can you explain?',author:'reviewer',at:'2026-11-11'}]},draft:{decision:'accepted',body:'',line:null}});
 assert.equal(x.document.getElementById('body-h1').value,'');assert.equal(x.document.getElementById('body-h2').value,'Private question');
 assert.match(x.document.getElementById('status-h1').textContent,/Draft: accepted/);
});

test('file changes share one file group and diff action lives on the file bar',t=>{
 const x=setup(t);
 assert.equal(x.document.querySelectorAll('.file-group').length,1);
 assert.equal(x.document.querySelectorAll('.file-group[data-file="example.ts"] .change-card').length,3);
 assert.equal(x.document.querySelectorAll('.file-header button[data-action="diff"]').length,1);
 assert.equal(x.document.querySelectorAll('.toolbar button[data-action="diff"]').length,0);
 assert.doesNotMatch(x.document.querySelector('.file-body').textContent,/h[123] · original/);
 assert.match(x.document.querySelector('.change-header').textContent,/Change 1 of 2/);
});

test('speaker cards have distinct roles and thinking disappears after the formal reply',t=>{
 const x=setup(t);x.input('h2','Keep my draft');const field=x.document.getElementById('body-h2');field.focus();
 const reviewer={id:'review-1',hunk:'h1',body:'Please explain this',author:'reviewer',at:'2026-11-24'};
 x.update({type:'update',feedback:{...x.feedback,comments:[reviewer]},activity:[{id:'work-1',hunk:'h1',agent:'qwen',summary:'Checking the call graph'}]});
 const thinking=x.document.getElementById('activity-work-1');
 assert.equal(thinking.dataset.role,'agent-thinking');assert.match(thinking.textContent,/Checking the call graph/);
 assert.equal(x.document.getElementById('comment-review-1').dataset.role,'reviewer');
 x.update({type:'update',feedback:{...x.feedback,comments:[reviewer]},activity:[{id:'work-1',hunk:'h1',agent:'qwen',summary:'Preparing the answer'}]});
 assert.match(x.document.getElementById('activity-work-1').textContent,/Preparing the answer/);assert.equal(x.document.activeElement,field);
 const agent={id:'reply-1',hunk:'h1',body:'The call stays in the provider',author:'qwen',at:'2026-11-24'};
 x.update({type:'update',feedback:{...x.feedback,comments:[reviewer,agent]},activity:[]});
 assert.equal(x.document.getElementById('activity-work-1'),null);
 assert.equal(x.document.getElementById('comment-reply-1').dataset.role,'agent');
 assert.equal(field.value,'Keep my draft');assert.deepEqual(x.errors,[]);
 const css=x.document.querySelector('style').textContent;
 assert.ok(css.includes('.comment.reviewer'));assert.ok(css.includes('.comment.agent'));assert.ok(css.includes('border-left-width: 4px'));
});

test('comments and replies from every revision remain visible including removed hunk anchors',t=>{
 const x=setup(t);
 const oldReview={id:'old-review',hunk:'h99',body:'Review on an old hunk',author:'reviewer',at:'2026-11-24',proposalRevision:1};
 const oldReply={id:'old-reply',hunk:'h99',body:'Reply on the same old hunk',author:'qwen',at:'2026-11-24',proposalRevision:1};
 const current={id:'current-reply',hunk:'h1',body:'New revision reply',author:'qwen',at:'2026-11-24',proposalRevision:2};
 x.update({type:'update',feedback:{...x.feedback,proposalRevision:2,comments:[oldReview,oldReply,current]},activity:[]});
 const general=x.document.getElementById('comments-general');
 assert.ok(general.querySelector('#comment-old-review'));assert.ok(general.querySelector('#comment-old-reply'));
 assert.equal(x.document.getElementById('comment-old-review').dataset.proposalRevision,'1');
 assert.equal(x.document.getElementById('comment-old-reply').dataset.proposalRevision,'1');
 assert.equal(x.document.getElementById('comment-current-reply').dataset.proposalRevision,'2');
 assert.match(x.document.querySelector('.file-count').textContent,/Revision 1/);
 assert.match(general.textContent,/Review on an old hunk/);assert.match(general.textContent,/Reply on the same old hunk/);
});
