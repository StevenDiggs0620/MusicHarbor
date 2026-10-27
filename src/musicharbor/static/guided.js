'use strict';
// Guided screens keep the original route and action contracts available.
let deferredMatches=new Set();
let activeJobs=[];
let activityExpanded=false;
const priorityStrategies=new Set(['most-songs','songs-per-dollar','artist']);
function journey(page){return page==='import'?'<p class="setup-guide">Add a playlist → Check uncertain matches → Plan purchases → Export owned music</p>':'';}
function musicTabs(page){
  return `<nav class="subnav" aria-label="My music views"><a href="#owned" ${page==='owned'?'aria-current="page"':''}>Owned songs</a><a href="#library" ${page==='library'?'aria-current="page"':''}>Local files</a></nav>`;
}
function buyTabs(page){
  return `<nav class="subnav" aria-label="Buying views"><a href="#plan" ${page==='plan'?'aria-current="page"':''}>Purchase plan</a><a href="#review" ${page==='review'?'aria-current="page"':''}>Check matches (${recordings().filter(unresolved).length})</a></nav>`;
}
function guidedImport(){
  return heading('Add your playlist','Choose how to bring your songs into the app.','GET STARTED')+journey('import')+
    `<section class="panel"><h2>How would you like to add it?</h2><div class="choice-grid"><button class="choice" data-action="choose-import" data-id="playlist-file"><strong>Import a playlist file</strong><span>Use an Exportify CSV. No Spotify developer setup required.</span></button><button class="choice" data-action="choose-import" data-id="spotify-import"><strong>Use Spotify directly</strong><span>Use a saved connection or set up Spotify access.</span></button></div></section>
    <details class="panel" id="playlist-file" open><summary>Import a playlist file</summary><details class="help-disclosure"><summary>How do I get an Exportify file?</summary><ol><li>Open <a href="https://exportify.net" target="_blank" rel="noopener noreferrer">Exportify</a> and sign in there.</li><li>Export the playlist you want as a CSV file.</li><li>Choose the downloaded file below and check its preview.</li></ol><p>Already have a CSV? Start below. Your original file stays unchanged.</p></details>${csvImportPanel()}</details>
    <details class="panel" id="spotify-import"><summary>Import directly from Spotify</summary><p>${settings.connected?'Your account is connected. Paste the playlist link below.':'This route needs Spotify developer setup. File import above is available without it.'}</p><a class="button secondary" href="#settings">${settings.connected?'Connection settings':'Set up Spotify connection'}</a><form id="import-form" class="stack spaced"><label>Spotify playlist link<input name="url" required maxlength="2000" placeholder="https://open.spotify.com/playlist/…"></label><label>Purchase country<select name="storefront">${optionsStore(settings.storefront)}</select></label><button type="submit">Import from Spotify</button></form></details>
    ${project?`<details class="panel"><summary>Add to or replace the selected playlist instead</summary><a class="button secondary" href="#update">Update selected playlist</a></details>`:''}`;
}
function candidateDetails(c){
  return `<details class="match-details"><summary>Technical match details</summary><p>Confidence score: ${esc(c.score)}/100 · ${esc(c.confidence)}</p><ul>${(c.reasons||[]).map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul>${storeLink(c.song.trackViewUrl)}</details>`;
}
function matchVersion(song){return song.trackExplicitness==='explicit'?'Explicit':['cleaned','notExplicit'].includes(song.trackExplicitness)?'Clean / non-explicit':'Explicitness unknown';}
function decoratePurchaseCards(){
  document.querySelectorAll('.release-info > .actions').forEach(row=>{
    if(row.dataset.guided)return;row.dataset.guided='true';
    row.querySelector('a')?.classList.add('button');
    row.querySelectorAll('button').forEach(b=>b.classList.add('secondary'));
    const exclude=row.querySelector('[data-action="exclude-release"]');
    if(exclude){const details=document.createElement('details');details.className='more-actions';details.innerHTML='<summary>Include / exclude release</summary>';exclude.before(details);details.append(exclude);}
  });
  document.querySelectorAll('.album-group-controls').forEach(panel=>{
    if(panel.dataset.guided)return;panel.dataset.guided='true';
    const owned=panel.closest('.album-group')?.classList.contains('owned');
    const label=panel.querySelector('.album-controls-label');if(label){label.textContent=owned?'Ownership for the whole release':'Buy or manage the whole release';}
    panel.classList.add('spaced');panel.querySelectorAll('button').forEach(b=>b.classList.add('secondary'));
  });
}
function decorateGuidedScreen(page){
  if(['owned','library'].includes(page)&&!$('#main .subnav'))$('#main > .lede').insertAdjacentHTML('afterend',musicTabs(page));
  if(page==='library'){
    const form=$('#scan-form');
    if(form&&!form.dataset.guided){
      form.dataset.guided='true';
      const input=$('#folder'),label=form.querySelector('label[for="folder"]');
      const manual=document.createElement('details');manual.id='manual-folder';manual.innerHTML='<summary>Enter or edit a folder path</summary>';
      input.before(manual);manual.append(label,input);
      form.insertAdjacentHTML('afterbegin','<h2>Find music you already own</h2><p>Choose the folder containing your music, then scan it. We’ll identify songs and reuse matching files across playlists.</p><button type="button" data-action="choose-folder">Choose music folder…</button><p id="selected-folder" class="muted" aria-live="polite"></p>');
      $('#selected-folder').textContent=input.value||'No folder selected yet.';
      form.querySelector('[type="submit"]').textContent='Scan music';
      form.insertAdjacentHTML('beforeend','<button type="button" class="secondary" data-action="review-library-files">Review local-file matches</button>');
      form.insertAdjacentHTML('beforeend','<a href="#overview">Back to my next step</a>');
    }
  }
  if(page==='settings'){
    document.querySelectorAll('#settings-form > section, #main > section').forEach(section=>{
      const title=section.querySelector('h2');if(!title)return;
      const details=document.createElement('details');details.className='panel settings-section';details.open=['Spotify connection','Matching preferences'].includes(title.textContent);
      const summary=document.createElement('summary');summary.textContent=title.textContent;details.append(summary);
      section.before(details);title.remove();section.classList.remove('panel');details.append(section);
    });
  }
  if(page==='import'){
    const panel=$('#csv-import-panel');if(panel){panel.classList.remove('panel','hero');panel.querySelector('.eyebrow')?.remove();const heading=panel.querySelector('h2');if(heading)heading.textContent='Choose your CSV file';}
    const preview=$('#csv-import-form button[value="preview"]');if(preview)preview.textContent='Preview playlist';
  }
  decoratePurchaseCards();
}
function handleGuidedChange(event){
  const input=event.target;
  if(input.id==='strategy'){
    const value=input.value;
    $('#budget-choice').hidden=value!=='best-value';$('#budget').disabled=value!=='best-value';
    $('#artist-choice').hidden=value!=='artist';$('#artist').disabled=value!=='artist';$('#artist').required=value==='artist';
    $('#strategy-description').textContent=strategies[value][1];
  }
  if(input.name==='export-preset'){
    const device=input.value==='device';
    $('#device-export').hidden=!device;$('#export-custom').checked=device;
    $('#export-path-fields').hidden=!device;
    if(!device)$('#export-slashes').value='macos';
    if(device){$('#export-replace-mode').value='prefix';syncDeviceDestination();}
  }
  if(input.id==='device-folder')syncDeviceDestination();
  if(input.id==='export-custom'&&!input.checked){
    $('input[name="export-preset"][value="mac"]').checked=true;
    $('#device-export').hidden=true;
  }
  if(input.id==='export-to')$('#device-folder').value=input.value;
  if(['export-custom','export-from','export-to','export-slashes','export-replace-mode'].includes(input.id))updateDeviceExample();
  if(input.id==='folder'&&$('#selected-folder'))$('#selected-folder').textContent=input.value||'No folder selected yet.';
}
const guidedActions={
  'show-song-choices':()=>{const panel=$('#song-choices');panel.open=true;$('#song-search').focus();},
  'retry-export-preview':()=>refreshExportPreview(),
  'purchase-view':(id)=>{purchaseView=id;renderPlanResult();},
  'choose-import':id=>{const panel=document.getElementById(id);panel.open=true;panel.querySelector('summary').focus();panel.scrollIntoView({block:'start',behavior:'smooth'});},
  'skip-library':async()=>{sessionStorage.setItem('pp-library-skipped:'+project.id,'yes');await render();},
  'show-versions':()=>{const panel=$('#other-versions');panel.open=true;panel.querySelector('summary').focus();},
  'defer-match':async id=>{deferredMatches.add(project.id+':'+id);selectedRecording=null;await render();},
  'resume-review':async()=>{deferredMatches=new Set([...deferredMatches].filter(id=>!id.startsWith(project.id+':')));await render();},
  'show-activity':()=>{activityExpanded=true;const details=$('#activity-details');if(details){details.open=true;details.querySelector('summary')?.focus();}else notify('No background activity to show.');},
  'choose-folder':async()=>{
    const form=$('#scan-form'),input=$('#folder'),pid=project.id;
    if(!window.pywebview?.api?.choose_folder){$('#manual-folder').open=true;input.focus();notify('Folder selection is available in the desktop app. Here, paste your music folder path.');return;}
    const path=await window.pywebview.api.choose_folder();
    if(!path||project?.id!==pid||!form.isConnected)return;
    input.value=path;form.dataset.dirty='true';$('#selected-folder').textContent=path;form.querySelector('[type="submit"]').focus();
  }
};
function renderGuidedJobs(jobs){
  activeJobs=jobs;
  const target=$('#job-bar'),old=target.querySelector('details');
  if(old)activityExpanded=old.open;
  const snapshot=JSON.stringify(jobs);
  if(target.dataset.snapshot===snapshot)return;
  target.dataset.snapshot=snapshot;
  const scroll=target.querySelector('.activity-history')?.scrollTop||0;
  const focus=document.activeElement;
  const focused=target.contains(focus)?{action:focus.dataset.action,id:focus.dataset.id,summary:focus.tagName==='SUMMARY'}:null;
  target.hidden=!jobs.length;target.style.height='auto';
  if(!jobs.length){target.innerHTML='';return;}
  const running=jobs.filter(j=>['running','queued'].includes(j.status));
  const newest=jobs[0],label=running.length?`${running.length} task${running.length===1?'':'s'} in progress`:newest.status==='error'?'A task needs attention':newest.status==='cancelled'?'Task cancelled':'Work complete';
  const kindLabel={discover:'Finding Store matches',scan:'Finding music you own',import:'Adding playlist songs',refresh:'Updating releases and prices',plan:'Calculating purchases',release:'Loading a release',listening:'Updating listening history'};
  target.innerHTML=`<details id="activity-details" ${activityExpanded?'open':''}><summary><strong>Activity</strong><span>${esc(label)}</span><span class="muted">Show details and history</span></summary><div class="activity-history">${jobs.map(job=>`<article class="job-card"><div class="section-head"><strong>${esc(kindLabel[job.kind]||job.kind||'Background task')} · ${esc({queued:'Waiting',running:'In progress',done:'Complete',error:'Needs attention',cancelled:'Cancelled'}[job.status]||job.status)}</strong>${['running','queued'].includes(job.status)?`<button class="small secondary" data-action="cancel-operation" data-id="${esc(job.id)}">Cancel</button>`:`<button class="small secondary" data-action="dismiss-operation" data-id="${esc(job.id)}">Dismiss</button>`}</div>${(job.stages||[]).map(stage=>`<div class="job-stage"><div><span>${esc(stage.label)}</span><strong>${stage.percent!=null?`${stage.percent}%`:esc({pending:'Next',running:'Working',done:'Done'}[stage.status]||stage.status)}</strong></div>${stage.status==='running'?`<progress max="100" ${stage.percent!=null?`value="${stage.percent}"`:''} aria-label="${esc(stage.label)}"></progress>`:''}</div>`).join('')}<p>${esc(job.error||job.message||'')}</p>${job.status==='done'?'<a href="#overview">See my next step</a>':''}</article>`).join('')}</div></details>`;
  if(running.length){const job=running[0],stage=(job.stages||[]).find(s=>s.status==='running');target.insertAdjacentHTML('beforeend',`<div class="activity-current"><span>${esc(stage?.label||kindLabel[job.kind]||'Working…')}${stage?.percent!=null?' · '+esc(stage.percent)+'%':''}</span><button class="small secondary" data-action="cancel-operation" data-id="${esc(job.id)}">Cancel${running.length>1?' this task':''}</button></div>`);}
  target.querySelector('.activity-history').scrollTop=scroll;
  if(focused){const candidate=focused.summary?target.querySelector('summary'):[...target.querySelectorAll('[data-action]')].find(b=>b.dataset.action===focused.action&&b.dataset.id===focused.id);candidate?.focus({preventScroll:true});}
}
document.addEventListener('invalid',event=>{
  let parent=event.target.parentElement;
  while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}
},true);
document.addEventListener('click',event=>{
  const skip=event.target.closest('a.skip');if(skip){event.preventDefault();const main=document.getElementById('main');main.tabIndex=-1;main.focus();}
});
