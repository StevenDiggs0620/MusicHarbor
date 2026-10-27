'use strict';
const $ = s => document.querySelector(s);
const token = $('meta[name="app-token"]').content;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const enc = encodeURIComponent;
const currency = {us:'USD',ca:'CAD',gb:'GBP'};
const country = {us:'United States',ca:'Canada',gb:'United Kingdom'};
let project = null, projects = [], settings = {}, selectedRecording = null;
let currentPlan = null, cheapestPlan = null, renderVersion = 0, selectionVersion = 0;
let candidateLimits = new Map();
function candidatePage(items, key) { return items.slice(0,candidateLimits.get(key)||100); }
function moreCandidates(items, key) { return items.length>(candidateLimits.get(key)||100)?`<button type="button" class="secondary" data-action="more-candidates" data-id="${esc(key)}">Show more matches (${items.length} total)</button>`:''; }
function captureDrafts() {
  return [...document.querySelectorAll('#main form, #export-options')].filter(el=>el.dataset.dirty==='true'||el.dataset.submitting==='true'||[...el.querySelectorAll('input[type=file]')].some(input=>input.files.length)).map(el=>({id:el.id,element:el}));
}
function restoreDrafts(drafts) { for(const draft of drafts) { const replacement=document.getElementById(draft.id); if(replacement)replacement.replaceWith(draft.element); } }
let planOptions = {strategy:'cheapest',purchase_penalty:1,budget:null,artist:''};
let query = '', reviewAll = false;
let csvDraft = null;
let csvPreviewVersion = 0;
let conversion = {currency:'',rate:''};
try { conversion = JSON.parse(localStorage.getItem('pp-conversion') || 'null') || conversion; } catch {}

function safeURL(value, provider='store') {
  try { const u = new URL(value); const hosts = provider === 'spotify' ? ['open.spotify.com'] : ['music.apple.com','itunes.apple.com']; return u.protocol === 'https:' && hosts.includes(u.hostname) ? u.href : ''; } catch { return ''; }
}
function storeLink(url, text='Open in Store') { const u=safeURL(url); return u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(text)} ↗</a>` : '<span class="muted">Store link unavailable</span>'; }
function money(n, code=currency[project?.storefront] || 'USD') { return n == null || !Number.isFinite(Number(n)) || Number(n)<0 ? 'Price unavailable' : new Intl.NumberFormat(undefined,{style:'currency',currency:/^[A-Z]{3}$/.test(code || '')?code:'USD'}).format(n); }
function duration(n) { const seconds=Math.round(Number(n)); return Number.isFinite(seconds)&&seconds>0 ? `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}` : 'Unknown duration'; }
function badge(s) { const labels={high:'Strong match',confirmed:'Confirmed',medium:'Check version',low:'Check version',unmatched:'No match yet',matched:'File matched',NEEDS_REVIEW:'Needs review',HIGH_CONFIDENCE:'Strong match',EXACT:'Exact match',UNMATCHED:'No match yet',MISSING:'File missing',ERROR:'Needs attention',LOOKUP_FAILED:'Search interrupted'};return `<span class="badge ${esc(s)}">${esc(labels[s]||s)}</span>`; }
function notify(message, error=false) { const n=$('#notice'); n.textContent=message; n.className=error?'error':''; n.hidden=!message;n.setAttribute('role',error?'alert':'status');n.setAttribute('aria-live',error?'assertive':'polite'); }
async function api(path, method='GET', body) {
  const response=await fetch(path,{method,headers:{'X-App-Token':token,...(body!==undefined?{'Content-Type':'application/json'}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json().catch(()=>({error:'The app returned an unreadable response.'}));
  if(!response.ok) throw new Error(data.error || (Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('; '):data.detail) || `Request failed (${response.status}).`);
  return data;
}
const endpoint = tail => `/api/projects/${enc(project.id)}${tail}`;
function recordings(all=false) { const ids=new Set((project?.tracks||[]).map(t=>t.recording_id)); return Object.values(project?.recordings || {}).filter(r=>all||ids.has(r.id)); }
function unresolved(r) { return r.included && !['high','confirmed'].includes(r.match_status); }
function filtered(rs) { return rs.filter(r=>`${r.title} ${r.artist} ${r.album}`.toLowerCase().includes(query.toLowerCase())); }
function optionsStore(value='us') { return Object.entries(country).map(([k,v])=>`<option value="${k}" ${value===k?'selected':''}>${v}</option>`).join(''); }
function heading(title, subtitle, eyebrow='YOUR MUSIC, MADE YOURS') { return `<p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="lede">${subtitle}</p>`; }
function empty(title, text, action='') { return `<div class="panel empty"><div class="symbol" aria-hidden="true">♫</div><h2>${title}</h2><p class="muted">${text}</p>${action}</div>`; }

function csvImportPanel() {
  return `<section class="panel hero" id="csv-import-panel"><p class="eyebrow">NO SPOTIFY PREMIUM OR API CREDENTIALS NEEDED</p><h2>Import your Exportify playlist.</h2><p class="muted">Generate a CSV at <a href="https://exportify.net" target="_blank" rel="noopener noreferrer">exportify.net ↗</a>, then choose it below. The file is processed locally; it is not uploaded to Spotify or another website.</p><form id="csv-import-form" class="stack"><div><label for="playlist-csv">Exportify CSV file</label><input id="playlist-csv" name="file" type="file" accept=".csv,text/csv" required aria-describedby="csv-file-help"><small id="csv-file-help">Up to 10 MB and 20,000 playlist entries. Preview the imported songs before creating a playlist.</small></div><div class="grid"><div><label for="csv-project-name">Playlist name</label><input id="csv-project-name" name="name" maxlength="200" placeholder="Use the file name"></div><div><label for="csv-storefront">Purchase country</label><select id="csv-storefront" name="storefront">${optionsStore(settings.storefront)}</select></div></div><div class="actions"><button type="submit" name="step" value="preview">Import a File</button><button id="csv-commit" type="submit" name="step" value="commit" hidden disabled>Create playlist from CSV</button></div><div id="csv-preview" aria-live="polite"></div></form></section>`;
}

async function csvRequest(path, bytes) {
  const response=await fetch(path,{method:'POST',headers:{'X-App-Token':token,'Content-Type':'text/csv'},body:bytes});
  const data=await response.json().catch(()=>({error:'The app returned an unreadable response.'}));
  if(!response.ok) throw new Error(data.error || (Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('; '):data.detail) || 'CSV import failed.');
  return data;
}

function showCsvPreview(result) {
  const problems=(items,label)=>items.length?`<div class="warning spaced"><strong>${esc(label)}</strong><ul>${items.map(x=>`<li>Line ${x.line}: ${esc(x.message)}</li>`).join('')}</ul></div>`:'';
  $('#csv-preview').innerHTML=`<div class="result"><h3>${result.rows_read} CSV rows found · ${result.count} valid entries · ${result.recording_count} unique songs</h3><p>${result.repeated_entries} repeated entries retained in their original positions. ${result.blank_rows} blank rows ignored.</p><p>${result.missing_duration} entries have unknown duration; ${result.missing_explicit} have unknown explicit status.</p>${result.error_count?`<p><strong>${result.error_count} row errors must be fixed before importing. No playlist has been created.</strong></p>`:'<p>Check the preview, then select Create playlist from CSV.</p>'}</div>${problems(result.errors,'Rows to fix (up to 50 shown)')}${problems(result.warnings,'Import notes (up to 50 shown)')}<details><summary>Recognized columns</summary><ul>${Object.entries(result.columns).map(([field,header])=>`<li>${esc(header)} → ${esc(field.replaceAll('_',' '))}</li>`).join('')}</ul></details><div class="table-wrap"><table><caption>First ${result.rows.length} valid entries of ${result.count}; the import includes every valid row when no errors remain.</caption><thead><tr><th>#</th><th>Song</th><th>Album</th><th>Duration</th><th>Explicit</th></tr></thead><tbody>${result.rows.map(r=>`<tr><td>${r.position}</td><td><strong>${esc(r.title)}</strong><small>${esc(r.artist)}</small></td><td>${esc(r.album)}</td><td>${duration(r.duration)}</td><td>${r.explicit===true?'Yes':r.explicit===false?'No':'Unknown'}</td></tr>`).join('')}</tbody></table></div>`;
  $('#csv-commit').hidden=!result.can_import;
  $('#csv-commit').disabled=!result.can_import;
}

