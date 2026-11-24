'use strict';
const vscode=require('vscode');
const path=require('node:path');
const {PythonBridge}=require('./bridge');
const {createInlineComments}=require('./inline-comments');

function activate(context){
 const output=vscode.window.createOutputChannel('Pair Review Python');
 const bridges=new Map();
 const bridgeFor=root=>{
  if(!bridges.has(root)){
   const uvPath=vscode.workspace.getConfiguration('pairReview').get('uvPath','uv');
   bridges.set(root,new PythonBridge(context.extensionPath,root,uvPath,message=>{if(message)output.appendLine(message)}));
  }
  return bridges.get(root);
 };
 context.subscriptions.push(output,{dispose(){for(const bridge of bridges.values())bridge.dispose();bridges.clear()}});
 const changed=new vscode.EventEmitter(),inlineChanged=new vscode.EventEmitter(),inlineSubmitted=new vscode.EventEmitter();
 context.subscriptions.push(changed,inlineChanged,inlineSubmitted);
 const inline=vscode.comments?createInlineComments(vscode,context,{
  bridgeFor,
  onChange:event=>inlineChanged.fire(event),
  onSubmit:event=>inlineSubmitted.fire(event)
 }):null;
 const content=async uri=>{
  const {root,id,kind}=JSON.parse(uri.query);
  if(!vscode.workspace.isTrusted||!vscode.workspace.workspaceFolders?.some(folder=>path.resolve(folder.uri.fsPath)===root))throw new Error('Preview belongs to a different workspace');
  const snapshot=await bridgeFor(root).request('snapshot',{id,kind});
  if(uri.path!==`/${id}/${kind}/${snapshot.path}`)throw new Error('Preview path does not match the proposal');
  if(kind==='original'||kind==='proposed')await inline?.ensure(root,id);
  return snapshot.text;
 };
 context.subscriptions.push(changed,vscode.workspace.registerTextDocumentContentProvider('pair-review',{onDidChange:changed.event,provideTextDocumentContent:content}));
 const open=uri=>vscode.commands.executeCommand('vscode.openWith',uri,'pairReview.proposal',{viewColumn:vscode.ViewColumn.Active,preview:false});
 context.subscriptions.push(vscode.commands.registerCommand('pairReview.open',async()=>{
  const files=await vscode.workspace.findFiles('**/.pair-review/proposals/*.dff','**/node_modules/**',500);
  const items=files.map(uri=>({label:path.basename(uri.fsPath),description:uri.fsPath,uri}));
  const picked=await vscode.window.showQuickPick(items,{placeHolder:'Select an agent proposal in this workspace'});
  if(picked)await open(picked.uri);else if(!items.length)vscode.window.showInformationMessage('No proposals yet. Ask the agent to submit a Pair Review proposal.');
 }));
 const watcher=vscode.workspace.createFileSystemWatcher('**/.pair-review/proposals/*.dff');
 context.subscriptions.push(watcher,watcher.onDidCreate(async uri=>{
  if(!vscode.workspace.isTrusted)return;
  try{
   if(vscode.workspace.getConfiguration('pairReview').get('autoOpen',true))await open(uri);
   else{
    const action=await vscode.window.showInformationMessage('Agent submitted a code proposal','Review');
    if(action)await open(uri);
   }
  }catch(error){vscode.window.showErrorMessage(`Pair Review: ${error.message}`)}
 }));
 const provider={
  async openCustomDocument(uri){return{uri,dispose(){}} },
  async resolveCustomEditor(document,panel){
   let disposed=false;
   const timers=new Set();
   try{
    if(!vscode.workspace.isTrusted)throw new Error('Trust the workspace before reviewing.');
    const file=document.uri.fsPath,root=path.dirname(path.dirname(path.dirname(file)));
    const folder=vscode.workspace.getWorkspaceFolder(document.uri);
    if(!folder||path.resolve(folder.uri.fsPath)!==path.resolve(root))throw new Error('Open the proposal’s project root as a VS Code workspace folder.');
    const id=path.basename(file,'.dff'),bridge=bridgeFor(root),initial=await bridge.request('load',{id});
    const uriFor=kind=>vscode.Uri.from({scheme:'pair-review',path:`/${id}/${kind}/${initial.path}`,query:JSON.stringify({root,id,kind})});
    const original=uriFor('original'),proposed=uriFor('proposed'),resolved=uriFor('resolved');
    let sourceColumn;
    const sourceOptions=()=>({viewColumn:sourceColumn||((panel.viewColumn||1)+1),preview:false,preserveFocus:true});
    const openColored=async uri=>{
     let doc=await vscode.workspace.openTextDocument(uri);
     const aliases={bash:'shellscript',sh:'shellscript',shell:'shellscript'};
     const lang=/\.tsx$/.test(initial.path)?'typescriptreact':/\.jsx$/.test(initial.path)?'javascriptreact':(aliases[initial.language]||initial.language);
     if(vscode.languages&&(await vscode.languages.getLanguages()).includes(lang))doc=await vscode.languages.setTextDocumentLanguage(doc,lang);
     return doc;
    };
    const showDiff=async()=>{
     await openColored(original);await openColored(proposed);
     const options=sourceOptions();sourceColumn=options.viewColumn;
     await vscode.commands.executeCommand('vscode.diff',original,proposed,`${initial.path} — Original ↔ Full proposed file`,options);
    };
    const showSource=async(line=0)=>{
     const doc=await openColored(proposed),targetLine=Math.max(0,Math.min(line,doc.lineCount-1));
     const editor=await vscode.window.showTextDocument(doc,{...sourceOptions(),selection:new vscode.Range(targetLine,0,targetLine,0)});
     sourceColumn=editor.viewColumn;
    };
    panel.webview.options={enableScripts:true,localResourceRoots:[]};
    let lastReview=await bridge.request('reviewState',{id}),lastFeedback=lastReview.feedback,lastInline=JSON.stringify(lastReview.inlineDrafts||{}),refreshing=false;
    panel.title=`Review: ${initial.path}`;panel.webview.html=initial.html;
    const refresh=async()=>{
     if(disposed||refreshing)return;refreshing=true;
     try{
      const review=await bridge.request('reviewState',{id}),nextFeedback=review.feedback,inlineDrafts=review.inlineDrafts||{},signature=JSON.stringify(inlineDrafts);
      if(nextFeedback.revision===lastFeedback.revision&&signature===lastInline)return;
      lastInline=signature;
      const known=new Set(lastFeedback.comments.map(comment=>comment.id));
      const replies=nextFeedback.comments.filter(comment=>!known.has(comment.id)&&comment.author!=='reviewer');
      lastReview=review;lastFeedback=nextFeedback;changed.fire(resolved);
      panel.webview.postMessage({type:'update',feedback:nextFeedback,inlineDrafts});
      if(replies.length)vscode.window.showInformationMessage(`Pair Review: ${replies.at(-1).author} replied on ${initial.path}`);
     }catch(error){panel.webview.postMessage({type:'error',message:error.message})}finally{refreshing=false}
    };
    const updates=vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder,`.pair-review/{state/${id}.json,comments/${id}/*.json}`));
    updates.onDidCreate(refresh);updates.onDidChange(refresh);
    const poll=setInterval(refresh,1500);timers.add(poll);
    const onInline=inlineChanged.event(event=>{if(event.root===root&&event.id===id)refresh()});
    const onSubmitted=inlineSubmitted.event(async event=>{
     if(event.root!==root||event.id!==id)return;
     try{
      lastReview=event.reviewState||await bridge.request('reviewState',{id});lastFeedback=lastReview.feedback;lastInline=JSON.stringify(lastReview.inlineDrafts||{});
      panel.webview.postMessage({type:'submitted',scope:event.scope,feedback:lastFeedback,inlineDrafts:lastReview.inlineDrafts||{}});changed.fire(resolved);
     }catch(error){panel.webview.postMessage({type:'error',message:error.message})}
    });
    const receive=panel.webview.onDidReceiveMessage(async message=>{
     try{
      if(!vscode.workspace.isTrusted)throw new Error('Workspace is not trusted');
      if(message.type==='draft')await bridge.request('draft',{id,hunk:message.hunk,value:message.value});
      else if(message.type==='discard')await bridge.request('discard',{id,hunk:message.hunk});
      else if(message.type==='sendComment'){
       const result=await bridge.request('sendComment',{id,hunk:message.hunk,value:message.value});lastReview=result;lastFeedback=result.feedback;
       panel.webview.postMessage({type:'commentSent',hunk:message.hunk,feedback:result.feedback,draft:result.draft||null});
      }else if(message.type==='submitReview'){
       await inline?.assertReady(root,id);
       const target=path.resolve(root,initial.path);
       if(vscode.workspace.textDocuments.some(doc=>doc.uri.fsPath===target&&doc.isDirty))throw new Error('Save or revert unsaved source edits before submitting. Drafts are preserved.');
       for(const [hunk,value]of Object.entries(message.drafts||{})){
        if(message.scope!=='all'&&message.scope!==hunk)throw new Error('Draft outside selected scope');
        await bridge.request('draft',{id,hunk,value});
       }
       const result=await bridge.request('submitReview',{id,scope:message.scope});lastReview=result;lastFeedback=result.feedback;lastInline=JSON.stringify(result.inlineDrafts||{});
       panel.webview.postMessage({type:'submitted',scope:message.scope,feedback:result.feedback,inlineDrafts:result.inlineDrafts||{}});
       await inline?.refresh(root,id);changed.fire(resolved);
      }else if(message.type==='refresh')await refresh();
      else if(message.type==='source'){
       let line=0,offset=0;
       if(message.hunk)for(const hunk of initial.hunks){if(hunk.id===message.hunk){line=hunk.start+offset;break}offset+=hunk.added-(hunk.end-hunk.start)}
       await showSource(line);
      }else if(message.type==='diff')await showDiff();
      else if(message.type==='resolved'){
       const doc=await openColored(resolved);await vscode.window.showTextDocument(doc,sourceOptions());
      }
     }catch(error){panel.webview.postMessage({type:'error',message:error.message});vscode.window.showErrorMessage(`Pair Review: ${error.message}`)}
    });
    panel.onDidDispose(()=>{disposed=true;for(const timer of timers)clearInterval(timer);updates.dispose();receive.dispose();onInline.dispose();onSubmitted.dispose()});
    if(vscode.workspace.getConfiguration('pairReview').get('previewMode','diff')==='source')await showSource();else await showDiff();
   }catch(error){
    panel.webview.html=`<p>${String(error.message).replace(/[&<>"']/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]))}</p>`;
   }
  }
 };
 context.subscriptions.push(vscode.window.registerCustomEditorProvider('pairReview.proposal',provider,{supportsMultipleEditorsPerDocument:false,webviewOptions:{retainContextWhenHidden:true}}));
}
module.exports={activate};
