'use strict';
const path=require('node:path');
const fs=require('node:fs');
const {spawnSync}=require('node:child_process');
const {downloadAndUnzipVSCode,runTests,runVSCodeCommand}=require('@vscode/test-electron');

async function main(){
 const root=path.resolve(__dirname,'../..'),cache=path.join(root,'.vscode-test');
 const packaged=spawnSync('python3',['scripts/package.py'],{cwd:root,encoding:'utf8'});
 if(packaged.status!==0)throw new Error(packaged.stderr||packaged.stdout);
 const vsix=packaged.stdout.trim().split('\n').at(-1),downloaded=await downloadAndUnzipVSCode({version:'stable',cachePath:cache});
 const currentMacExecutable=path.join(path.dirname(downloaded),'Code');
 const executable=process.platform==='darwin'&&fs.existsSync(currentMacExecutable)?currentMacExecutable:downloaded;
 const profile=fs.mkdtempSync(path.join(cache,'installed-host-')),extensionsDir=path.join(profile,'extensions'),userDataDir=path.join(profile,'user-data');
 fs.mkdirSync(extensionsDir,{recursive:true});fs.mkdirSync(userDataDir,{recursive:true});
 const install=await runVSCodeCommand([`--install-extension=${vsix}`,`--extensions-dir=${extensionsDir}`,`--user-data-dir=${userDataDir}`,'--force'],{version:'stable',cachePath:cache});
 process.stdout.write(install.stdout);process.stderr.write(install.stderr);
 const workspace=fs.mkdtempSync(path.join(cache,'review-workspace-'));
 fs.writeFileSync(path.join(workspace,'a.txt'),'one\ntwo\nthree\nfour\n');
 await runTests({
  vscodeExecutablePath:executable,
  extensionDevelopmentPath:path.join(__dirname,'driver'),
  extensionTestsPath:path.join(__dirname,'suite'),
  launchArgs:[workspace,`--extensions-dir=${extensionsDir}`,`--user-data-dir=${userDataDir}`],
  extensionTestsEnv:{
   PAIR_REVIEW_PROJECT_ROOT:root,
   PAIR_REVIEW_HOST_WORKSPACE:workspace,
   PAIR_REVIEW_EXTENSIONS_DIR:extensionsDir,
   PAIR_REVIEW_UV_PATH:process.env.PAIR_REVIEW_UV_PATH||'uv'
  }
 });
}
main().catch(error=>{console.error(error);process.exitCode=1});
