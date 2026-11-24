'use strict';
const {spawn}=require('node:child_process');
const readline=require('node:readline');

class PythonBridge {
 constructor(extensionPath,root,uvPath,onError){
  this.extensionPath=extensionPath;this.root=root;this.uvPath=uvPath;this.onError=onError;
  this.pending=new Map();this.nextId=1;this.disposed=false;this.child=null;
 }
 start(){
  if(this.child)return;
  this.child=spawn(this.uvPath,['run','--project',this.extensionPath,'pair-review-bridge','--workspace',this.root],{
   cwd:this.root,stdio:['pipe','pipe','pipe'],windowsHide:true
  });
  const lines=readline.createInterface({input:this.child.stdout});
  lines.on('line',line=>{
   let message;try{message=JSON.parse(line)}catch{this.onError('Pair Review Python bridge returned invalid JSON');return}
   const pending=this.pending.get(message.id);if(!pending)return;
   this.pending.delete(message.id);
   if(message.error)pending.reject(new Error(message.error.message));else pending.resolve(message.result);
  });
  this.child.stderr.on('data',chunk=>this.onError(String(chunk).trimEnd()));
  this.child.on('error',error=>this.fail(error));
  this.child.on('exit',(code,signal)=>{
   if(!this.disposed)this.fail(new Error(`Pair Review Python bridge exited (${code===null?signal:code})`));
   this.child=null;
  });
 }
 fail(error){
  for(const {reject}of this.pending.values())reject(error);
  this.pending.clear();this.onError(error.message);
 }
 request(method,params={}){
  if(this.disposed)return Promise.reject(new Error('Pair Review Python bridge is disposed'));
  this.start();
  const id=this.nextId++;
  return new Promise((resolve,reject)=>{
   this.pending.set(id,{resolve,reject});
   this.child.stdin.write(JSON.stringify({id,method,params})+'\n',error=>{if(error){this.pending.delete(id);reject(error)}});
  });
 }
 dispose(){
  this.disposed=true;
  if(this.child){this.child.stdin.end();this.child.kill();this.child=null}
  const error=new Error('Pair Review Python bridge is disposed');
  for(const {reject}of this.pending.values())reject(error);
  this.pending.clear();
 }
}
module.exports={PythonBridge};
