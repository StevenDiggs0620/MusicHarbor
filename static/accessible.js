'use strict';
// Frequent tasks stay visible; disclosures contain supporting detail only.
let reviewFilter='needs';
let calculatedOptions=null, planPending=false, comparisonPending=false;
let calculationGeneration=0;
const strategies={
  cheapest:['Spend the least','Find the lowest-priced combination covering the available songs you still need.'],
  fewest:['Fewest purchases','Cover the available songs using the fewest Store products; this may cost more.'],
  'best-value':['Stay within a budget','Choose songs within your budget, prioritizing listening history when connected.'],
  'most-songs':['Most songs first','Order purchases by how many additional songs each one gives you.'],
  'songs-per-dollar':['Most songs per dollar','Order purchases by additional songs per dollar spent.'],
  artist:['Focus on an artist','Put purchases covering your chosen artist first.']
};
function playlistNeedsReview(){return recordings().filter(r=>unresolved(r)&&!r.effective_owned);}
function reviewRows(){
  return recordings().filter(r=>reviewFilter==='all'||(reviewFilter==='later'?deferredMatches.has(project.id+':'+r.id):unresolved(r)&&!r.effective_owned&&!deferredMatches.has(project.id+':'+r.id)));
}
function accessibleSongs(){
  return heading('Playlist songs','Search, include songs, change ownership, or check a version.')+
    `<section class="panel"><div class="actions"><a class="button secondary" href="#review">Check matches</a><a class="button secondary" href="#update">Add or replace songs</a><a class="button secondary" href="#plan">Plan purchases</a></div><label for="song-search" class="spaced">Find a song or artist</label><input id="song-search" type="search" value="${esc(query)}"><div id="song-table">${songTable(filtered(recordings()))}</div></section><details class="panel"><summary>Original playlist order (${project.tracks.length} entries)</summary><ol>${project.tracks.map(t=>{const r=t.source_metadata||project.recordings[t.recording_id];return `<li>${esc(r.artist)} — ${esc(r.title)}${t.source_row?` · CSV line ${esc(t.source_row)}`:''}</li>`;}).join('')}</ol></details>`;
}
function accessibleOverview(){
  if(!project)return heading('Start with a playlist','Import a CSV file or use your Spotify connection.')+journey('import')+'<section class="panel"><a class="button" href="#import">Add playlist</a> <a class="button secondary" href="#projects">Open or restore a playlist</a></section>';
  const songs=recordings(),included=songs.filter(r=>r.included),owned=included.filter(r=>r.effective_owned),review=playlistNeedsReview();
  const local=new Set(project.local_files.filter(f=>f.status==='matched').map(f=>f.recording_id));
  const ready=owned.filter(r=>local.has(r.id));
  let title='Choose purchases',body=`You own ${owned.length} of ${included.length} included songs.`,route='plan';
  if(!songs.length){title='Add songs';body='Import a file or a Spotify playlist to start.';route='import';}
  else if(!included.length){title='Choose songs to include';body='All songs are currently skipped. Include the ones you want to buy or export.';route='songs';}
  else if(!project.library_folders?.length&&sessionStorage.getItem('pp-library-skipped:'+project.id)!=='yes'){title='Find music you already own';body='Choose your music folder before buying songs you may already have.';route='library';}
  else if(review.length){title=`Check ${review.length} song matches`;body='Review uncertain playlist versions before relying on a complete purchase estimate.';route='review';}
  else if(owned.length===included.length){title=ready.length===owned.length?'Export your playlist':'Find remaining local files';body=ready.length===owned.length?'Your included songs have matched local files. Export checks that the files still exist.':'Some owned songs need local files before export.';route=ready.length===owned.length?'export':'library';}
  return heading(esc(project.name),'Your progress and next step.','OVERVIEW')+`<section class="panel next-step"><span class="step-label">Next step</span><h2>${title}</h2><p>${body}</p><div class="actions"><a class="button" href="#${route}">${title}</a>${route==='library'?'<button class="secondary" data-action="skip-library">Skip for now</button>':''}${project.busy?'<button class="secondary" data-action="show-activity">View background progress</button>':''}</div></section><div class="stats"><div class="stat"><strong>${songs.length}</strong><span>Unique songs · ${project.tracks.length} playlist entries</span></div><div class="stat"><strong>${owned.length}</strong><span>Included songs owned</span></div><div class="stat"><strong>${review.length}</strong><span>Playlist matches to check, including set-aside songs</span></div><div class="stat"><strong>${ready.length}</strong><span>Included songs with matched files</span></div></div><div class="actions"><a class="button secondary" href="#songs">View playlist songs</a><a class="button secondary" href="#update">Add or replace songs</a><a class="button secondary" href="#export">Export available songs</a></div>`;
}
function accessibleUpdate(){return heading('Update this playlist','Add songs or replace the list while keeping saved matches and ownership.')+playlistUpdatePanel()+(project.source_url?'<button class="secondary" data-action="reimport">Replace from linked Spotify playlist</button>':'');}
function accessibleReview(){
  const needs=playlistNeedsReview(),later=recordings().filter(r=>deferredMatches.has(project.id+':'+r.id));
  const list=reviewRows();if(!list.some(r=>r.id===selectedRecording))selectedRecording=list[0]?.id;
  const r=project.recordings[selectedRecording];
  const controls=`<div class="section-head"><div class="segmented" role="group" aria-label="Playlist match filters">${[['needs',`Needs review (${needs.filter(r=>!deferredMatches.has(project.id+':'+r.id)).length})`],['later',`Set aside (${later.length})`],['all',`All songs (${recordings().length})`]].map(([id,label])=>`<button class="secondary" data-action="review-filter" data-id="${id}" aria-pressed="${reviewFilter===id}">${label}</button>`).join('')}</div><button class="secondary" data-action="discover">Find Store matches</button></div><p class="muted">This view contains only this playlist’s songs. <a href="#library">Review local-file matches in My music</a>.</p>`;
  const lead=heading('Check matches','Compare the song, artist, version, and length before accepting.')+controls;
  if(!r)return lead+empty('No songs in this view','Use Set aside or All songs to inspect other playlist songs.','<a class="button" href="#plan">Plan purchases</a>');
  const candidates=(r.candidates||[]).filter(c=>c.song&&!(r.rejected||[]).includes(String(c.song.trackId)));
  const top=candidates[0],s=top?.song;
  const seconds=(s?.trackTimeMillis||0)/1000;
  const weak=!s||top.confidence!=='high'||(r.duration&&seconds&&Math.abs(r.duration-seconds)>10);
  const differences=[];
  if(s){if(r.title!==s.trackName)differences.push('Titles differ—check version labels.');if(r.artist!==s.artistName)differences.push('Artist credits differ—check the performer.');if(r.duration&&seconds&&Math.abs(r.duration-seconds)>3)differences.push(`Duration differs by ${Math.round(Math.abs(r.duration-seconds))} seconds.`);if(r.explicit!=null&&['explicit','cleaned','notExplicit'].includes(s.trackExplicitness)&&r.explicit!==(s.trackExplicitness==='explicit'))differences.push('Clean / explicit versions differ.');}
  return lead+`<div class="review-layout"><div class="review-list" aria-label="Playlist songs to review">${list.map(x=>`<button class="${x.id===r.id?'selected':''}" data-action="select-recording" data-id="${esc(x.id)}"><strong>${esc(x.title)}</strong><small>${esc(x.artist)}</small></button>`).join('')}</div><section class="panel"><div class="metadata"><div class="comparison-side"><span class="step-label">Your playlist song</span><h3>${esc(r.title)}</h3><p>${esc(r.artist)}<br>${esc(r.album)}</p><p>${duration(r.duration)} · ${r.explicit===true?'Explicit':r.explicit===false?'Clean / non-explicit':'Explicitness unknown'}</p>${r.selected?`<p>Accepted match: ${esc(r.selected.trackName)} · ${esc(r.selected.artistName)} · ${esc(r.selected.collectionName)}</p>`:''}</div><div class="comparison-side"><span class="step-label">${weak?'Possible Store version':'Suggested Store version'}</span>${s?`<h3>${esc(s.trackName)}</h3><p>${esc(s.artistName)}<br>${esc(s.collectionName)}</p><p>${duration(seconds)} · ${matchVersion(s)}</p>${storeLink(s.trackViewUrl)}`:'<p>No match found. Search below.</p>'}</div></div>${weak?`<div class="warning spaced"><strong>${s?'Check this version carefully':'No reliable match found'}</strong><p>${s?'This is a weak or uncertain match. Search alternatives before accepting it.':'Try the song title and artist below.'}</p></div>`:''}${differences.length?`<ul>${differences.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<div class="actions spaced">${weak?'<button data-action="show-versions">Find another version</button>':''}${s?`<button class="${weak?'secondary':''}" data-action="confirm-match" data-id="${esc(s.trackId)}">${weak?'Accept this version anyway':'Accept match'}</button>`:''}${!weak?'<button class="secondary" data-action="show-versions">Find another version</button>':''}<button class="secondary" data-action="defer-match" data-id="${esc(r.id)}">Skip for now</button><button class="secondary" data-action="own-recording" data-id="${esc(r.id)}">${r.effective_owned?'Undo ownership':'Already own this'}</button>${deferredMatches.has(project.id+':'+r.id)?`<button class="secondary" data-action="resume-song" data-id="${esc(r.id)}">Return to review</button>`:''}</div><form id="manual-search" class="stack spaced"><label for="manual-term">Find another version by song title and artist</label><input id="manual-term" name="term" value="${esc(r.artist+' '+r.title)}" required maxlength="300"><button type="submit">Search Store</button></form>${s?`<button class="secondary spaced" data-action="reject-match" data-id="${esc(s.trackId)}">Reject this suggestion</button>`:''}<div class="actions spaced"><button class="secondary" data-action="include" data-id="${esc(r.id)}">${r.included?'Exclude from playlist purchases':'Include this song'}</button><button class="secondary" data-action="required" data-id="${esc(r.id)}">${r.required?'Remove required status':'Require in budget plans'}</button>${r.selected?`<button class="secondary" data-action="load-release" data-id="${esc(r.id)}">Load accepted release</button>`:''}${r.ownership_override!=null?`<button class="secondary" data-action="reset-ownership" data-id="${esc(r.id)}">Use release ownership</button>`:''}</div><details class="spaced"><summary>Technical details</summary><p>ISRC: ${esc(r.isrc||'Not supplied')}</p>${top?`<p>Match confidence: ${esc(top.confidence)} · ${esc(top.score)}/100</p><ul>${(top.reasons||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<p>${esc((r.match_evidence?.reasons||[]).join(' · '))}</p>${safeURL(r.spotify_url,'spotify')?`<a href="${esc(safeURL(r.spotify_url,'spotify'))}" target="_blank" rel="noopener noreferrer">Original Spotify song</a>`:''}</details><section id="other-versions" class="spaced"><h2>Other versions (${Math.max(0,candidates.length-1)})</h2>${candidatePage(candidates.slice(1),'recording:'+r.id).map(c=>`<article class="candidate"><h3>${esc(c.song.trackName)}</h3><p>${esc(c.song.artistName)} · ${esc(c.song.collectionName)}<br>${duration((c.song.trackTimeMillis||0)/1000)} · ${matchVersion(c.song)}</p><div class="actions"><button class="secondary" data-action="confirm-match" data-id="${esc(c.song.trackId)}">Accept this version</button><button class="secondary" data-action="reject-match" data-id="${esc(c.song.trackId)}">Reject</button>${storeLink(c.song.trackViewUrl)}</div>${candidateDetails(c)}</article>`).join('')||'<p>No other versions yet. Search above to find more.</p>'}${moreCandidates(candidates.slice(1),'recording:'+r.id)}</section></section></div>`;
}
function accessiblePlan(){
  return heading('Purchase plan','Choose a strategy, calculate, then buy in the Store.')+`<section class="panel"><form id="plan-form" class="stack"><label for="strategy">Purchase strategy</label><select id="strategy" name="strategy" aria-describedby="strategy-description">${Object.entries(strategies).map(([id,[label]])=>`<option value="${id}" ${planOptions.strategy===id?'selected':''}>${label}</option>`).join('')}</select><p id="strategy-description">${strategies[planOptions.strategy][1]}</p><div id="budget-choice" ${planOptions.strategy==='best-value'?'':'hidden'}><label for="budget">Your budget (${currency[project.storefront]})</label><input id="budget" name="budget" type="number" min="0" max="1000000" step="0.01" value="${planOptions.budget??''}" ${planOptions.strategy==='best-value'?'':'disabled'}><small>Leave blank for no limit. Songs marked required must fit.</small></div><div id="artist-choice" ${planOptions.strategy==='artist'?'':'hidden'}><label for="artist">Artist to focus on</label><input id="artist" name="artist" maxlength="200" value="${esc(planOptions.artist)}" ${planOptions.strategy==='artist'?'required':'disabled'}></div><div class="actions"><button type="submit">Calculate plan</button><button class="secondary" type="button" data-action="refresh-prices">Update releases &amp; prices</button></div><details id="advanced-planning"><summary>Advanced: purchase penalty</summary><label for="penalty">Cost per extra purchase when comparing budget plans</label><input id="penalty" name="purchase_penalty" type="number" min="0" max="10000" step="0.25" value="${planOptions.purchase_penalty}"><p class="muted">This is a planning preference, not a Store fee.</p></details></form></section><div id="plan-state" role="status" aria-live="polite"></div><label for="release-search">Find a release in your results</label><input id="release-search" type="search" value="${esc(query)}"><div id="plan-result"><p>Choose a strategy, then calculate your purchases.</p></div><details class="panel spaced"><summary>Listening history and ranking</summary>${listeningSummary()}</details>`;
}
function currentPlanInputs(){
  const f=$('#plan-form');if(!f)return planOptions;
  const data=new FormData(f),strategy=data.get('strategy');
  return {strategy,budget:strategy==='best-value'&&data.get('budget')!==''?Number(data.get('budget')):null,purchase_penalty:Number(data.get('purchase_penalty')),artist:strategy==='artist'?(data.get('artist')||''):''};
}
function planKey(o){return JSON.stringify([o.strategy,o.strategy==='best-value'?o.budget:null,o.strategy==='best-value'?o.purchase_penalty:0,o.strategy==='artist'?o.artist:'']);}
function updatePlanState(){
  const state=$('#plan-state');if(!state)return;
  const stale=currentPlan&&calculatedOptions&&planKey(currentPlanInputs())!==planKey(calculatedOptions);
  state.className=stale?'warning spaced':'';
  state.textContent=stale?'Options changed—recalculate. The results below still use the settings shown with them.':planPending?'Calculating your plan… Previous results, if shown, remain labeled below.':'';
}
function renderAccessiblePlanResult(){
  const target=$('#plan-result');if(!target||!currentPlan)return;
  const p=currentPlan,o=calculatedOptions||planOptions,budget=p.strategy==='best-value';
  const unavailable=p.unavailable||[],notSelected=Math.max(0,p.remaining-p.covered-unavailable.length);
  const success=p.covered>0||p.optimal||p.remaining===0;
  const title=!success?'No purchase plan found':`${p.covered} songs for ${money(p.cost,p.currency)}${budget&&o.budget!=null?` — within your ${money(o.budget,p.currency)} budget`:''}`;
  const ids=new Set(p.release_ids),playlistIds=new Set(project.tracks.map(t=>t.recording_id));
  const match=r=>`${r.name} ${r.artist}`.toLowerCase().includes(query.toLowerCase());
  const others=Object.values(project.releases).filter(r=>!ids.has(r.id)&&!r.owned&&r.coverage?.some(id=>playlistIds.has(id)&&project.recordings[id]?.included)).filter(match);
  target.innerHTML=`<section class="panel result"><p class="step-label">Calculated for: ${esc(strategies[o.strategy]?.[0]||o.strategy)}${budget?` · ${o.budget==null?'No budget limit':money(o.budget,p.currency)+' budget'} · ${money(o.purchase_penalty,p.currency)} purchase penalty`:''}${o.artist?' · '+esc(o.artist):''}</p><h2>${title}</h2>${!success?`<p>${esc(p.status)}</p>`:`<p>${budget&&notSelected?`${notSelected} available songs were not selected within this budget and these preferences. `:''}${unavailable.length?`${unavailable.length} songs have no usable priced match. `:''}${p.complete?'All remaining included songs are covered.':''}</p>`}<div class="actions">${unavailable.length?'<a href="#review">Check unavailable matches</a>':''}<a href="#songs">Review song choices</a></div><details><summary>Calculation details and comparison</summary><p>${esc(p.status)}</p><p>${p.release_ids.length} Store products · ${p.coverage_percent}% of remaining songs covered.</p><p>Cheapest complete plan: ${cheapestPlan?.complete?money(cheapestPlan.cost,cheapestPlan.currency):comparisonPending?'Calculating comparison…':cheapestPlan?'Unavailable for the current matches':'Comparison unavailable; calculate again to retry.'}</p><p>Based on discovered releases in your purchase country. Store prices may change and exclude checkout taxes.</p>${unavailable.length?`<p>Unavailable: ${unavailable.map(id=>esc(project.recordings[id]?.title||id)).join(', ')}.</p>`:''}</details></section><div class="section-head"><h2>${priorityStrategies.has(p.strategy)?'What to buy next':'Selected purchases'}</h2><div class="segmented" role="group" aria-label="Purchase display"><button class="secondary" data-action="purchase-view" data-id="strategy" aria-pressed="${purchaseView==='strategy'}">${priorityStrategies.has(p.strategy)?'Buying order':'Individual purchases'}</button><button class="secondary" data-action="purchase-view" data-id="grouped" aria-pressed="${purchaseView==='grouped'}">By album</button></div></div><p class="muted">Same purchases and total; ${priorityStrategies.has(p.strategy)?'Buying order shows your priority, while By album gathers songs from the same release.':'By album gathers songs from the same release; individual purchases have no priority ranking.'}</p>${purchaseCards(p,match)||'<p>No purchases match this view.</p>'}<details class="panel"><summary>Other discovered releases (${others.length})</summary>${others.map(r=>releaseCard(r)).join('')}</details>`;
  decoratePurchaseCards();renderConversionEstimate();updatePlanState();
}
function releaseLabel(r){
  if(r.purchase_type==='track'||r.recording_id)return 'Individual song';
  const kind=String(r.release_kind||r.kind||'').toLowerCase(),name=String(r.name||'');
  if(kind==='single'||/ - Single$/i.test(name))return 'Single';
  if(kind==='ep'||/ - EP$/i.test(name))return 'EP';
  if(kind.includes('album')||kind==='compilation'||kind==='soundtrack')return kind==='compilation'?'Compilation':kind==='soundtrack'?'Soundtrack':'Album';
  return 'Release';
}
function accessibleExport(){
  return heading('Export playlist','Download a playlist pointing to music files you own. Audio files stay where they are.')+`<section class="panel"><div id="export-preview" aria-live="polite"><p>Checking files…</p></div><div id="export-options" class="stack"><div class="actions export-primary"><button data-action="export" disabled>Checking ready entries…</button><button class="secondary" data-action="retry-export-preview">Check again</button></div><fieldset class="goal-options"><legend>Where will you use it?</legend><div class="choice-grid"><label class="choice"><input type="radio" name="export-preset" value="mac" checked><strong>On this Mac</strong><span>Use the files in their current locations.</span></label><label class="choice"><input type="radio" name="export-preset" value="device"><strong>On another device</strong><span>Tell us where your music will be stored.</span></label></div></fieldset><div id="device-export" hidden><label for="device-folder">Music folder on your device</label><input id="device-folder" placeholder="For example: Music or /Music"><p>Enter the folder as your player sees it. A relative folder such as Music is relative to the playlist file. You must copy the audio files to that location yourself.</p><p id="device-path-example" class="path-example" aria-live="polite"></p></div><details id="export-advanced"><summary>Advanced export settings</summary><div class="stack"><fieldset class="export-format-options"><legend>Playlist format</legend><label class="check"><input type="radio" name="export-format" value="m3u">M3U</label><label class="check"><input type="radio" name="export-format" value="m3u8" checked>M3U8</label></fieldset><label>Path style<select id="export-slashes"><option value="macos">Forward slashes / (Mac, Linux, many players)</option><option value="windows">Backslashes \\ (Windows and some players)</option></select></label><label class="check"><input type="checkbox" id="export-extinf">Include artist, title and duration (EXTINF)</label><label class="check"><input type="checkbox" id="export-custom">Change exported paths</label><label>Path replacement method<select id="export-replace-mode"><option value="prefix">Replace the source folder only</option><option value="text">Replace matching text anywhere (legacy)</option></select></label><div id="export-path-fields" class="grid" hidden><label>Source music folder<input id="export-from" value="${esc(project.library_folders?.[0]||'')}" placeholder="Folder containing your music on this Mac"></label><label>Destination folder<input id="export-to" placeholder="Music"><small>Leave empty to create paths relative to the source folder.</small></label></div>${exportFileControls()}</div></details></div><div id="export-omissions" class="spaced"></div><details class="spaced"><summary>Preview exported paths</summary><pre id="export-text"></pre></details></section><details class="panel"><summary>Export history</summary>${project.exports.slice().reverse().map(x=>`<p>${esc(x.created)} · ${x.count} entries · ${x.skipped} omitted</p>`).join('')||'<p>No exports yet.</p>'}</details>`;
}
function renderAccessibleExport(preview){
  const target=$('#export-preview');if(!target)return;
  target.innerHTML=`<h2>${preview.count} playlist entries ready</h2><p>${preview.skipped} entries omitted. Repeated songs keep their original playlist positions.</p>`;
  const button=$('[data-action="export"]');button.disabled=!preview.count;button.textContent=`Download ${preview.count} ready entries`;
  $('#export-text').textContent=preview.text;
  $('#export-omissions').innerHTML=(preview.omission_groups||[]).map(g=>`<details><summary>${esc(g.reason)} (${g.count} entries)</summary><a ${g.action==='export'?'data-action="export-settings"':''} href="#${['songs','plan','library','export'].includes(g.action)?g.action:'songs'}">${g.action==='export'?'Adjust the source folder in Advanced export settings':g.action==='plan'?'Review purchases and ownership':g.action==='library'?'Find or review local files':'Change included songs'}</a><ul class="omissions">${g.entries.map(x=>`<li><strong>${esc(x.artist)} — ${esc(x.title)}</strong><span>Playlist position ${x.position}</span><button class="small secondary" data-action="review-recording" data-id="${esc(x.recording_id)}">Review song</button></li>`).join('')}</ul>${g.count>g.entries.length?`<p>Showing ${g.entries.length} examples of ${g.count} entries in this group.</p>`:''}</details>`).join('');
  updateDeviceExample();
}
function updateDeviceExample(){
  const target=$('#device-path-example');if(!target)return;
  const source=$('#export-from').value.replaceAll('\\','/')||'/Your music folder',replacement=$('#export-to').value.replaceAll('\\','/');
  const prefix=source.replace(/\/+$/,'')+'/';
  const sample=project.local_files.find(f=>f.status==='matched'&&f.path.replaceAll('\\','/').startsWith(prefix));
  const before=sample?.path||(prefix+'Artist/Album/Song.m4a');
  const dest=replacement.replace(/\/+$/,'')||(replacement.startsWith('/')?'/':'');
  const relative=before.replaceAll('\\','/').slice(prefix.length);
  let after=$('#export-replace-mode').value==='text'?before.replaceAll('\\','/').split(source).join(replacement):(dest?dest+(dest.endsWith('/')?'':'/'):'')+relative;
  if(!$('#export-custom').checked)after=before.replaceAll('\\','/');
  if($('#export-slashes').value==='windows')after=after.replaceAll('/','\\');
  target.textContent=`Example: ${before} → ${after}`;
}
function syncDeviceDestination(){
  ++exportPreviewVersion;
  $('#export-to').value=$('#device-folder').value;
  updateDeviceExample();
  const button=$('[data-action="export"]');if(button)button.disabled=true;
  if(!$('#device-folder').value.trim())validateExportDestination();
}
function validateExportDestination(){
  const device=$('input[name="export-preset"]:checked')?.value==='device';
  if(device&&(!$('#device-folder').value.trim()||!$('#export-from').value.trim())){
    $('#export-preview').innerHTML='<div class="warning" role="status">Enter your destination music folder and check the source folder before exporting.</div>';
    if(!$('#export-from').value.trim())$('#export-advanced').open=true;
    const button=$('[data-action="export"]');if(button)button.disabled=true;
    if($('#export-text'))$('#export-text').textContent='';
    return false;
  }
  return true;
}
async function chooseNativeFolder(){
  const form=$('#scan-form'),input=$('#folder'),pid=project.id;
  const capability=await api('/api/desktop');
  if(project?.id!==pid||!form.isConnected)return;
  if(!capability.folder_picker){$('#manual-folder').open=true;input.focus();notify('This server has no desktop folder picker. Enter the folder path here, or quit the old app and open the newly packaged desktop app.');return;}
  const result=await api('/api/desktop/folder','POST',{});
  if(!result.path||project?.id!==pid||!form.isConnected)return;
  input.value=result.path;form.dataset.dirty='true';$('#selected-folder').textContent=result.path;form.querySelector('[type="submit"]').focus();
}
Object.assign(guidedActions,{
  'export-settings':()=>{$('#export-advanced').open=true;$('#export-from').focus();},
  'show-song-choices':()=>{location.hash='songs';},
  'show-versions':()=>{$('#manual-term')?.focus();},
  'choose-folder':chooseNativeFolder,
  'review-filter':async id=>{reviewFilter=id;selectedRecording=null;await render();},
  'defer-match':async id=>{deferredMatches.add(project.id+':'+id);reviewFilter='needs';selectedRecording=null;await render();},
  'resume-song':async id=>{deferredMatches.delete(project.id+':'+id);reviewFilter='needs';selectedRecording=id;await render();},
  'review-library-files':()=>{$('#library-review')?.scrollIntoView({block:'start'});$('#library-review')?.focus();}
});
