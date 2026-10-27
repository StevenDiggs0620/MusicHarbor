'use strict';
// Workflow components are kept separate from the screen templates.
let purchaseView='grouped';
let libraryPage={files:[],recordings:{},total:0,next_offset:null};
let planningRequests=new Map();
async function requestPlan(pid,options,version=renderVersion) {
  const key=pid+JSON.stringify(options)+':'+version;
  if(planningRequests.has(key))return planningRequests.get(key);
  const promise=(async()=>{
    const started=await api(`/api/projects/${enc(pid)}/plan/start`,'POST',options);
    let failures=0;
    while(true){
      if(project?.id!==pid || renderVersion!==version){
        await api(`/api/jobs/${enc(started.job)}/cancel`,'POST',{});
        throw new Error('Calculation cancelled after navigation.');
      }
      let job;
      try {job=await api(`/api/jobs/${enc(started.job)}`);await refreshJobs();failures=0;}
      catch(error){failures++;notify('Reconnecting to the calculation…',true);await new Promise(r=>setTimeout(r,Math.min(10000,1000*failures)));continue;}
      if(job.status==='done')return job.result;
      if(['cancelled','error'].includes(job.status))throw new Error(job.error||job.message);
      await new Promise(r=>setTimeout(r,500));
    }
  })();
  planningRequests.set(key,promise);
  try{return await promise;}finally{planningRequests.delete(key);}
}
async function loadLibrary(offset=0,version=renderVersion){
  const pid=project.id;
  const page=await api(`/api/projects/${enc(pid)}/library?offset=${offset}&limit=100`);
  if(project?.id!==pid||version!==renderVersion)return;
  libraryPage=page;
  if(location.hash==='#library'){
    const scan=$('#scan-form');
    $('#main').innerHTML=libraryScreen();
    if(scan?.dataset.dirty==='true')$('#scan-form').replaceWith(scan);
    decorateGuidedScreen('library');
  }
}
function libraryNavigation(){
  return `<p>Showing ${libraryPage.files.length} of ${libraryPage.total} library files.</p><div class="actions"><button class="secondary" data-action="library-page" data-id="${Math.max(0,(libraryPage.offset||0)-100)}" ${!libraryPage.offset?'disabled':''}>Previous 100</button><button class="secondary" data-action="library-page" data-id="${libraryPage.next_offset??0}" ${libraryPage.next_offset==null?'disabled':''}>Next 100</button></div>`;
}
function exportFileControls(){
  const groups=new Map();
  for(const file of project.local_files){if(file.status==='matched'&&file.recording_id){if(!groups.has(file.recording_id))groups.set(file.recording_id,[]);groups.get(file.recording_id).push(file);}}
  return `<label>Preferred format<select id="export-preferred-format">${['any','flac','m4a','mp3','wav','aac','ogg'].map(x=>`<option value="${x}">${x==='any'?'Any format':x.toUpperCase()}</option>`).join('')}</select></label><label>Preferred folder<input id="export-preferred-folder" placeholder="Optional folder path"></label><label class="check"><input type="checkbox" id="export-quality" checked> Prefer lossless, then higher bit depth, sample rate and bitrate</label><details><summary>Choose a specific copy for a recording</summary><p>Folder and format preferences rank available copies. A specific choice takes precedence and is saved with this project.</p>${recordings().filter(r=>(groups.get(r.id)||[]).length>1||project.export_file_overrides?.[r.id]).map(r=>`<label>${esc(r.artist)} — ${esc(r.title)}<select data-export-recording="${esc(r.id)}"><option value="">Automatic selection</option>${project.export_file_overrides?.[r.id]&&!groups.get(r.id)?.some(f=>f.path===project.export_file_overrides[r.id])?`<option selected value="${esc(project.export_file_overrides[r.id])}">Unavailable: ${esc(project.export_file_overrides[r.id])}</option>`:''}${(groups.get(r.id)||[]).sort((a,b)=>a.path.localeCompare(b.path)).map(f=>`<option value="${esc(f.path)}" ${project.export_file_overrides?.[r.id]===f.path?'selected':''}>${esc(f.path)}</option>`).join('')}</select></label>`).join('')||'<p>No recordings have multiple matched copies.</p>'}</details>`;
}
function retentionControls(){
  const p=settings.retention||{};
  return `<section class="panel"><h2>History retention</h2><p>Expired catalog cache is cleared automatically. Price history records changes only. Cleanup never removes projects, matches, ownership decisions, or music files.</p><div class="grid"><label>Keep completed jobs (days)<input name="job_days" type="number" min="1" max="3650" value="${p.job_days??30}" required></label><label>Keep price changes (days)<input name="price_days" type="number" min="1" max="3650" value="${p.price_days??365}" required></label><label>Export records per project<input name="export_count" type="number" min="1" max="10000" value="${p.export_count??100}" required></label></div><button type="submit">Save retention settings</button></section>`;
}
function purchaseCards(plan,match){
  if(purchaseView==='strategy')return plan.release_ids.map((id,index)=>({release:project.releases[id],rank:priorityStrategies.has(plan.strategy)?index+1:undefined})).filter(x=>x.release&&match(x.release)).map(x=>releaseCard(x.release,x.rank)).join('');
  return (plan.purchase_groups||[]).map(group=>purchaseGroupCard(group,group.release_ids.map(id=>project.releases[id]).filter(Boolean).filter(match))).join('');
}
