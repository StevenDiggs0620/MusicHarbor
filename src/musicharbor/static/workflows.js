'use strict';
// Workflow components are kept separate from the screen templates.
let purchaseView='grouped';
let purchaseDisplay={sort:'default',minPlays:'',minReleaseTracks:'',minPlaylistSongs:''};
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
function purchaseDisplayMetrics(ids,group,individual=false){
  const items=ids.map(id=>project.releases[id]).filter(Boolean),first=items[0];
  if(!first)return {price:null,plays:group?.play_count??null,releaseTracks:null,playlistSongs:0};
  const source=first.songs?.[0]||{};
  const collectionId=String(first.release_id||source.collectionId||first.id.replace(/^album:/,''));
  const album=project.releases['album:'+collectionId]||items.find(r=>r.id==='album:'+collectionId);
  const covered=new Set([...(album?.coverage||[]),...items.flatMap(r=>r.coverage||[])]);
  const playlistIds=new Set(project.tracks.map(t=>t.recording_id));
  const playlistSongs=[...covered].filter(id=>playlistIds.has(id)&&project.recordings[id]?.included).length;
  const prices=individual?[first.price]:items.map(r=>r.price);
  const code=individual?first.currency:(items[0]?.currency);
  const price=prices.length&&prices.every(value=>value!=null&&Number.isFinite(Number(value))&&Number(value)>=0)
    ?prices.reduce((sum,value)=>sum+Math.round(Number(value)*100),0)/100:null;
  return {price,plays:group?.play_count??null,releaseTracks:album?.track_count??first.track_count??null,playlistSongs};
}
function purchaseDisplayControls(){
  return `<section class="panel purchase-display-panel"><h3>Sort and filter these results</h3><form id="purchase-display-form" class="purchase-display-options"><label>Sort by<select name="sort"><option value="default" ${purchaseDisplay.sort==='default'?'selected':''}>Purchase plan order</option><option value="price" ${purchaseDisplay.sort==='price'?'selected':''}>Lowest purchase price</option><option value="listens" ${purchaseDisplay.sort==='listens'?'selected':''}>Most listens</option><option value="releaseTracks" ${purchaseDisplay.sort==='releaseTracks'?'selected':''}>Most tracks on release</option><option value="playlistSongs" ${purchaseDisplay.sort==='playlistSongs'?'selected':''}>Most included playlist songs</option></select></label><label>Minimum listens<input name="minPlays" type="number" min="1" step="1" value="${esc(purchaseDisplay.minPlays)}" placeholder="Any"></label><label>Minimum tracks on release<input name="minReleaseTracks" type="number" min="1" step="1" value="${esc(purchaseDisplay.minReleaseTracks)}" placeholder="Any"></label><label>Minimum included playlist songs<input name="minPlaylistSongs" type="number" min="1" step="1" value="${esc(purchaseDisplay.minPlaylistSongs)}" placeholder="Any"></label><div class="actions"><button type="submit">Apply options</button><button type="button" class="secondary" data-action="purchase-display-reset">Clear filters</button></div><small>Filters apply to the selected purchases. Listen totals need synced listening history. Sorting and filtering do not change the calculated plan or its total.</small></form></section>`;
}
function displayFiltersMatch(metrics){
  const minPlays=purchaseDisplay.minPlays===''?null:Number(purchaseDisplay.minPlays);
  const minTracks=purchaseDisplay.minReleaseTracks===''?null:Number(purchaseDisplay.minReleaseTracks);
  const minSongs=purchaseDisplay.minPlaylistSongs===''?null:Number(purchaseDisplay.minPlaylistSongs);
  return (minPlays===null||(metrics.plays!==null&&metrics.plays>=minPlays))
    &&(minTracks===null||(metrics.releaseTracks!==null&&metrics.releaseTracks>=minTracks))
    &&(minSongs===null||metrics.playlistSongs>=minSongs);
}
function sortPurchaseEntries(entries){
  const sort=purchaseDisplay.sort;
  if(sort==='default')return entries;
  const key={price:'price',listens:'plays',releaseTracks:'releaseTracks',playlistSongs:'playlistSongs'}[sort];
  return entries.slice().sort((a,b)=>{
    const left=a.metrics[key],right=b.metrics[key];
    if(left==null&&right!=null)return 1;
    if(right==null&&left!=null)return -1;
    if(left===right)return a.index-b.index;
    return sort==='price'?left-right:right-left;
  });
}
function purchaseCards(plan,match){
  const groups=plan.purchase_groups||[];
  if(purchaseView==='strategy'){
    const entries=plan.release_ids.map((id,index)=>{
      const group=groups.find(g=>g.release_ids.includes(id));
      return {release:project.releases[id],group,index,metrics:purchaseDisplayMetrics([id],group,true)};
    }).filter(x=>x.release&&match(x.release)&&displayFiltersMatch(x.metrics));
    return sortPurchaseEntries(entries).map(x=>releaseCard(x.release,priorityStrategies.has(plan.strategy)&&purchaseDisplay.sort==='default'?x.index+1:undefined)).join('');
  }
  const entries=groups.map((group,index)=>({group,index,items:group.release_ids.map(id=>project.releases[id]).filter(Boolean),metrics:purchaseDisplayMetrics(group.release_ids,group)}))
    .filter(x=>x.items.length&&x.items.some(match)&&displayFiltersMatch(x.metrics));
  return sortPurchaseEntries(entries).map(x=>purchaseGroupCard(x.group,x.items.filter(match))).join('');
}