async function loadProjects() {
  projects=await api('/api/projects');
  $('#project-picker').innerHTML='<option value="">Choose a playlist</option>'+projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  if(project) $('#project-picker').value=project.id;
}
async function selectProject(id) {
  const selection=++selectionVersion; ++renderVersion;
  $('#main').inert=true;
  let loaded;
  try { loaded=id?await api(`/api/projects/${enc(id)}`):null; }
  finally { if(selection===selectionVersion)$('#main').inert=false; }
  if(selection!==selectionVersion)return;
  project=loaded;
  libraryPage={files:[],recordings:{},total:0,next_offset:null};
  selectedRecording=null; currentPlan=null; cheapestPlan=null;calculatedOptions=null;reviewFilter='needs';planPending=false;comparisonPending=false;++calculationGeneration; query='';
  if(id) localStorage.setItem('pp-project',id); else localStorage.removeItem('pp-project');
  $('#project-picker').value=id || '';
  await render();
  if(selection!==selectionVersion)return;
  if(project) {await refreshJobs();watchJob();} else {jobPollGeneration++;jobPollProject=null;renderJobs([]);}
}
async function reload({preserveDrafts=false}={}) {
  const selection=selectionVersion, pid=project?.id, version=renderVersion;
  const loaded=pid?await api(`/api/projects/${enc(pid)}`):null;
  if(selection!==selectionVersion || project?.id!==pid)return;
  await loadProjects();
  if(selection!==selectionVersion || project?.id!==pid || version!==renderVersion)return;
  const drafts=preserveDrafts?captureDrafts():[];
  project=loaded; currentPlan=null; cheapestPlan=null;calculatedOptions=null;
  await render(drafts);
}
function songTable(rs, owned=false) {
  if(!rs.length) return '<p class="muted">No songs in this view.</p>';
  return `<div class="table-wrap"><table><thead><tr><th>Recording</th><th>Match</th><th>Included</th><th>Ownership</th><th></th></tr></thead><tbody>${rs.map(r=>`<tr><td><strong>${esc(r.title)}</strong><small>${esc(r.artist)} · ${duration(r.duration)}</small><small>${esc(r.album)}${r.required?' · Required':''}</small></td><td>${badge(r.match_status)}</td><td><button class="small secondary" data-action="include" data-id="${esc(r.id)}">${r.included?'Included':'Skipped'}</button></td><td><button class="small ${r.effective_owned?'secondary':''}" data-action="own-recording" data-id="${esc(r.id)}">${r.effective_owned?'Owned · undo':'Mark owned'}</button>${r.ownership_override!=null?`<button class="small secondary" data-action="reset-ownership" data-id="${esc(r.id)}">Use release ownership</button>`:''}</td><td><button class="small secondary" data-action="review-recording" data-id="${esc(r.id)}">Review</button></td></tr>`).join('')}</tbody></table></div>`;
}
function releaseCard(r, rank, ownedView=false, playsLabel='') {
  const playlistIds=new Set(project.tracks.map(t=>t.recording_id));
  const covers=(r.coverage||[]).filter(id=>playlistIds.has(id)&&project.recordings[id]?.included && !project.recordings[id].effective_owned);
  const wanted=(r.coverage||[]).filter(id=>playlistIds.has(id)&&project.recordings[id]?.included);
  const art=(()=>{try{const u=new URL(r.artwork);return u.protocol==='https:'&&u.hostname.endsWith('.mzstatic.com')?`<img class="art" src="${esc(u.href)}" alt="" loading="lazy">`:'';}catch{return '';}})();
  return `<article class="release-card ${r.owned?'owned':''} ${r.excluded?'excluded':''}">${rank?`<span class="rank">${rank}</span>`:''}${art || '<span class="art" aria-hidden="true">♫</span>'}<div class="release-info"><div class="section-head"><div><h3>${esc(r.name)}</h3>${r.purchase_type==='track'?`<small>Individual song from ${esc(r.release_name || 'Unknown release')}</small>`:''}<small class="release-artist">${esc(r.artist)} · ${esc(r.date || 'Date unknown')}</small></div><span class="price">${money(r.price,r.currency)}${ownedView?`<small>${r.recording_id?'Estimated playlist-song value':'Whole release Store price'}</small>`:''}</span></div>${playsLabel}${badge(releaseLabel(r))} ${r.owned?badge('owned'):''} ${r.partial?.length?badge('partially owned'):''}<p class="muted">${ownedView?`${r.coverage.length} owned playlist song${r.coverage.length===1?'':'s'}`:`${covers.length} remaining wanted song${covers.length===1?'':'s'} · ${wanted.length} included in total`}</p><div class="actions">${storeLink(r.url)}${ownedView?(r.recording_id?`<button class="small secondary" data-action="own-recording" data-id="${esc(r.recording_id)}">Undo owned</button><button class="small secondary" data-action="review-recording" data-id="${esc(r.recording_id)}">Review</button>`:`<button class="small secondary" data-action="own-release" data-id="${esc('album:'+r.release_id)}">Undo release ownership</button><button class="small secondary" data-action="partial" data-id="${esc('album:'+r.release_id)}">Choose owned songs</button>`):`<button class="small" data-action="own-release" data-id="${esc(r.id)}">${r.owned?'Undo owned':'Mark owned'}</button><button class="small secondary" data-action="partial" data-id="${esc(r.id)}">Partial ownership</button><button class="small secondary" data-action="exclude-release" data-id="${esc(r.id)}">${r.excluded?'Include release':'Exclude'}</button>`}</div><details><summary>Songs covered and price history</summary><ul>${(r.coverage||[]).map(id=>`<li>${esc(project.recordings[id]?.title || id)}${project.recordings[id]?.effective_owned?' · owned':''}</li>`).join('') || '<li>No confirmed wanted recordings.</li>'}</ul><p>Checked: ${esc(r.checked || 'Not checked')}${r.incomplete_tracklist?' · Store track list is incomplete.':r.tracklist_refresh_incomplete?' · Refresh was incomplete; the previous complete track list was retained.':''}</p>${(project.price_history||[]).filter(x=>x.release_id===r.id).slice(-8).reverse().map(x=>`<small>${esc(x.checked)} · ${money(x.price,x.currency)}</small><br>`).join('')}</details></div></article>`;
}
function purchaseGroupCard(group, items, ownedView=false) {
  if(!items.length)return '';
  const playsLabel=group.play_count!=null?`<small class="plays-count">${group.play_count.toLocaleString()} plays in the last ${settings.listening?.days||90} days</small>`:'';
  if(group.type!=='tracks' || items.length<2) {
    return `<section class="purchase-group">${items.map(r=>releaseCard(r,undefined,ownedView,playsLabel)).join('')}</section>`;
  }
  const first=items[0], code=first.currency || currency[project.storefront];
  const priced=items.every(r=>r.currency===code && r.price!=null && Number.isFinite(Number(r.price)) && Number(r.price)>=0);
  const total=priced?items.reduce((sum,r)=>sum+Math.round(Number(r.price)*100),0)/100:null;
  const artwork=items.find(r=>r.artwork)?.artwork;
  const collectionId=first.release_id || (first.songs || [])[0]?.collectionId;
  const album=collectionId?project.releases['album:'+collectionId]:null;
  const playlistIds=new Set(project.tracks.map(t=>t.recording_id));
  const wanted=album?(album.coverage || []).filter(id=>playlistIds.has(id)&&project.recordings[id]?.included):[];
  const remaining=wanted.filter(id=>!project.recordings[id].effective_owned);
  const albumControls=album?`<div class="album-group-controls"><p class="muted">${remaining.length} remaining wanted recording${remaining.length===1?'':'s'} · ${wanted.length} included in total</p><small class="album-controls-label">Whole release controls</small><div class="actions">${storeLink(album.url)}<button class="small" data-action="own-release" data-id="${esc(album.id)}">${album.owned?'Undo owned':'Mark owned'}</button><button class="small secondary" data-action="partial" data-id="${esc(album.id)}">Partial ownership</button><button class="small secondary" data-action="exclude-release" data-id="${esc(album.id)}">${album.excluded?'Include release':'Exclude'}</button></div><details><summary>Covered recordings and price history</summary><ul>${(album.coverage || []).filter(id=>playlistIds.has(id)).map(id=>`<li>${esc(project.recordings[id]?.title || id)}${project.recordings[id]?.effective_owned?' · owned':''}</li>`).join('') || '<li>No confirmed playlist recordings.</li>'}</ul><p>Whole release price: ${money(album.price,album.currency)}<br>Checked: ${esc(album.checked || 'Not checked')}${album.incomplete_tracklist?' · Store track list is incomplete.':album.tracklist_refresh_incomplete?' · Refresh was incomplete; the previous complete track list was retained.':''}</p>${(project.price_history || []).filter(x=>x.release_id===album.id).slice(-8).reverse().map(x=>`<small>${esc(x.checked)} · ${money(x.price,x.currency)}</small><br>`).join('')}</details></div>`:'';
  let art='';
  try { const url=new URL(artwork); if(url.protocol==='https:'&&url.hostname.endsWith('.mzstatic.com'))art=`<img class="art" src="${esc(url.href)}" alt="" loading="lazy">`; } catch {}
  return `<section class="purchase-group album-group ${ownedView?'owned':''}"><details class="album-song-disclosure"><summary>${art||'<span class="art" aria-hidden="true">♫</span>'}<span class="album-group-info"><strong>${esc(first.release_name || group.label)}</strong><small>${esc(first.artist)} · ${items.length} ${ownedView?'owned songs':'songs to buy'}</small>${playsLabel}<small class="album-expand-hint">Show songs and individual prices</small></span><span class="price">${money(total,code)}<small>${ownedView?'Estimated song value':'Individual songs total'}</small></span></summary><div class="album-group-tracks">${items.map(r=>releaseCard(r,undefined,ownedView)).join('')}</div></details>${albumControls}</section>`;
}

