'use strict';
const path=require('node:path');

function createInlineComments(vscode,context,{bridgeFor,onChange=()=>{},onSubmit=()=>{}}){
 const controller=vscode.comments.createCommentController('pair-review','Pair Review');
 controller.options={prompt:'Add a line comment to your review. Submit sends saved drafts to the agent.',placeHolder:'Write a review comment…'};
 const sessions=new Map(),metadata=new WeakMap();
 const keyOf=(root,id)=>root+'\0'+id;
 const uriFor=(root,file,id,kind)=>vscode.Uri.from({scheme:'pair-review',path:`/${id}/${kind}/${file}`,query:JSON.stringify({root,id,kind})});
 function identify(uri){
  if(!vscode.workspace.isTrusted||uri?.scheme!=='pair-review')return null;
  let parsed;try{parsed=JSON.parse(uri.query)}catch{return null}
  const {root,id,kind}=parsed;
  if(!['original','proposed'].includes(kind)||!vscode.workspace.workspaceFolders?.some(folder=>path.resolve(folder.uri.fsPath)===root))return null;
  return{root,id,kind};
 }
 function commentView(item,thread,isDraft){
  return{id:item.id,draftId:isDraft?item.id:undefined,body:item.body,savedBody:item.body,author:{name:item.author},mode:vscode.CommentMode.Preview,label:isDraft?'Draft · not submitted':undefined,contextValue:isDraft?'pairReviewDraftComment':'pairReviewPublishedComment',parent:thread,timestamp:new Date(item.at)};
 }
 async function sync(session){
  const{root,id}=session,review=await bridgeFor(root).request('reviewState',{id}),feedback=review.feedback;
  session.path=feedback.path;session.inlineDrafts=review.inlineDrafts||{};
  const draftIds=new Set(Object.keys(session.inlineDrafts));
  const items=[...feedback.comments.filter(comment=>comment.threadId),...Object.values(session.inlineDrafts)];
  const signature=JSON.stringify({items,draftIds:[...draftIds]});if(signature===session.signature)return review;
  session.signature=signature;
  const groups=new Map();
  for(const item of items){if(!groups.has(item.threadId))groups.set(item.threadId,[]);groups.get(item.threadId).push(item)}
  for(const[threadId,comments]of groups){
   let thread=session.threads.get(threadId);const anchor=comments[0];
   if(!thread){
    thread=controller.createCommentThread(uriFor(root,session.path,id,anchor.side),new vscode.Range(anchor.startLine-1,0,anchor.endLine-1,0),[]);
    thread.collapsibleState=vscode.CommentThreadCollapsibleState.Expanded;
    session.threads.set(threadId,thread);metadata.set(thread,{root,id,threadId});
   }
   const old=new Map(thread.comments.map(comment=>[comment.id,comment]));
   const views=comments.map(item=>{const previous=old.get(item.id);return previous?.mode===vscode.CommentMode.Editing?previous:commentView(item,thread,draftIds.has(item.id))});
   if(JSON.stringify(thread.comments.map(comment=>[comment.id,comment.savedBody,comment.label]))!==JSON.stringify(views.map(comment=>[comment.id,comment.savedBody,comment.label])))thread.comments=views;
   const hasDraft=comments.some(comment=>draftIds.has(comment.id));
   thread.contextValue=hasDraft?'pairReviewDraftThread':'pairReviewPublishedThread';
   thread.label=`${anchor.side} L${anchor.startLine}${anchor.endLine===anchor.startLine?'':'–'+anchor.endLine}${hasDraft?' · draft review':''}`;
   thread.canReply=true;
  }
  for(const[threadId,thread]of session.threads)if(!groups.has(threadId)){thread.dispose();session.threads.delete(threadId);metadata.delete(thread)}
  return review;
 }
 async function ensure(root,id){
  const key=keyOf(root,id);
  if(!sessions.has(key))sessions.set(key,{root,id,threads:new Map(),signature:null,inlineDrafts:{}});
  const session=sessions.get(key);await sync(session);return session;
 }
 async function identifyDocument(uri){
  const location=identify(uri);if(!location)return null;
  const session=await ensure(location.root,location.id);
  if(uri.path!==`/${location.id}/${location.kind}/${session.path}`)return null;
  return location;
 }
 async function refresh(root,id){
  const session=sessions.get(keyOf(root,id));if(session)await sync(session);onChange({root,id});
 }
 async function save(reply){
  if(!reply?.thread||!reply.text?.trim())throw new Error('Enter a comment before adding it to the review.');
  const thread=reply.thread,location=await identifyDocument(thread.uri);
  if(!location||!thread.range)throw new Error('Select a line or range in a Pair Review original/proposed file.');
  const{root,id,kind}=location,previous=metadata.get(thread);
  const anchor={side:kind,startLine:thread.range.start.line+1,endLine:thread.range.end.line+1};
  const result=await bridgeFor(root).request('saveInlineDraft',{id,anchor,body:reply.text,options:previous?{threadId:previous.threadId}:{}});
  const item=result.item,session=await ensure(root,id);
  session.threads.set(item.threadId,thread);metadata.set(thread,{root,id,threadId:item.threadId});
  session.signature=null;await refresh(root,id);return item;
 }
 function threadContext(value){
  const thread=value?.thread||value,info=metadata.get(thread);
  if(!info)throw new Error('Save a comment with Add to review first.');
  if(!identify(thread.uri))throw new Error('Thread belongs to a different or untrusted workspace');
  return{...info,thread};
 }
 async function submit(reply,all=false){
  if(reply?.text?.trim())await save(reply);
  const{root,id,threadId}=threadContext(reply),session=await ensure(root,id);
  if([...session.threads.values()].some(thread=>thread.comments.some(comment=>comment.mode===vscode.CommentMode.Editing)))throw new Error('Save or cancel edited inline drafts before submitting.');
  const target=path.resolve(root,session.path);
  if(vscode.workspace.textDocuments.some(document=>document.uri.fsPath===target&&document.isDirty))throw new Error('Save or revert unsaved source edits before submitting.');
  const scope=all?'all':'thread:'+threadId;
  const reviewState=await bridgeFor(root).request('submitReview',{id,scope});await refresh(root,id);onSubmit({root,id,scope,reviewState});
 }
 async function assertReady(root,id){
  const session=await ensure(root,id);
  if([...session.threads.values()].some(thread=>thread.comments.some(comment=>comment.mode===vscode.CommentMode.Editing)))throw new Error('Save or cancel edited inline drafts before submitting.');
 }
 async function sendComment(value){
  let info,commentId;
  if(value?.parent){
   if(value.mode===vscode.CommentMode.Editing)throw new Error('Save the edited draft before sending it.');
   info=threadContext(value.parent);commentId=value.draftId;
   if(!commentId)throw new Error('This comment is already published.');
  }else{
   const item=await save(value);info=threadContext(value);commentId=item.id;
  }
  const{root,id}=info,scope='comment:'+commentId;
  const reviewState=await bridgeFor(root).request('submitReview',{id,scope});await refresh(root,id);onSubmit({root,id,scope,reviewState});
 }
 function edit(comment){threadContext(comment.parent);comment.mode=vscode.CommentMode.Editing;comment.parent.comments=[...comment.parent.comments]}
 async function saveEdit(comment){
  const{root,id}=threadContext(comment.parent),session=await ensure(root,id),item=session.inlineDrafts[comment.draftId];
  if(!item)throw new Error('Only draft comments can be edited.');
  const body=typeof comment.body==='string'?comment.body:comment.body.value;
  await bridgeFor(root).request('saveInlineDraft',{id,anchor:item,body,options:{draftId:item.id,threadId:item.threadId}});
  comment.mode=vscode.CommentMode.Preview;comment.savedBody=body;comment.parent.comments=[...comment.parent.comments];await refresh(root,id);
 }
 function cancelEdit(comment){threadContext(comment.parent);comment.body=comment.savedBody;comment.mode=vscode.CommentMode.Preview;comment.parent.comments=[...comment.parent.comments]}
 async function remove(comment){const{root,id}=threadContext(comment.parent);await bridgeFor(root).request('discardInlineDraft',{id,draftId:comment.draftId});await refresh(root,id)}
 const commandActions={
  'pairReview.addInlineDraft':save,
  'pairReview.sendInlineComment':sendComment,
  'pairReview.submitInlineThread':reply=>submit(reply),
  'pairReview.submitInlineReview':reply=>submit(reply,true),
  'pairReview.editInlineDraft':edit,
  'pairReview.saveInlineDraft':saveEdit,
  'pairReview.cancelInlineEdit':cancelEdit,
  'pairReview.deleteInlineDraft':remove
 };
 for(const[name,handler]of Object.entries(commandActions))context.subscriptions.push(vscode.commands.registerCommand(name,async argument=>{try{return await handler(argument)}catch(error){vscode.window.showErrorMessage(`Pair Review: ${error.message}`)}}));
 controller.commentingRangeProvider={provideCommentingRanges:async document=>{
  try{const location=await identifyDocument(document.uri);if(!location)return[];return[new vscode.Range(0,0,Math.max(0,document.lineCount-1),0)]}catch{return[]}
 }};
 const timer=setInterval(()=>{for(const[key,session]of sessions){
  if(!vscode.workspace.isTrusted||!vscode.workspace.workspaceFolders?.some(folder=>path.resolve(folder.uri.fsPath)===session.root)){for(const thread of session.threads.values())thread.dispose();sessions.delete(key);continue}
  sync(session).catch(()=>{});
 }},1500);timer.unref?.();
 const api={ensure,refresh,identify,assertReady,dispose(){clearInterval(timer);controller.dispose();sessions.clear()}};
 context.subscriptions.push(api);return api;
}
module.exports={createInlineComments};