function playlistUpdatePanel() {
  return `<section class="panel"><h2>Update this playlist</h2><p>Keep existing recording matches, release discoveries, ownership and review decisions. Only new or unfinished items need catalog searches.</p><form id="playlist-update-form" class="stack"><div class="grid"><div><label for="update-source">Import from</label><select id="update-source" name="source"><option value="csv">Exportify CSV</option><option value="spotify">Spotify playlist link</option></select></div><div><label for="update-mode">How to update</label><select id="update-mode" name="mode"><option value="add">Add to playlist</option><option value="replace">Replace playlist</option></select></div></div><p class="muted">Add keeps existing entries and adds missing songs or extra duplicate appearances. Replace uses only the incoming playlist entries, in their original order. Removed songs retain their catalog data for future updates.</p><div id="update-csv-field"><label for="update-csv">New Exportify CSV</label><input id="update-csv" name="file" type="file" accept=".csv,text/csv" required></div><div id="update-spotify-field" hidden><label for="update-url">New Spotify playlist link</label><input id="update-url" name="url" type="text" maxlength="2000" placeholder="https://open.spotify.com/playlist/…" value="${esc(project.source_url||'')}"><small>Requires Spotify access configured in Settings.</small></div><button type="submit">Update this playlist</button><div id="playlist-update-feedback" aria-live="polite"></div></form></section>`;
}

function renderPlanResult(){renderAccessiblePlanResult();}
function ownedScreen(){return heading('My music','Your owned songs and the files available for this playlist.')+'<div class="actions"><a class="button secondary" href="#library">Choose folder / scan music</a><a class="button secondary" href="#library">Review local-file matches</a><a class="button secondary" href="#export">Export owned songs</a></div><div id="owned-result" class="spaced"><p>Loading your collection…</p></div><details class="panel"><summary>Listening history and ranking</summary>'+listeningSummary()+'</details>';}
function renderOwnedCollection(data) {
  const target=$('#owned-result');if(!target)return;
  target.innerHTML=`<div class="stats"><div class="stat"><strong>${data.count}</strong><span>Owned playlist songs</span></div><div class="stat"><strong>${data.percent}%</strong><span>Playlist already owned</span></div><div class="stat"><strong>${money(data.value,data.currency)}</strong><span>Estimated playlist collection value</span></div></div><div class="result"><h2>Your owned collection</h2><p>${data.count} of ${data.total} unique playlist songs owned. Duplicate appearances count once. Value uses saved individual Store track prices, including only owned songs in this playlist—not full album prices or your purchase history.</p>${data.unpriced?`<p>${data.unpriced} owned song${data.unpriced===1?' has':'s have'} no known price; the value shown is a partial estimate.</p>`:''}</div><h2 class="spaced">Owned music</h2>${data.groups.map(group=>purchaseGroupCard(group,group.release_ids.map(id=>data.releases[id]),true)).join('')||'<p class="muted">No songs in this playlist are marked owned yet.</p>'}`;
}
function libraryScreen() {
  const files=libraryPage.files || [];
  const resolved=files.filter(f=>f.status==='matched');
  return heading('Local music files','Scan music you already own and review uncertain file matches. This shared library is separate from playlist match review.')+
    `<section class="panel"><form id="scan-form" class="stack"><label for="folder">Music folder path</label><input id="folder" name="folder" required placeholder="Music folder path" value="${esc(project.library_folders?.[0] || '')}"><button type="submit">Scan and identify music</button><small>MP3, M4A, FLAC, WAV, AAC and OGG. Audio and file paths stay local. Title and artist are used for catalog searches.</small></form></section>
    <div class="stats"><div class="stat"><strong>${files.length}</strong><span>Files on this page</span></div><div class="stat"><strong>${resolved.length}</strong><span>Identified on this page</span></div><div class="stat"><strong>${files.filter(f=>f.status==='review').length}</strong><span>Need review on this page</span></div><div class="stat"><strong>${files.filter(f=>!['review','matched'].includes(f.status)).length}</strong><span>Other files on this page</span></div></div>
    <section class="panel" id="library-review" tabindex="-1"><h2>Local-file matches</h2><p>${libraryPage.unresolved_total??files.filter(f=>f.status!=='matched').length} local files need attention across your library. Playlist matches are reviewed separately.</p>${libraryNavigation()}<p>Review uncertain identities below. Open identified files to inspect or override a decision.</p>${files.filter(f=>f.status!=='matched').map(localFileCard).join('') || '<p>No uncertain files.</p>'}<details><summary>${resolved.length} identified files</summary>${resolved.map(localFileCard).join('')}</details></section>`;
}
function localFileCard(f) {
  const rid=f.identity_id || f.recording_id;
  return `<article class="file-row"><div class="section-head"><strong>${esc(f.title || f.path.split(/[\\/]/).pop())}</strong>${badge(f.resolution_state || f.status)}</div><small>${esc(f.artist || 'Artist missing')} · ${esc(f.album || 'Album missing')} · ${duration(f.duration)}</small><code>${esc(f.path)}</code><p>${esc(f.error || (f.match_evidence?.reasons||[]).join(' · '))}</p>${rid?`<button class="small secondary" data-action="review-local" data-id="${esc(f.id)}">Review recording identity</button>`:'<p>Metadata could not be read. Repair the tags and rescan.</p>'}</article>`;
}
function reviewLocal(id) {
  const f=libraryPage.files.find(x=>x.id===id)||project.local_files.find(x=>x.id===id);
  if(!f)throw new Error('This file is no longer on the current library page. Reload the library.');
  const r=libraryPage.recordings[f.identity_id||f.recording_id]||project.recordings[f.identity_id||f.recording_id];
  const candidates=(f.candidates?.some(c=>c.song)?f.candidates:r?.candidates)||[];
  modal(`<h2>Identify this local file</h2><p>${esc(f.artist)} — ${esc(f.title)}<br><small>${esc(f.album)} · ${duration(f.duration)} · ${f.explicit===true?'Explicit':f.explicit===false?'Clean / non-explicit':'Explicitness unknown'}</small></p><code>${esc(f.path)}</code><p>Current identity: ${esc(r?.selected?.trackName || r?.title || 'Unidentified')} · ${esc(r?.selected?.collectionName || r?.album || '')}</p><form id="local-search-form" data-id="${esc(id)}" class="stack spaced"><label>Search recording title and artist<input name="term" value="${esc(f.artist+' '+f.title)}" required maxlength="300"></label><button>Search recordings</button></form>${candidatePage(candidates.filter(c=>c.song),'file:'+id).map(c=>`<article class="candidate"><strong>${esc(c.song.artistName)} — ${esc(c.song.trackName)}</strong><small>${esc(c.song.collectionName)} · ${duration(c.song.trackTimeMillis/1000)} · ${esc(c.song.trackExplicitness)}</small>${candidateDetails(c)}<button data-action="confirm-local" data-id="${esc(id)}" data-track="${esc(c.song.trackId)}">Confirm this recording</button></article>`).join('') || '<p>Search to find recording candidates. This file does not need to belong to a playlist.</p>'}${moreCandidates(candidates.filter(c=>c.song),'file:'+id)}`);
}
function projectsScreen() {
  return heading('Every playlist has a place.','Switch between saved projects, keep a backup, or start a new collection.')+
    `<section class="panel"><h2>Create a playlist</h2><form id="new-project" class="form-grid"><div><label for="new-name">Playlist name</label><input id="new-name" name="name" required maxlength="200" placeholder="My next purchases"></div><div><label for="new-store">Purchase country</label><select id="new-store" name="storefront">${optionsStore(settings.storefront)}</select></div><button type="submit">Create playlist</button></form></section><section class="panel"><h2>Saved playlists</h2>${projects.map(p=>`<div class="section-head"><div><strong>${esc(p.name)}</strong><small> · ${esc(p.updated.slice(0,10))}</small></div><div class="actions"><button class="small" data-action="open-project" data-id="${esc(p.id)}">Open</button><button class="small secondary" data-action="rename-project" data-id="${esc(p.id)}">Rename</button><button class="small secondary" data-action="duplicate-project" data-id="${esc(p.id)}">Duplicate</button><a class="button small secondary" href="/api/projects/${enc(p.id)}/backup" download>Playlist-only backup</a><a class="button small secondary" href="/api/projects/${enc(p.id)}/backup?scope=library" download>Full-library backup</a><button class="small danger" data-action="delete-project" data-id="${esc(p.id)}">Delete</button></div></div>`).join('') || '<p class="muted">No saved playlists.</p>'}</section><section class="panel"><h2>Restore a playlist</h2><p class="muted">Playlist-only backups contain this playlist’s relevant catalog and decisions, without local file paths. Full-library backups contain all playlists and shared file metadata, including private paths. Credentials and audio files are never included. Restores add new playlists and preserve existing library decisions; rescan restored files.</p><form id="restore-form" class="stack"><label for="backup-file">MusicHarbor backup file</label><input id="backup-file" name="file" type="file" accept="application/json,.json" required><button type="submit">Restore as a new playlist</button></form></section>`;
}
function listeningSummary() {
  return `<section class="panel listening-panel"><h2>Listening history</h2><div data-listening-status></div><div class="actions"><a href="#settings">Connection settings</a><button class="secondary" data-action="sync-listening">Sync last ${settings.listening?.days||90} days</button></div></section>`;
}
function listeningSettings() {
  const l=settings.listening||{};
  return `<section class="panel"><h2>Sort by your listening history</h2><p>Albums with equal playlist-song counts are ordered by your plays in the last ${settings.listening?.days||90} days. Releases with plays come first. Zero-play releases follow, sorted by price, artist and release title A–Z, ignoring playlist-song count. Other ties also use price, artist and title. Without synced history, playlist-song count stays first. Choose one source to avoid counting the same listen twice.</p><form id="listening-form" class="stack"><div class="grid"><label>Listening service<select name="provider" id="listening-provider"><option value="listenbrainz" ${l.provider!=='lastfm'?'selected':''}>ListenBrainz — easiest setup</option><option value="lastfm" ${l.provider==='lastfm'?'selected':''}>Last.fm</option></select></label><label>Your username<input name="username" required maxlength="100" value="${esc(l.username||'')}" autocomplete="username" placeholder="Username, not a profile URL"></label></div><label>Look back (days)<input name="days" type="number" min="1" max="3650" step="1" required value="${l.days||90}"></label><small>Default: 90 days. Choose 1–3,650 days. Longer periods take longer to sync. Saving automatically syncs the selected period.</small><div id="listenbrainz-setup" ${l.provider==='lastfm'?'hidden':''}><p>Public listening history only needs your ListenBrainz username. No password needed.</p><a href="https://listenbrainz.org/login/" target="_blank" rel="noopener noreferrer">Open ListenBrainz to sign in or find your username ↗</a><details class="spaced"><summary>Optional access token</summary><label>ListenBrainz token<input name="token" type="password" autocomplete="new-password" placeholder="${l.token_set?'Saved — leave blank to keep':'Only if your history requires it'}"></label><a href="https://listenbrainz.org/settings/" target="_blank" rel="noopener noreferrer">Find your token in ListenBrainz settings ↗</a></details></div><div id="lastfm-setup" ${l.provider!=='lastfm'?'hidden':''}><p>Last.fm allows read-only history access without signing in here, but requires an application API key. You never need to provide your Last.fm password or API secret.</p><a href="https://www.last.fm/api/account/create" target="_blank" rel="noopener noreferrer">Sign in to Last.fm and get an API key ↗</a><label class="spaced">Last.fm API key<input name="api_key" type="password" autocomplete="new-password" placeholder="${l.key_set?'Saved — leave blank to keep':'Paste the API key here'}"></label></div><small>Your history stays in the local app database and is used only for ranking. Sync updates rankings and listening-aware budget plans. Recording matches and ownership stay unchanged.</small><div class="actions"><button type="submit">Save &amp; sync</button><button type="button" class="secondary" data-action="disconnect-listening">Disconnect and clear history</button></div></form><div data-listening-status class="spaced" aria-live="polite"></div></section>`;
}
function renderListeningStatus() {
  const l=settings.listening||{}, date=l.synced_at?new Date(l.synced_at*1000).toLocaleString():'';
  const description=!l.connected?'Not connected. Album ties use price, then artist A–Z.':`${l.provider==='lastfm'?'Last.fm':'ListenBrainz'} · ${esc(l.username)}${date?` · Last synced ${esc(date)}`:' · Not synced yet'}`;
  document.querySelectorAll('[data-listening-status]').forEach(el=>el.innerHTML=`<p>${description}</p>${l.needs_sync?'<small>Sync the selected period to enable play-count ranking. Price, then artist and release title A–Z break track-count ties until enough history is available.</small>':date?`<small>Counts use the last ${l.days||90} days, with plays available through your last sync. Sync again to include newer plays. Uncertain recording matches are not counted.</small>`:''}`);
  document.querySelectorAll('[data-action="sync-listening"]').forEach(b=>b.disabled=!l.connected||l.running);
}
let listeningPolling=false;
async function reloadAfterJob() {
  const selection=selectionVersion;let failures=0;
  while(selection===selectionVersion) {
    try { return await reload({preserveDrafts:true}); }
    catch(e) { failures++;notify('Results could not refresh; reconnecting automatically. '+e.message,true);await new Promise(resolve=>setTimeout(resolve,Math.min(30000,1500*2**Math.min(failures,5)))); }
  }
}
async function watchListening() {
  if(listeningPolling||!settings.listening?.running)return;
  listeningPolling=true;let failures=0;
  try {
    while(settings.listening?.running){
      await new Promise(resolve=>setTimeout(resolve,Math.min(30000,1500*2**Math.min(failures,5))));
      try {
        settings.listening=await api('/api/listening');renderListeningStatus();await refreshJobs();
        if(failures)notify('Connection restored.'); failures=0;
      } catch(e){failures++;notify('Progress connection interrupted; reconnecting automatically. '+e.message,true);}
    }
    await reloadAfterJob();
  } catch(e){notify(e.message,true);} finally {listeningPolling=false;}
}
function settingsScreen() {
  const prefs=settings.preferences || {};
  return heading('Make it work for you.','Your credentials and preferences are stored locally, outside the application’s source folder.')+listeningSettings()+
    `<form id="settings-form" class="stack"><section class="panel"><div class="section-head"><h2>Spotify connection</h2>${badge(settings.connected?'connected':'not connected')}</div><p class="muted">Create a Spotify developer app, add the redirect address below, and save its Client ID. Connect Spotify for private playlists and current development-mode access.</p><label>Redirect address to register with Spotify</label><pre>${esc(settings.redirect_uri)}</pre><div class="stack"><div><label for="client-id">Spotify Client ID</label><input id="client-id" name="spotify_id" value="${esc(settings.spotify_id)}" autocomplete="off"></div><div><label for="client-secret">Client Secret (optional for OAuth)</label><input id="client-secret" name="spotify_secret" type="password" placeholder="${settings.spotify_secret_set?'Saved — leave blank to keep':'Only needed for Client Credentials flow'}" autocomplete="new-password"></div><label class="check"><input name="clear_secret" type="checkbox"> Remove saved Client Secret</label></div><div class="actions spaced"><button type="submit">Save settings</button><button type="button" class="secondary" data-action="connect">Connect Spotify</button><button type="button" class="secondary" data-action="disconnect">Disconnect</button></div><p class="warning spaced">Spotify development-mode access requires an eligible account and limits playlist contents to playlists you own or collaborate on. Public visibility alone does not guarantee API access.</p></section><section class="panel"><h2>Performance</h2><div class="grid"><label>API requests in flight<input name="api_concurrency" type="number" min="1" max="6" value="${settings.performance?.api_concurrency??3}" required></label><label>Background jobs at once<input name="background_jobs" type="number" min="1" max="4" value="${settings.performance?.background_jobs??2}" required></label></div><p class="muted">Defaults: 3 requests and 2 jobs. Projects run independently; changes to the same project stay sequential. Apple requests share a roughly 20-per-minute limit, including retries. Cached results and batches reduce calls; increasing concurrency does not remove the service limit.</p><button type="submit">Save performance settings</button></section><section class="panel"><h2>Matching preferences</h2><p class="muted">Live, acoustic, remix, instrumental, and other materially different versions always require review. Explicitly confirmed choices stay confirmed when preferences change.</p><div class="stack"><label class="check"><input name="clean_explicit_equivalent" type="checkbox" ${prefs.clean_explicit_equivalent?'checked':''}> Treat clean and explicit versions as equivalent</label><label class="check"><input name="remasters_equivalent" type="checkbox" ${prefs.remasters_equivalent?'checked':''}> Treat remasters as the same recording</label><div><label for="default-store">Default storefront for new playlists</label><select id="default-store" name="storefront">${optionsStore(settings.storefront)}</select></div><button type="submit">Save preferences</button></div></section></form>`;
}
function helpScreen() {
  return heading('A little help along the way.','How matching, buying, and exporting fit together.')+
    `<section class="panel prose"><h2>Your first playlist</h2><ol><li>Open Settings, save your Spotify Client ID, and connect your account.</li><li>Import a playlist using the storefront where you will purchase music.</li><li>Choose Find Store matches. Search runs in the background with a progress message.</li><li>Review uncertain recordings. Confirm the correct version, then load its release or run discovery again.</li><li>Compare the cheapest complete plan with your preferred buying queue.</li><li>Use Store links to purchase. Mark releases or recordings owned, then recalculate.</li><li>Scan your local music, review uncertain file identities, and export an M3U8 playlist.</li></ol><h2>Recording versus release</h2><p>One wanted recording can appear on a single, an album, and a deluxe edition. Those are separate purchase options covering the same recording. Individual Store songs also count as purchase options; a purchase count measures selected products, not checkout transactions.</p><h2>What “cheapest” means</h2><p>The optimizer finds the least expensive combination among discovered, confirmed options with valid prices in your storefront. The result says whether optimality was proven. It cannot claim to have found every edition in the Store. Missing matches and unavailable prices stay visible.</p><p>Most songs first picks the largest remaining coverage, then lower price, then newer date. Songs per dollar ranks useful coverage divided by price. Artist focus prioritizes the selected artist’s remaining recordings. These queues can cost more than the cheapest complete plan.</p><h2>Ownership and versions</h2><p>Owning a release normally owns its covered wanted recordings. Partial ownership lets you select which recordings you have. Marking a recording unowned overrides album ownership, useful when you own another version. Use “Use release ownership” to clear that override.</p><h2>Privacy and service limits</h2><p>Spotify receives playlist and authorization requests. Apple receives title and artist searches for the selected storefront. Music files and local paths are not sent to either service. Credentials are stored in a local file with restricted permissions where supported; they are not encrypted. The app uses no audio downloads or stream ripping.</p><p>Store queries are cached for a day and paced to reduce rate limits. Refresh prices bypasses the cache. Backups contain project metadata and may include local paths, but never Spotify credentials.</p><h2>Keyboard controls</h2><table><tbody>${[['Enter','Submit the focused form'],['Escape','Close a dialog'],['/','Focus the current search field'],['N / P','Next / previous recording in Match Review'],['M / R','Confirm / reject the first displayed candidate'],['O','Toggle ownership of the selected review recording'],['E','Open Export'],['?','Open Help'],['Tab / Shift+Tab','Move through controls']].map(([k,v])=>`<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`).join('')}</tbody></table><h2>Troubleshooting</h2><ul><li>Authorization error: check the exact redirect address and allowed Spotify users, then reconnect.</li><li>No Store match: try a shorter manual search and check alternate releases. iTunes does not generally expose ISRC, so matching uses it only when both sources supply it.</li><li>Incomplete plan: review unmatched songs, enable appropriate versions, or refresh missing prices.</li><li>Missing local files: scan the folder containing your current copies. AAC and WAV files may have little usable metadata; manual file selection is available.</li><li>App already running: open <a href="http://127.0.0.1:8765">the local app</a>. Only one instance should use the database.</li></ul><h2>API documentation</h2><p><a href="https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide" target="_blank" rel="noopener noreferrer">Spotify access changes</a> · <a href="https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html" target="_blank" rel="noopener noreferrer">iTunes Search API</a></p></section>`;
}
async function calculatePlan(version=renderVersion) {
  const pid=project.id,options={...planOptions},generation=++calculationGeneration;
  planPending=true;comparisonPending=false;updatePlanState();
  try{
    const chosen=await requestPlan(pid,options,version);
    if(version!==renderVersion||project?.id!==pid||generation!==calculationGeneration)return;
    currentPlan=chosen;calculatedOptions=options;purchaseView=priorityStrategies.has(options.strategy)?'strategy':'grouped';
    cheapestPlan=options.strategy==='cheapest'?chosen:null;planPending=false;comparisonPending=options.strategy!=='cheapest';renderPlanResult();
    if(comparisonPending){
      try{
        const comparison=await requestPlan(pid,{strategy:'cheapest'},version);
        if(version===renderVersion&&project?.id===pid&&generation===calculationGeneration)cheapestPlan=comparison;
      }catch(error){if(version===renderVersion&&project?.id===pid)notify('Your chosen plan is ready. Comparison unavailable: '+error.message,true);}
    }
  }finally{
    if(generation===calculationGeneration){planPending=false;comparisonPending=false;if(version===renderVersion&&project?.id===pid){renderPlanResult();updatePlanState();}}
  }
}
function renderConversionEstimate() {
  const chosen=currentPlan;
  if(chosen && $('#plan-result') && conversion.currency && Number.isFinite(Number(conversion.rate)) && Number(conversion.rate)>0) {
    const estimate=document.createElement('p');estimate.className='conversion';
    estimate.textContent=`Display estimate: ${money(chosen.cost*Number(conversion.rate),conversion.currency)} at your supplied rate of ${conversion.rate} ${conversion.currency} per ${chosen.currency}. Purchases and optimization remain in ${chosen.currency}; this is not a live exchange rate.`;
    $('#plan-result').prepend(estimate);
  }
}
async function render(drafts=[]) {
  const version=++renderVersion, pid=project?.id;
  const savedCsvDraft=csvDraft;
  const page=(location.hash.slice(1)||'overview');
  const main=$('#main'),sameScreen=main.dataset.page===page&&main.dataset.project===(pid||'');
  const disclosures=new Map(sameScreen?[...main.querySelectorAll('details')].map(d=>[d.id||d.querySelector('summary')?.textContent,d.open]):[]);
  main.dataset.page=page;main.dataset.project=pid||'';
  document.querySelectorAll('nav a').forEach(a=>{const active=a.hash==='#'+({library:'owned',import:'overview',update:'songs'}[page]||page);a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('#breadcrumb').textContent=project?.name || 'Your workspace';
  $('#store-label').textContent=project?`${country[project.storefront]} · ${currency[project.storefront]}`:'LOCAL ONLY';
  $('#review-count').textContent=playlistNeedsReview().length;
  $('#review-count').hidden=playlistNeedsReview().length===0;
  if(!project && ['songs','update','review','plan','owned','library','export'].includes(page)) { $('#main').innerHTML=heading('Choose a playlist first.','Import a playlist or open an existing playlist to continue.')+empty('No playlist selected','Your saved playlists are available from the sidebar.','<a class="button" href="#import">Import a playlist</a>'); return; }
  const screens={overview:accessibleOverview,songs:accessibleSongs,update:accessibleUpdate,import:guidedImport,review:accessibleReview,plan:accessiblePlan,owned:ownedScreen,library:libraryScreen,export:accessibleExport,projects:projectsScreen,settings:settingsScreen,help:helpScreen};
  $('#main').innerHTML=(screens[page]||accessibleOverview)();
  if(page==='help') {
    const guide=$('#main .panel');
    if(guide) {
      const oldTitle=guide.querySelector('h2');if(oldTitle)oldTitle.textContent='Optional: using direct Spotify import';
      guide.insertAdjacentHTML('beforebegin',`<section class="panel prose"><h2>Import your Exportify CSV for free</h2><ol><li>Get your playlist CSV from <a href="https://exportify.net" target="_blank" rel="noopener noreferrer">exportify.net</a>. An existing CSV works too.</li><li>Choose Add playlist, choose the file, set the playlist name and purchase country, and click <strong>Preview playlist</strong>.</li><li>Check the preview. Fix any reported errors in the source CSV, then choose the corrected file.</li><li>Click <strong>Create playlist from CSV</strong>, automatic matching starts next.</li><li>Review uncertain matches, calculate purchases, and track ownership as usual.</li></ol><p>No Spotify Premium, developer app, or credentials are needed for CSV import. The file is processed by this local application. Store searches require internet access.</p><h2>What the CSV provides</h2><p>Track Name and Artist Name(s) are required. Album, Spotify URI, duration in milliseconds, explicit status, release date, and ISRC are used when supplied. Semicolon-separated artists are preserved as separate credits. Extra columns such as genres, popularity, and audio features are ignored.</p><p>Missing duration or explicitness stays unknown and can require manual match review. Repeated playlist entries remain in order. Prices and release coverage come from the Store search, not the CSV.</p><p>Each CSV import creates a new playlist; local-library ownership is reused across playlists. Manual playlist ownership remains specific to that playlist. Limits: 10 MB and 20,000 entries. UTF-8 Exportify files, quoted commas, and multiple artists are supported.</p></section>`);
    }
  }
  if(page==='settings') {
    $('#settings-form').insertAdjacentHTML('beforeend',retentionControls());
    const lead=$('#main > .lede');if(lead)lead.textContent='Spotify credentials are optional. Import an Exportify CSV without an account connection, or configure direct Spotify access here.';
  }
  if(page==='import') {
    if(!drafts.some(d=>d.id==='csv-import-form')){csvDraft=null;csvPreviewVersion++;}
  }

  restoreDrafts(drafts);
  if(drafts.some(d=>d.id==='csv-import-form'))csvDraft=savedCsvDraft;
  decorateGuidedScreen(page);
  main.querySelectorAll('details').forEach(d=>{const key=d.id||d.querySelector('summary')?.textContent;if(disclosures.has(key))d.open=disclosures.get(key);});
  renderListeningStatus();watchListening();await refreshJobs();
  if(version!==renderVersion || project?.id!==pid)return;
  if(page==='owned') {
    const data=await api(endpoint('/owned-collection'));
    if(version!==renderVersion)return;
    renderOwnedCollection(data);decoratePurchaseCards();
  }
  if(page==='plan') {
    if(!$('#display-currency'))$('#plan-form').insertAdjacentHTML('beforeend',`<details><summary>Advanced: currency display estimate</summary><p class="muted spaced">Enter your own exchange rate. This changes only the displayed estimate, never the Store prices or optimization.</p><div class="grid"><div><label for="display-currency">Display currency</label><select id="display-currency" name="display_currency"><option value="">No conversion</option>${['USD','CAD','GBP','EUR','AUD','JPY'].map(c=>`<option ${conversion.currency===c?'selected':''}>${c}</option>`).join('')}</select></div><div><label for="exchange-rate">Display units per 1 ${currency[project.storefront]}</label><input id="exchange-rate" name="exchange_rate" type="number" min="0.000001" step="any" value="${esc(conversion.rate)}" placeholder="User-supplied rate"></div></div></details>`);
    if(currentPlan)renderPlanResult();
  }
  if(page==='library') await loadLibrary(0,version);
  if(page==='export') {
    if(!$('#export-preferred-format'))$('#export-options').insertAdjacentHTML('afterbegin',exportFileControls());
    await refreshExportPreview();
  }
}
let jobPollGeneration=0, jobPollProject=null;
const completedJobsSeen=new Set();
function renderJobs(jobs) {renderGuidedJobs(jobs);}
async function refreshJobs() {
  if(!project){const jobs=await api('/api/jobs');renderJobs(jobs);return jobs;}
  const pid=project.id, jobs=await api(`/api/projects/${enc(pid)}/jobs`);
  if(project?.id===pid)renderJobs(jobs);
  return jobs;
}
async function watchJob() {
  if(!project)return;
  const pid=project.id;
  if(jobPollProject===pid)return;
  jobPollProject=pid;const generation=++jobPollGeneration;let firstPoll=true, failures=0;
  try {
    while(project?.id===pid&&generation===jobPollGeneration){
      let jobs;
      try { jobs=await refreshJobs(); if(failures)notify('Connection restored.');failures=0; }
      catch(e){failures++;notify('Progress connection interrupted; reconnecting automatically. '+e.message,true);await new Promise(resolve=>setTimeout(resolve,Math.min(30000,1500*2**Math.min(failures,5))));continue;}
      if(project?.id!==pid||generation!==jobPollGeneration)return;
      let changed=false;
      for(const job of jobs){
        if(job.kind==='plan')continue;
        if(!['running','queued'].includes(job.status)&&!completedJobsSeen.has(job.id)){
          completedJobsSeen.add(job.id);changed=changed||!firstPoll||!!project?.busy;
        }
      }
      firstPoll=false;
      if(changed&&project?.id===pid)await reloadAfterJob();
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  }catch(e){notify(e.message,true);}
  finally{if(generation===jobPollGeneration)jobPollProject=null;}
}
async function beginJob(kind,body) {const result=await api(endpoint('/'+kind),'POST',body);await refreshJobs();watchJob(result.job);}
async function updateRecording(id,body) {await api(endpoint(`/recordings/${enc(id)}`),'PATCH',body);await reload();}
async function updateRelease(id,body) {await api(endpoint(`/releases/${enc(id)}`),'PATCH',body);await reload();}
function modal(html) {$('#dialog-body').innerHTML=html;$('#dialog').showModal();}
function exportParams() {
  return new URLSearchParams({format:$('input[name="export-format"]:checked')?.value||'m3u',
    extinf:!!$('#export-extinf')?.checked, slashes:$('#export-slashes')?.value||'windows',
    preferred_format:$('#export-preferred-format')?.value||'any',preferred_folder:$('#export-preferred-folder')?.value||'',prefer_quality:$('#export-quality')?.checked??true,
    path_mode:$('#export-replace-mode')?.value||'prefix',custom_path:!!$('#export-custom')?.checked, path_from:$('#export-from')?.value||'', path_to:$('#export-to')?.value||''});
}
let exportPreviewVersion=0;
async function refreshExportPreview() {
  const version=++exportPreviewVersion, pid=project.id, viewVersion=renderVersion;
  const button=$('[data-action="export"]');if(button)button.disabled=true;
  if(!validateExportDestination())return;
  let preview;
  try{preview=await api(endpoint('/export-preview')+'?'+exportParams());}
  catch(error){if(version===exportPreviewVersion&&viewVersion===renderVersion&&project?.id===pid&&$('#export-preview')){
    $('#export-preview').innerHTML=`<div class="warning" role="alert"><strong>Export needs attention</strong><p>${esc(error.message)}</p><p>Check the advanced export options, including any specific file choices, then try again.</p><button class="secondary" data-action="retry-export-preview">Check again</button></div>`;
    $('#export-advanced').open=true;
  }return;}
  if(version!==exportPreviewVersion || viewVersion!==renderVersion || project?.id!==pid || !$('#export-preview'))return;
  renderAccessibleExport(preview);
}
window.addEventListener('focus',async()=>{
  if(!window.pywebview || !settings)return;
  try{const fresh=await api('/api/settings');const changed=fresh.connected!==settings.connected;settings=fresh;if(changed){await render(captureDrafts());notify(fresh.connected?'Spotify connected.':'Spotify disconnected.');}}catch(e){console.warn('Could not refresh connection status',e);}
});
async function downloadExport() {
  if(!validateExportDestination())return;
  const params=exportParams();
  const response=await fetch(endpoint('/export')+'?'+params,{method:'POST',headers:{'X-App-Token':token}});
  if(!response.ok){const data=await response.json();throw new Error(data.error || 'Export failed.');}
  const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='playlist-owned.'+params.get('format');a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);notify(params.get('format').toUpperCase()+' playlist exported.');
}
const actions={
  ...guidedActions,
  'more-candidates':async key=>{candidateLimits.set(key,(candidateLimits.get(key)||100)+100);if(key.startsWith('file:'))reviewLocal(key.slice(5));else await render(captureDrafts());},
  'sync-listening':async()=>{settings.listening=await api('/api/listening/sync','POST');renderListeningStatus();watchListening();},
  'disconnect-listening':async()=>{settings.listening=await api('/api/listening/disconnect','POST');await reload();},
  'review-local':id=>reviewLocal(id),
  'confirm-local':async (id,button)=>{await api(endpoint(`/files/${enc(id)}/match`),'POST',{track_id:button.dataset.track,action:'confirm'});$('#dialog').close();await reload();notify('Local song identified and marked owned.');},
  discover:()=>beginJob('discover'),reimport:()=>beginJob('import'),'refresh-prices':()=>beginJob('refresh'),
  'own-recording':id=>updateRecording(id,{ownership_override:!project.recordings[id].effective_owned}),
  'reset-ownership':id=>updateRecording(id,{reset_override:true,owned:false}),
  include:id=>updateRecording(id,{included:!project.recordings[id].included}),
  required:id=>updateRecording(id,{required:!project.recordings[id].required}),
  'own-release':async id=>{
    const r=project.releases[id];
    if(!r.owned){await updateRelease(id,{owned:true});return;}
    modal(`<h2>Remove full-release ownership?</h2><p>${r.partial?.length||0} previously marked individual recordings can remain owned. Ownership from other releases, local files, and recording overrides is unaffected.</p><div class="actions"><button data-action="restore-partial" data-id="${esc(id)}">Keep previous partial ownership</button><button class="secondary" data-action="clear-release-ownership" data-id="${esc(id)}">Clear ownership from this release</button></div>`);
  },
  'restore-partial':async id=>{$('#dialog').close();await updateRelease(id,{owned:false});notify('Full-release ownership removed; previous partial ownership retained.');},
  'clear-release-ownership':async id=>{$('#dialog').close();await updateRelease(id,{clear_ownership:true});notify('Ownership from this release cleared. Other ownership sources are unchanged.');},
  'library-page':async id=>loadLibrary(Number(id)),
  'exclude-release':id=>updateRelease(id,{excluded:!project.releases[id].excluded}),
  'review-recording':async id=>{deferredMatches.delete(project.id+':'+id);selectedRecording=id;reviewAll=true;reviewFilter='all';query='';if(location.hash==='#review')await render();else location.hash='review';},
  'select-recording':async id=>{selectedRecording=id;await render();},
  'confirm-match':async (id,button)=>{
    const pid=project.id, rid=selectedRecording;
    button.textContent='Saving match…';
    const decision=await api(endpoint(`/recordings/${enc(rid)}/match`),'POST',{track_id:id,action:'confirm'});
    if(project?.id!==pid)return;
    const confirmedRid=decision.recording_id||rid;
    selectedRecording=confirmedRid;
    notify('Match confirmed and saved.');
    await reload();
    try{await api(`/api/projects/${enc(pid)}/recordings/${enc(confirmedRid)}/release`,'POST',{});await refreshJobs();watchJob();}
    catch(e){notify(`Match saved. Release lookup could not start: ${e.message}`,true);}
  },
  'reject-match':async id=>{await api(endpoint(`/recordings/${enc(selectedRecording)}/match`),'POST',{track_id:id,action:'reject'});await reload();},
  'load-release':async id=>{await api(endpoint(`/recordings/${enc(id)}/release`),'POST',{});await refreshJobs();watchJob();},
  'cancel-operation':async id=>{await api(`/api/jobs/${enc(id)}/cancel`,'POST',{});await refreshJobs();},
  'dismiss-operation':async id=>{await api(`/api/jobs/${enc(id)}/dismiss`,'POST',{});await refreshJobs();},
  partial:id=>{const r=project.releases[id];modal(`<h2>Choose owned songs: ${esc(r.name)}</h2><p>Select the songs you own from this release.</p><form id="partial-form" data-id="${esc(id)}" class="stack">${r.coverage.map(rid=>`<label class="check"><input type="checkbox" name="recording" value="${esc(rid)}" ${r.owned||(r.partial||[]).includes(rid)?'checked':''}>${esc(project.recordings[rid]?.title)}</label>`).join('') || '<p>No confirmed covered recordings yet.</p>'}<button type="submit">Save owned songs</button></form>`);},
  connect:async()=>{const data=await api('/api/oauth/start','POST',{});if(window.pywebview){window.open(data.url,'_blank');notify('Finish Spotify sign-in in your browser, then return here.');}else location.assign(data.url);},
  disconnect:async()=>{await api('/api/oauth/disconnect','POST',{});settings=await api('/api/settings');notify('Spotify disconnected.');await render();},
  export:downloadExport,
  'open-project':async id=>{await selectProject(id);location.hash='overview';},
  'rename-project':id=>{const p=projects.find(p=>p.id===id);modal(`<h2>Rename playlist</h2><form id="rename-form" data-id="${esc(id)}" class="stack"><label for="rename-name">Name</label><input id="rename-name" name="name" value="${esc(p.name)}" required maxlength="200"><button type="submit">Save name</button></form>`);},
  'duplicate-project':async id=>{const p=await api(`/api/projects/${enc(id)}/duplicate`,'POST',{});await loadProjects();await selectProject(p.id);notify('Playlist duplicated.');},
  'delete-project':id=>{const p=projects.find(p=>p.id===id);modal(`<h2>Delete ${esc(p.name)}?</h2><p>This removes the saved playlist and its decisions. Your music files remain on disk.</p><form id="delete-form" data-id="${esc(id)}"><button class="danger" type="submit">Delete playlist</button></form>`);}
};
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const fn=actions[button.dataset.action];if(!fn)return;
  const previousHTML=button.innerHTML;button.disabled=true;
  try{await fn(button.dataset.id,button);}catch(e){notify(e.message,true);}finally{
    if(button.isConnected){
      button.innerHTML=previousHTML;
      if(button.dataset.action==='export')await refreshExportPreview();
      else button.disabled=false;
    }
  }
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(form.getAttribute('method')==='dialog')return;
  event.preventDefault();if(form.dataset.submitting==='true')return;
  form.dataset.submitting='true';
  const f=new FormData(form);const button=event.submitter || form.querySelector('button[type="submit"]');if(button)button.disabled=true;
  try {
    if(form.id==='listening-form'){
      settings.listening=await api('/api/listening/connect','POST',{provider:f.get('provider'),username:f.get('username'),days:Number(f.get('days')),api_key:f.get('api_key')||'',token:f.get('token')||''});
      form.querySelectorAll('input[type=password]').forEach(input=>input.value='');
      renderListeningStatus();watchListening();await refreshJobs();
    } else if(form.id==='csv-import-form'){
      if(event.submitter?.value==='commit') {
        if(!csvDraft)throw new Error('Choose a CSV and preview it before importing.');
        const params=new URLSearchParams({name:f.get('name')||'',storefront:f.get('storefront'),filename:csvDraft.filename});
        const result=await csvRequest('/api/import/csv?'+params.toString(),csvDraft.bytes);
        csvDraft=null;await loadProjects();await selectProject(result.project);location.hash='overview';
        notify(`Imported ${result.count} playlist entries (${result.recording_count} unique songs; ${result.count-result.recording_count} duplicate appearances). Automatic matching is running.`);
      } else {
        const file=f.get('file');
        if(!file?.size)throw new Error('Choose a nonempty Exportify CSV.');
        if(file.size>10*1024*1024)throw new Error('Choose a CSV smaller than 10 MB.');
        const previewVersion=++csvPreviewVersion;
        csvDraft=null;$('#csv-commit').hidden=true;$('#csv-commit').disabled=true;
        $('#csv-preview').textContent='Reading your CSV…';
        const bytes=await file.arrayBuffer();
        const result=await csvRequest('/api/import/csv/preview',bytes);
        if(!form.isConnected || previewVersion!==csvPreviewVersion || !$('#csv-preview'))return;
        if(result.can_import)csvDraft={bytes,filename:file.name};
        showCsvPreview(result);
      }
    } else if(form.id==='playlist-update-form'){
      const pid=project.id, mode=f.get('mode'), feedback=$('#playlist-update-feedback');
      if(f.get('source')==='csv'){
        const file=f.get('file');
        if(!file?.size)throw new Error('Choose a nonempty Exportify CSV.');
        if(file.size>10*1024*1024)throw new Error('Choose a CSV smaller than 10 MB.');
        const bytes=await file.arrayBuffer();
        const preview=await csvRequest('/api/import/csv/preview',bytes);
        if(!form.isConnected || project?.id!==pid)return;
        if(!preview.can_import){
          feedback.innerHTML=`<div class="warning">${preview.error_count} rows need correction. The playlist has not changed.<ul>${preview.errors.map(e=>`<li>Line ${e.line}: ${esc(e.message)}</li>`).join('')}</ul></div>`;
          return;
        }
        await csvRequest(`/api/projects/${enc(pid)}/playlist/csv?`+new URLSearchParams({mode,filename:file.name}),bytes);
      } else {
        await api(`/api/projects/${enc(pid)}/playlist/spotify`,'POST',{mode,url:f.get('url')});
      }
      notify('Playlist update started. Existing catalog data will be reused.');
      await reload();
    } else if(form.id==='import-form'||form.id==='new-project'){
      const p=await api('/api/projects','POST',{name:f.get('name')||'Spotify Playlist',storefront:f.get('storefront'),url:f.get('url')||''});
      await loadProjects();await selectProject(p.id);if(form.id==='import-form')await beginJob('import');else notify('Playlist created.');location.hash='overview';
    } else if(form.id==='settings-form'){
      await api('/api/settings','POST',{spotify_id:f.get('spotify_id'),spotify_secret:f.get('spotify_secret'),clear_secret:f.has('clear_secret'),storefront:f.get('storefront'),performance:{api_concurrency:Number(f.get('api_concurrency')),background_jobs:Number(f.get('background_jobs'))},retention:{job_days:Number(f.get('job_days')),price_days:Number(f.get('price_days')),export_count:Number(f.get('export_count'))},preferences:{clean_explicit_equivalent:f.has('clean_explicit_equivalent'),remasters_equivalent:f.has('remasters_equivalent')}});
      settings=await api('/api/settings');notify('Settings saved.');await reload();
    } else if(form.id==='manual-search'){
      notify('Searching the Store…');const result=await api(endpoint(`/recordings/${enc(selectedRecording)}/search`),'POST',{term:f.get('term')});notify(`Found ${result.count} Store results.`);await reload();
    } else if(form.id==='plan-form'){
      planOptions={strategy:f.get('strategy'),budget:!f.has('budget')||f.get('budget')===''?null:Number(f.get('budget')),purchase_penalty:Number(f.get('purchase_penalty')),artist:f.get('artist')||''};
      conversion={currency:f.get('display_currency'),rate:f.get('exchange_rate')};localStorage.setItem('pp-conversion',JSON.stringify(conversion));await calculatePlan();
    } else if(form.id==='local-search-form'){await api(endpoint(`/files/${enc(form.dataset.id)}/search`),'POST',{term:f.get('term')});await loadLibrary(libraryPage.offset||0);reviewLocal(form.dataset.id);}
    else if(form.id==='scan-form')await beginJob('scan',{folder:f.get('folder')});
    else if(form.classList.contains('local-match-form')){await api(endpoint(`/files/${enc(form.dataset.id)}`),'PATCH',{recording_id:f.get('recording_id')||null});notify('Local file match saved.');await reload();}
    else if(form.id==='partial-form'){await updateRelease(form.dataset.id,{owned:false,partial:f.getAll('recording')});$('#dialog').close();}
    else if(form.id==='rename-form'){await api(`/api/projects/${enc(form.dataset.id)}`,'PATCH',{name:f.get('name')});$('#dialog').close();await reload();}
    else if(form.id==='delete-form'){const id=form.dataset.id;await api(`/api/projects/${enc(id)}`,'DELETE');$('#dialog').close();if(project?.id===id)project=null;await loadProjects();await selectProject(project?.id||projects[0]?.id||'');notify('Playlist deleted.');}
    else if(form.id==='restore-form'){const file=f.get('file');if(file.size>128*1024*1024)throw new Error('Choose a playlist file smaller than 128 MB.');const p=await api('/api/restore','POST',JSON.parse(await file.text()));await loadProjects();await selectProject(p.id||projects[0]?.id||'');notify('Backup restored. Scan your local files again before exporting.');}
  }catch(e){notify(e.message,true);}finally{delete form.dataset.submitting;if(button)button.disabled=false;}
});
document.addEventListener('input',event=>{const draft=event.target.closest('form, #export-options');if(draft)draft.dataset.dirty='true';if(event.target.closest('#plan-form'))updatePlanState();if(event.target.id==='device-folder'){syncDeviceDestination();}if(event.target.id==='song-search'){query=event.target.value;$('#song-table').innerHTML=songTable(filtered(recordings()));}if(event.target.id==='release-search'){query=event.target.value;renderPlanResult();}});
document.addEventListener('change',event=>{
  handleGuidedChange(event);
  if(event.target.closest('#plan-form'))updatePlanState();
  if(event.target.id==='purchase-view'){purchaseView=event.target.value;renderPlanResult();}
  if(event.target.dataset.exportRecording){
    const rid=event.target.dataset.exportRecording,path=event.target.value,pid=project.id;
    api(`/api/projects/${enc(pid)}/export-files/${enc(rid)}`,'PATCH',{path:path||null}).then(()=>{
      if(project?.id!==pid)return;
      project.export_file_overrides??={};if(path)project.export_file_overrides[rid]=path;else delete project.export_file_overrides[rid];
      return refreshExportPreview();
    }).catch(e=>notify(e.message,true));return;
  }
  const draft=event.target.closest('form, #export-options');if(draft)draft.dataset.dirty='true';
  if(event.target.id==='listening-provider'){
    $('#listenbrainz-setup').hidden=event.target.value!=='listenbrainz';
    $('#lastfm-setup').hidden=event.target.value!=='lastfm';
  }
  if(event.target.id==='update-source'){
    const csv=event.target.value==='csv';
    $('#update-csv-field').hidden=!csv;$('#update-csv').required=csv;
    $('#update-spotify-field').hidden=csv;$('#update-url').required=!csv;
  }
  if(event.target.closest('#export-options')){
    $('#export-path-fields').hidden=!$('#export-custom').checked;
    updateDeviceExample();refreshExportPreview().catch(e=>notify(e.message,true));
  }
  if(event.target.id==='review-all'){reviewAll=event.target.checked;render().catch(e=>notify(e.message,true));}
  if(event.target.id==='playlist-csv') {
    csvDraft=null;csvPreviewVersion++;$('#csv-commit').hidden=true;$('#csv-commit').disabled=true;$('#csv-preview').textContent='';
    const file=event.target.files[0];if(file)$('#csv-project-name').value=file.name.replace(/\.csv$/i,'').slice(0,200);
  }
});
$('#project-picker').addEventListener('change',event=>selectProject(event.target.value).catch(e=>notify(e.message,true)));
window.addEventListener('hashchange',()=>{query='';render().catch(e=>notify(e.message,true));});
document.addEventListener('keydown',event=>{
  if(event.ctrlKey||event.metaKey||event.altKey||event.target.matches('input,textarea,select,[contenteditable="true"]')||$('#dialog').open)return;
  const key=event.key.toLowerCase();
  if(key==='?'){event.preventDefault();location.hash='help';}
  if(key==='e'){event.preventDefault();location.hash='export';}
  if(key==='/'){event.preventDefault();const input=$('#song-search, #release-search, #manual-term');let parent=input?.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}input?.focus();}
  if(location.hash==='#review'){
    if(key==='n'||key==='p'){event.preventDefault();const list=[...document.querySelectorAll('[data-action="select-recording"]')];const i=list.findIndex(b=>b.dataset.id===selectedRecording);list[(i+(key==='n'?1:-1)+list.length)%list.length]?.click();}
    if(key==='m'||key==='r'){event.preventDefault();document.querySelector(`[data-action="${key==='m'?'confirm-match':'reject-match'}"]`)?.click();}
    if(key==='o'&&selectedRecording){event.preventDefault();actions['own-recording'](selectedRecording).catch(e=>notify(e.message,true));}
  }
});
(async()=>{try{settings=await api('/api/settings');await loadProjects();const saved=localStorage.getItem('pp-project');await selectProject(projects.some(p=>p.id===saved)?saved:projects[0]?.id||'');const oauth=new URLSearchParams(location.search).get('oauth');if(oauth){notify(oauth==='connected'?'Spotify connected. You can import your playlist.':'Spotify sign-in was cancelled.');history.replaceState(null,'',location.pathname+location.hash);}}catch(e){notify(e.message,true);$('#main').innerHTML=empty('Could not open the workspace','Reload the page or restart the app.');}})();
