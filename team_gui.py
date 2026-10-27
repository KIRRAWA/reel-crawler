#!/usr/bin/env python3
"""team_gui.py -- browser-based team hub for the reel-crawler review toolchain.

Launch from the command line (opens your browser automatically):

    python3 team_gui.py            # or: python3 review_team.py gui

One page for everything the team does together:

  * Shared repo setup -- point the sync repo at ONE GitHub repo. A single lab
    GitHub account is enough for the whole team: everyone pushes with the same
    GitHub credential (paste its token once -- the hub remembers it on this
    machine and pre-fills it next time), and members are told apart by their
    OWN account + password below -- git commits are authored with that account
    name, so the history still shows who reviewed what. No need to add every
    member as a GitHub collaborator.
  * Accounts -- create member accounts (only salted PBKDF2 hashes are stored,
    never plaintext passwords).
  * Login / logout -- password login on this machine.
  * Sync -- pull before reviewing, push after (same as review_team.py sync).
  * Progress + disputes -- everyone's review counts and conflicting verdicts.

Stdlib only. The review queue itself stays at http://127.0.0.1:8765
(review_gui.py); this page logs you in and launches it for you.
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import review_team as rt

REVIEW_PORT = 8765
SECRETS = rt.ROOT / '.hub_credentials.json'   # URL + token memory for THIS machine
PAGE_VERSION = '2026-10-27.1'                 # bump to make stale tabs show a reload hint

PAGE = '''<!doctype html>
<html><head><meta charset="utf-8"><title>Reel review · team hub</title>
<style>
body{font:15px/1.55 system-ui;margin:0;background:#f4f6fa;color:#1c2330}
header{padding:14px 24px;background:#101826;color:#fff;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header .t{font:700 18px ui-monospace,monospace}
header .muted{color:#9fb0c6;font-size:13px}
header button{background:#243040;color:#cfd8e6;border:1px solid #3a4a61;border-radius:6px;padding:4px 12px;cursor:pointer}
#banner{background:#fff7e6;border-bottom:1px solid #ecd9a0;padding:9px 24px;font-size:14px}
.wrap{max-width:980px;margin:0 auto;padding:18px 22px 70px;display:grid;gap:16px}
.card{background:#fff;border:1px solid #dde4ee;border-radius:12px;padding:16px 20px}
.card h2{margin:0 0 4px;font-size:16px}
.card .hint{color:#5b6b80;font-size:13px;margin:0 0 10px}
.card h2 .badge{font-size:12px;font-weight:500;color:#2f6fed;margin-left:8px}
label{display:block;font-size:13px;color:#5b6b80;margin:10px 0 3px}
input[type=text],input[type=password],input[type=number]{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #c6d2e2;border-radius:8px;font:inherit}
textarea{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #c6d2e2;border-radius:8px;font:inherit;margin:10px 0 2px}
.row{display:flex;gap:10px;flex-wrap:wrap}
.row>div{flex:1;min-width:200px}
button.act{background:#2f6fed;color:#fff;border:none;border-radius:8px;padding:9px 18px;font:600 14px system-ui;cursor:pointer;margin-top:12px}
button.act.ghost{background:#f0f4fa;color:#2f6fed;border:1px solid #c9d9f4}
button.act:disabled{opacity:.5;cursor:default}
a.act{display:inline-block;background:#2f6fed;color:#fff;border:none;border-radius:8px;padding:9px 18px;font:600 14px system-ui;cursor:pointer;margin-top:12px;text-decoration:none}
a.act.ghost{background:#f0f4fa;color:#2f6fed;border:1px solid #c9d9f4}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #e8edf5}
th{color:#5b6b80;font-weight:600;font-size:12px}
td.you{font-weight:700}
.msg{margin-top:10px;font-size:13px;white-space:pre-wrap}
.msg.err{color:#b3261e}
.msg.ok{color:#1a7f37}
.chk{display:flex;gap:8px;align-items:center;margin-top:12px;font-size:14px;color:#1c2330}
.chk input{width:auto}
.disagree{color:#b3261e;font-weight:700}
.step{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0;font-size:14px}
.step .hint{margin:0}
.step input{width:auto;padding:4px 8px}
.tick{width:20px;font:700 16px system-ui;color:#1a7f37;text-align:center}
.tick.off{color:#c6d2e2}
button.sm{padding:4px 10px;font-size:12px;margin-top:0}
.clog{display:none;background:#101826;color:#9fb0c6;padding:10px 12px;border-radius:8px;max-height:240px;overflow:auto;font:12px/1.55 ui-monospace,monospace;white-space:pre-wrap;margin-top:10px}
</style></head>
<body>
<header><span class="t">reel-crawler · team hub</span>
 <span class="muted" id="hdr">localhost only</span>
 <span style="flex:1"></span>
 <span class="muted" id="who"></span>
 <a id="btn-review-top" class="act" href="http://127.0.0.1:8765/" style="display:none;padding:5px 14px;font-size:13px" target="_blank">Open review queue →</a>
 <button id="btn-logout" style="display:none">Log out</button>
</header>
<div id="banner" style="display:none">First run: set up the shared repo (step 1), create the member accounts (step 2), then each person logs in with their own password (step 3).</div>
<div class="wrap">

<div class="card">
 <h2>1 · Shared GitHub repo <span class="badge" id="repo-badge"></span></h2>
 <p class="hint">One GitHub repo for the whole team. A single lab account is enough: paste its token once, and every member pushes with that same credential — people are told apart by their own account + password (step 2), and every git commit is authored with that account name. Leave the token empty to use this machine's own GitHub access instead (e.g. SSH). The URL and token are remembered on this machine only (never uploaded) and filled in automatically the next time you open the hub.</p>
 <div class="row"><div style="flex:2.4">
  <label for="repo-url">Repo URL (https:// or git@ — where the shared state lives)</label>
  <input type="text" id="repo-url" placeholder="https://github.com/lab-org/reel-review-sync">
 </div><div>
  <label for="repo-token">GitHub token (optional — saved on this machine only, never uploaded)</label>
  <input type="text" id="repo-token" placeholder="ghp_…">
 </div></div>
 <button class="act" id="btn-setup">Set up / update remote</button>
 <button class="act ghost" id="btn-forget">Clear saved URL &amp; token</button>
 <div class="msg" id="setup-msg"></div>
</div>

<div class="card">
 <h2>2 · Member accounts</h2>
 <p class="hint">Each member gets their own username + password — that is what keeps everyone's reviews apart, no matter which GitHub account the repo lives under. Only salted PBKDF2 hashes are stored (and synced); plaintext passwords never leave the machine.</p>
 <table id="acc-table"><thead><tr><th>Account</th><th>Opinions</th><th>Reviewed</th><th>Last decision (UTC)</th></tr></thead><tbody></tbody></table>
 <div class="row">
  <div><label for="new-name">New username (letters, digits, dot, dash, underscore)</label>
   <input type="text" id="new-name" placeholder="david"></div>
  <div><label for="new-pw">Password (at least 4 characters)</label>
   <input type="password" id="new-pw"></div>
  <div><label for="new-pw2">Repeat password</label>
   <input type="password" id="new-pw2"></div>
 </div>
 <button class="act ghost" id="btn-create">Create account</button>
 <div class="msg" id="acc-msg"></div>
</div>

<div class="card">
 <h2>3 · Log in on this machine <span class="badge" id="login-badge"></span></h2>
 <div id="login-form">
  <p class="hint">Logging in checks your password, then pulls the latest shared state from GitHub, so your review queue is always up to date. If the checkbox is on, the review page opens right after login — if your browser blocks that pop-up, use the manual button above instead.</p>
  <div class="row">
   <div><label for="li-name">Username</label><input type="text" id="li-name"></div>
   <div><label for="li-pw">Password</label><input type="password" id="li-pw"></div>
  </div>
  <div class="chk"><input type="checkbox" id="li-open" checked><span>Open the review queue right after login</span></div>
  <button class="act" id="btn-login">Log in</button>
 </div>
 <div id="login-done" style="display:none">
  <div class="msg ok" id="login-who"></div>
  <a id="btn-review" class="act" href="http://127.0.0.1:8765/" target="_blank">Open review queue →</a>
  <button class="act ghost" id="btn-passwd">Change my password</button>
 </div>
 <div class="msg" id="login-msg"></div>
</div>

<div class="card">
 <h2>4 · Sync <span class="badge" id="sync-badge"></span></h2>
 <p class="hint">Sync: online → this machine = download everyone's latest videos and reviews. Sync: this machine → online = upload yours — your reviews AND any new video metadata from your local collection stores (the videos themselves never leave the machine). The review queue now saves your decisions locally as you go and uploads them all together when you press Submit (s) at the end — exam style — so these two buttons are mainly for collecting or checking progress.</p>
 <button class="act ghost" id="btn-pull">Sync: online → this machine</button>
 <button class="act ghost" id="btn-push">Sync: this machine → online</button>
 <div class="msg" id="sync-msg"></div>
</div>

<div class="card">
 <h2>5 · Disputes</h2>
 <p class="hint">Videos where reviewers disagree (accept vs reject, or different categories). All opinions are kept — nothing is overwritten.</p>
 <table id="dis-table"><thead><tr><th>Video</th><th>@author</th><th>Verdicts</th></tr></thead><tbody></tbody></table>
</div>

<div class="card">
 <h2>6 · Add videos to the pool</h2>
 <p class="hint">Found reels the team should review (e.g. downloaded locally)? Paste their links here — one per line — and they appear in every member's review queue after their next pull. Only public metadata (URL, author, likes, caption) is shared; no video files leave this machine. Author / caption / likes are optional and apply to all the lines at once.</p>
 <textarea id="pool-urls" rows="4" placeholder="https://www.instagram.com/reel/AbCd1234/&#10;https://www.instagram.com/reel/EfGh5678/"></textarea>
 <div class="row">
  <div><label for="pool-user">@author (optional)</label><input type="text" id="pool-user" placeholder="some.creator"></div>
  <div><label for="pool-caption">Caption (optional)</label><input type="text" id="pool-caption"></div>
  <div><label for="pool-likes">Likes (optional)</label><input type="number" id="pool-likes" min="0" placeholder="1200"></div>
 </div>
 <button class="act ghost" id="btn-pool-add">Add to the pool</button>
 <div class="msg" id="pool-msg"></div>
</div>

<div class="card" id="collect-card">
 <h2>7 · Collect new reels <span class="badge" id="collect-badge"></span></h2>
 <p class="hint">Every member can find new reels for the pool. The collector opens Instagram in a browser and drives itself: it browses the feed automatically, every reel stays on screen for the same fixed time, and at the end it saves frame info and pushes the videos into everyone's review queue. Tick the three boxes below and the Start button lights up.</p>
 <div class="step"><span class="tick off" id="tick-deps">·</span><b>1 · Collector dependencies</b> (Playwright + speech model)
  <button class="act ghost sm" id="btn-deps-check">Re-check</button>
  <span class="hint" id="deps-help" style="display:none"></span>
 </div>
 <div class="step"><span class="tick off" id="tick-ig">·</span><b>2 · Instagram login</b> — use a clean account whose feed has not been trained toward one topic
  <button class="act ghost sm" id="btn-ig-login">Open Instagram login</button>
  <span class="hint" id="ig-help"></span>
 </div>
 <div class="step"><span class="tick off" id="tick-team">·</span><b>3 · Team login</b> — this name signs your collected videos in the pool
  <span class="hint" id="team-who"></span>
  <span id="collect-login" style="display:none"><input type="text" id="cl-name" placeholder="username"><input type="password" id="cl-pw" placeholder="password"><button class="act ghost sm" id="btn-cl-login">Log in</button></span>
 </div>
 <div class="row">
  <div><label for="c-target">How many reels to collect</label><input type="number" id="c-target" min="1" value="100"></div>
  <div><label for="c-delay">Seconds each reel stays on screen</label><input type="number" id="c-delay" min="1" value="5"></div>
  <div><label for="c-output">Output folder (local)</label><input type="text" id="c-output" value="feed_candidates_mine"></div>
  <div><label for="c-minlikes">Minimum likes</label><input type="number" id="c-minlikes" min="0" value="10000"></div>
 </div>
 <div class="chk"><input type="checkbox" id="c-rescreen" checked><span>After collecting: screen &amp; save frame info automatically (no LLM — every video goes to the review queue)</span></div>
 <button class="act" id="btn-collect-start" disabled>Start collection</button>
 <button class="act ghost" id="btn-collect-stop" style="display:none">Stop</button>
 <div class="msg" id="collect-msg"></div>
 <pre class="clog" id="collect-log"></pre>
</div>

</div>
<script>
const $=id=>document.getElementById(id);
const PAGEV='2026-10-27.1';
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});return r.json();}
function msg(id,text,ok){const m=$(id);m.textContent=text||'';m.className='msg'+(text?(ok?' ok':' err'):'');}
let tokenFilled=false;    // prefill the saved token only once per page load
async function refresh(){
 const s=await api('/api/state');
 if(s.error){msg('setup-msg',s.error);return;}
 $('hdr').textContent='pool: '+s.pool_total+' videos · stores: '+(s.stores.join(', ')||'none');
 if(s.version&&s.version!==PAGEV){$('banner').style.display='';
  $('banner').textContent='The hub was updated — reload this page (Cmd/Ctrl+Shift+R) to use the new version.';}
 else $('banner').style.display=s.initialized?'none':'';
 $('repo-badge').textContent=s.initialized?(s.remote?'connected':'no remote yet'):'not initialized';
 const saved=s.saved||{};
 if(!$('repo-url').value)$('repo-url').value=saved.url||s.remote||'';
 if(!tokenFilled&&!$('repo-token').value)$('repo-token').value=saved.token||'';
 tokenFilled=true;
 const tb=$('acc-table').querySelector('tbody');tb.innerHTML='';
 s.accounts.forEach(a=>{const tr=document.createElement('tr');
  tr.innerHTML='<td'+(a.name===s.session?' class="you"':'')+'>'+esc(a.name)+(a.name===s.session?' (you)':'')+'</td>'
   +'<td>'+a.opinions+'</td><td>'+a.done+' / '+a.total+'</td><td>'+esc(a.last_utc||'—')+'</td>';
  tb.appendChild(tr);});
 if(!s.accounts.length)tb.innerHTML='<tr><td colspan="4" class="hint" style="padding:10px 0">No accounts yet — create the first one above.</td></tr>';
 const loggedIn=!!s.session;
 $('login-badge').textContent=loggedIn?s.session:'not logged in';
 $('login-form').style.display=loggedIn?'none':'';
 $('login-done').style.display=loggedIn?'':'none';
 if(loggedIn)$('login-who').textContent='You are logged in as '+s.session+' on this machine.';
 $('who').textContent=loggedIn?s.session:'';
 $('btn-logout').style.display=loggedIn?'':'none';
 $('btn-review-top').style.display=loggedIn?'':'none';
 $('sync-badge').textContent=s.initialized?(s.remote?'ready':'no remote'):'needs setup';
 const dt=$('dis-table').querySelector('tbody');dt.innerHTML='';
 s.disputes.forEach(d=>{const tr=document.createElement('tr');
  tr.innerHTML='<td>'+esc(d.code)+'</td><td>@'+esc(d.username||'?')+'</td><td>'
   +d.opinions.map(o=>'<span class="'+(o.action==='reject'?'disagree':'')+'">'+esc(o.user)+': '+esc(o.action)+(o.category?'/'+esc(o.category):'')+'</span>').join(' &nbsp;·&nbsp; ')+'</td>';
  dt.appendChild(tr);});
 if(!s.disputes.length)dt.innerHTML='<tr><td colspan="3" class="hint" style="padding:10px 0">No disputes yet — every reviewed video has unanimous verdicts.</td></tr>';
}
$('btn-setup').onclick=async()=>{const r=await api('/api/setup',{url:$('repo-url').value.trim(),token:$('repo-token').value.trim()});
 msg('setup-msg',r.error||r.message,r.ok);if(r.ok){$('repo-token').value='';refresh();}};
$('btn-forget').onclick=async()=>{const r=await api('/api/forget');$('repo-token').value='';msg('setup-msg',r.error||r.message,r.ok);refresh();};
$('btn-create').onclick=async()=>{
 const pw=$('new-pw').value,pw2=$('new-pw2').value;
 if(pw!==pw2){msg('acc-msg','Passwords do not match.');return;}
 const r=await api('/api/create',{name:$('new-name').value.trim(),pw});
 msg('acc-msg',r.error||r.message,r.ok);if(r.ok){$('new-name').value='';$('new-pw').value='';$('new-pw2').value='';refresh();}};
const RP=8765,RQ='http://127.0.0.1:'+RP+'/';
function tryOpen(url){try{const w=window.open(url,'_blank');return !(!w||w.closed);}catch(e){return false;}}
function ensureReview(){fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});}
async function afterLogin(r){
 if(r.ok){
  msg('login-msg',r.message,true);
  if($('li-open').checked){
   const q=await api('/api/review');
   if(q.error){msg('login-msg','Logged in, but the review queue could not be opened: '+q.error);}
   else setTimeout(()=>{if(!tryOpen(RQ))msg('login-msg','Your browser blocked the pop-up — click "Open review queue →" above instead.',true);},300);
  }
 }else msg('login-msg',r.error||r.message);
 refresh();}
$('btn-login').onclick=async()=>afterLogin(await api('/api/login',{name:$('li-name').value.trim(),pw:$('li-pw').value}));
$('li-pw').addEventListener('keydown',async e=>{if(e.key==='Enter')afterLogin(await api('/api/login',{name:$('li-name').value.trim(),pw:$('li-pw').value}));});
$('btn-logout').onclick=async()=>{await api('/api/logout');$('li-pw').value='';refresh();};
async function manualOpen(e){
 if(e.ctrlKey||e.metaKey||e.button===1){ensureReview();return;}   // native open (server is kept running)
 e.preventDefault();
 msg('login-msg','Opening review queue…');
 try{
  const q=await api('/api/review');
  if(q.error){msg('login-msg','Could not open the review queue: '+q.error);return;}
 }catch(err){}    // hub unreachable? try the direct link anyway
 if(!tryOpen(RQ))window.location.href=RQ;    // pop-up blocked: open in this tab (Back returns here)
}
$('btn-review').onclick=manualOpen;
$('btn-review-top').onclick=manualOpen;
$('btn-passwd').onclick=async()=>{
 const old=prompt('Current password:'),nu=prompt('New password (at least 4 characters):');
 if(old===null||nu===null)return;
 const r=await api('/api/password',{old,nu});msg('login-msg',r.error||r.message,r.ok);};
async function doSync(action,btn){btn.disabled=true;const r=await api('/api/sync',{action});btn.disabled=false;msg('sync-msg',r.error||r.message,r.ok);refresh();}
$('btn-pull').onclick=e=>doSync('pull',e.target);
$('btn-push').onclick=e=>doSync('push',e.target);
$('btn-pool-add').onclick=async()=>{
 const urls=$('pool-urls').value.split('\n').map(s=>s.trim()).filter(Boolean);
 if(!urls.length){msg('pool-msg','Paste at least one reel URL (one per line).');return;}
 const likes=$('pool-likes').value.trim();
 const btn=$('btn-pool-add');btn.disabled=true;
 const r=await api('/api/pool_add',{urls,username:$('pool-user').value.trim(),caption:$('pool-caption').value.trim(),likes:likes?Number(likes):null});
 btn.disabled=false;
 if(r.error){msg('pool-msg',r.error);return;}
 msg('pool-msg',r.message,r.ok);
 if(r.ok&&r.added&&r.added.length){$('pool-urls').value='';$('pool-likes').value='';refresh();}
};
async function pollCollect(){
 const s=await api('/api/collect_state');
 if(!s||s.error)return;
 const pre=s.prereqs||{};
 const tick=(on,id)=>{const el=$(id);el.textContent=on?'✓':'·';el.className='tick'+(on?'':' off');};
 tick(pre.deps,'tick-deps'); tick(pre.ig,'tick-ig'); tick(pre.team,'tick-team');
 const dh=$('deps-help');
 dh.textContent=pre.deps?'':('Missing. In the tool folder run:  pip install -r requirements.txt  then Re-check. ('+esc(pre.deps_msg||'')+')');
 dh.style.display=pre.deps?'none':'';
 $('ig-help').textContent=s.phase==='login'?'Browser open — log in there; cookies save automatically.':'';
 $('team-who').textContent=pre.team?('— logged in as '+pre.team):'';
 $('collect-login').style.display=pre.team?'none':'';
 const running=!!s.running;
 const ready=!running&&pre.deps&&pre.ig&&!!pre.team;
 $('btn-collect-start').disabled=!ready;
 $('btn-collect-stop').style.display=running?'':'none';
 $('btn-ig-login').disabled=running;
 $('collect-badge').textContent=running?
  (s.phase==='login'?'waiting for Instagram login…':s.phase==='collect'?'collecting…':s.phase==='screen'?'screening & saving frames…':s.phase)
  :(s.phase==='error'?'error — see log below':s.phase==='done'?'done — see log below':'');
 const lg=$('collect-log');
 if(s.log!==undefined){lg.textContent=s.log;lg.scrollTop=lg.scrollHeight;}
 lg.style.display=(s.log||running)?'':'none';
}
$('btn-deps-check').onclick=pollCollect;
$('btn-ig-login').onclick=async()=>{const r=await api('/api/ig_login');msg('collect-msg',r.error||r.message,r.ok);};
$('btn-cl-login').onclick=async()=>{
 const r=await api('/api/login',{name:$('cl-name').value.trim(),pw:$('cl-pw').value});
 if(r.ok){$('cl-pw').value='';msg('collect-msg',r.message,true);}else msg('collect-msg',r.error||r.message);
 refresh();
};
$('btn-collect-start').onclick=async()=>{
 const r=await api('/api/collect_start',{target:Number($('c-target').value),delay:Number($('c-delay').value),output:$('c-output').value.trim(),min_likes:Number($('c-minlikes').value),rescreen:$('c-rescreen').checked});
 msg('collect-msg',r.error||r.message,r.ok);
 if(r.ok)$('collect-msg').textContent='';
};
$('btn-collect-stop').onclick=async()=>{const r=await api('/api/collect_stop');msg('collect-msg',r.error||r.message,r.ok);};
setInterval(pollCollect,1500);
pollCollect();
if(location.hash==='#collect'){const c=$('collect-card');if(c)c.scrollIntoView();}
refresh();
</script></body></html>'''


# --------------------------------------------------------------------------
# actions (mirror the review_team.py CLI, with human-readable results)
# --------------------------------------------------------------------------

def load_secrets():
    try:
        return json.loads(SECRETS.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_secrets(url, token):
    """Remember the repo URL + token on this machine (0600, never committed)."""
    fd = os.open(str(SECRETS), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'url': url, 'token': token}, f)


def state():
    sess = rt.session_user()
    p = rt.pool() if rt.SYNC.is_dir() else {}
    names = sorted(set(rt.accounts() + rt.reviewers()))
    accounts = []
    for n in names:
        done, total, latest = (rt.progress(n, p) if p else (0, 0, {}))
        last = max((o.get('utc', '') for o in latest.values()), default='')
        accounts.append({'name': n, 'opinions': len(latest),
                         'done': done, 'total': total, 'last_utc': last})
    disputes = [{'code': r['code'], 'username': r.get('username'), 'url': r['url'],
                 'opinions': [{'user': o['user'], 'action': o['action'],
                               'category': o.get('category') or '',
                               'utc': o['utc']} for o in r['opinions']]}
                for r in rt.dispute_rows(p)] if p else []
    return {'initialized': rt.SYNC.is_dir() and (rt.SYNC / '.git').is_dir(),
            'version': PAGE_VERSION,
            'remote': rt.config().get('remote', ''),
            'saved': load_secrets(),
            'session': sess,
            'accounts': accounts,
            'pool_total': len(p),
            'stores': [d.name for d in rt.find_stores()],
            'disputes': disputes}


def do_setup(url, token):
    url = (url or '').strip()
    if not url:
        raise ValueError('Paste the GitHub repo URL first.')
    if not re.fullmatch(r'(?:https?|ssh|git|file)://\S+|git@\S+:\S+', url):
        raise ValueError('Repo URL should look like https://github.com/org/repo '
                         'or git@github.com:org/repo')
    token = (token or '').strip()
    cred = url
    if token:
        if not url.startswith('https://'):
            raise ValueError('A token only works with https:// repo URLs.')
        cred = 'https://' + token + '@' + url[len('https://'):]
    created = rt.init_local(quiet=True)
    rt.git(['remote', 'remove', 'origin'], check=False)
    rt.git(['remote', 'add', 'origin', cred])
    cfg = rt.config()
    cfg['remote'] = url            # the CLEAN url -- tokens never enter the repo
    cfg['auto_sync'] = True
    (rt.SYNC / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n',
                                         encoding='utf-8')
    rt._git_cfg(rt.session_user() or 'admin')
    rt.git(['add', 'config.json'])
    rt.git(['commit', '-m', 'sync: set shared repo remote'], check=False)
    tail = ' Token stored only in this machine\'s local git config.' if token else ''
    if created:
        # Fresh local repo: push it up. If the remote rejects the push, another
        # machine already set the shared repo up -- start from a clone instead.
        r = rt.git(['push', '-u', 'origin', 'main'], check=False)
        if r.returncode != 0:
            shutil.rmtree(str(rt.SYNC))
            r2 = subprocess.run(['git', '-C', str(rt.ROOT), 'clone', cred, 'sync_repo'],
                                env=rt.git_env(), capture_output=True, text=True)
            if r2.returncode != 0:
                # A failed clone can leave a partial sync_repo/ behind, which
                # would poison every later setup attempt -- remove it.
                if rt.SYNC.is_dir():
                    shutil.rmtree(str(rt.SYNC))
                raise RuntimeError('could not reach the remote (wrong token or URL?): '
                                   + (r2.stderr or '').strip()[-200:])
            save_secrets(url, token)
            return ('Sync repo cloned from ' + url + ' -- ready to pull and push.')
        save_secrets(url, token)
        return 'Sync repo created and pushed to ' + url + '.' + tail
    rt._push()
    save_secrets(url, token)
    return 'Sync repo pointed at ' + url + '.' + tail


def do_forget():
    if SECRETS.exists():
        SECRETS.unlink()
        return 'Saved URL & token removed from this machine.'
    return 'Nothing saved yet.'


def do_create(name, pw):
    if not rt.SYNC.is_dir():
        raise RuntimeError('Set up the shared repo first (step 1).')
    rt.account_add(name, pw)
    return f"Account {name!r} created. Now that member can log in on any machine."


def do_login(name, pw):
    if not rt.SYNC.is_dir():
        raise RuntimeError('Set up the shared repo first (step 1).')
    if name not in rt.accounts():
        raise ValueError(f"Unknown account {name!r}.")
    if not rt.verify_password(name, pw):
        raise ValueError('Wrong password.')
    (rt.SYNC / '.session.json').write_text(
        json.dumps({'name': name, 'login_utc': rt.now()}) + '\n', encoding='utf-8')
    message = f'Logged in as {name} on this machine.'
    if rt._remote():
        try:
            rt.sync_pull(quiet=True)
            message += f' Pulled latest team state ({len(rt.pool())} videos in the pool).'
        except RuntimeError as exc:
            message += f' (could not pull yet: {exc})'
    return message


def do_logout():
    if (rt.SYNC / '.session.json').exists():
        (rt.SYNC / '.session.json').unlink()
        return 'Logged out.'
    return 'Nobody was logged in.'


def do_password(old, new):
    user = rt.session_user()
    if not user:
        raise RuntimeError('Log in first.')
    if not rt.verify_password(user, old):
        raise ValueError('Current password is wrong.')
    if len(new) < 4:
        raise ValueError('New password must be at least 4 characters.')
    p = rt.SYNC / 'accounts' / f'{user}.json'
    salt, digest = rt.hash_password(new)
    p.write_text(json.dumps({'name': user, 'salt': salt, 'hash': digest},
                            indent=2) + '\n', encoding='utf-8')
    rt._git_cfg(user)
    rt.git(['add', p.relative_to(rt.SYNC).as_posix()])
    rt.git(['commit', '-m', f'accounts: change password for {user}'])
    rt._push()
    return 'Password updated.'


def do_sync(action):
    if action == 'pull':
        rt.sync_pull(quiet=True)
        return f'Pulled latest team state -- pool has {len(rt.pool())} videos.'
    rt.sync_push('sync', quiet=True)
    return 'Pushed this machine\'s changes to the shared repo.'


def do_pool_add(urls, username, caption, likes):
    user = rt.session_user()
    if not user:
        raise RuntimeError('Log in first (step 3).')
    urls = [u for u in (urls or []) if isinstance(u, str) and u.strip()]
    if not urls:
        raise ValueError('Paste at least one reel URL (one per line).')
    res = rt.add_pool_items(user, urls, username=username or '',
                            caption=caption or '', likes=likes)
    parts = []
    if res['added']:
        parts.append(f"added {len(res['added'])}: {' '.join(res['added'])}")
    if res['skipped']:
        parts.append(f"{len(res['skipped'])} already in the pool")
    if res['errors']:
        parts.append(f"{len(res['errors'])} skipped (not a reel URL)")
    if not parts:
        parts.append('nothing to add')
    return {'added': res['added'], 'skipped': res['skipped'],
            'errors': res['errors'], 'message': '; '.join(parts)}


# --------------------------------------------------------------------------
# collector control: run feed_collector.py from the hub with a live log
# --------------------------------------------------------------------------

COLLECTOR = rt.ROOT / 'feed_collector.py'
IG_PROFILE = rt.ROOT / 'instagram-session'

_COLLECT = {'proc': None, 'phase': 'idle', 'log': [], 'exit': None,
            'stopped': False, 'lock': threading.Lock()}


def _coll_log(line):
    with _COLLECT['lock']:
        _COLLECT['log'].append(line.rstrip('\n'))
        del _COLLECT['log'][:-400]
    print('[collect] ' + line.rstrip('\n'), flush=True)


def _coll_running():
    p = _COLLECT['proc']
    return p is not None and p.poll() is None


def _spawn_collector(args, phase, on_exit=None):
    """Start feed_collector.py; stream its stdout into the shared log."""
    cmd = [sys.executable, str(COLLECTOR)] + args
    proc = subprocess.Popen(cmd, cwd=str(rt.ROOT), env=rt.git_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, start_new_session=True)
    with _COLLECT['lock']:
        _COLLECT['proc'] = proc
        _COLLECT['phase'] = phase
        _COLLECT['exit'] = None
    _coll_log('$ ' + ' '.join(cmd))

    def tail():
        for line in proc.stdout:
            _coll_log(line)
        code = proc.wait()
        with _COLLECT['lock']:
            _COLLECT['proc'] = None
            _COLLECT['exit'] = code
        _coll_log(f'-- exited with code {code} --')
        if on_exit:
            on_exit(code)

    threading.Thread(target=tail, daemon=True).start()
    return proc


def collect_prereqs():
    """The three checkmarks: collector deps, Instagram login, team login."""
    deps, deps_msg = True, ''
    try:
        import playwright  # noqa: F401
        import faster_whisper  # noqa: F401
    except Exception as exc:
        deps, deps_msg = False, f'{type(exc).__name__}: {exc}'
    return {'deps': deps, 'deps_msg': deps_msg,
            'ig': (IG_PROFILE / 'cookies.txt').is_file(),
            'team': rt.session_user()}


def do_ig_login():
    """Open the collector's browser on Instagram; the login saves itself."""
    if _coll_running():
        raise RuntimeError('A collector process is already running -- stop it first.')
    _spawn_collector(['--login'], 'login',
                     on_exit=lambda code: _COLLECT.update(phase='idle'))
    return {'message': 'Browser opened for Instagram login. Log in in the browser '
                       'window -- the session saves itself once the login registers.'}


def do_collect_start(data):
    if _coll_running():
        raise RuntimeError('A collector process is already running -- stop it first.')
    pre = collect_prereqs()
    if not pre['deps']:
        raise RuntimeError('Step 1: collector dependencies are not installed. '
                           f'({pre["deps_msg"]})')
    if not pre['ig']:
        raise RuntimeError('Step 2: log in to Instagram first (Open Instagram login).')
    if not pre['team']:
        raise RuntimeError('Step 3: log in to the team account first.')
    target = int(data.get('target') or 100)
    delay = float(data.get('delay') or 5)
    min_likes = int(data.get('min_likes') or 0)
    output = str(data.get('output') or 'feed_candidates_mine')
    if not 1 <= target <= 100000:
        raise ValueError('How many reels: 1..100000')
    if delay < 1 or delay > 120:
        raise ValueError('Seconds each reel stays on screen: 1..120')
    if min_likes < 0:
        raise ValueError('Minimum likes: 0 or more')
    if not re.fullmatch(r'[\w.-]+', output) or output.startswith('.'):
        raise ValueError('Output folder: letters, digits, dot, dash, underscore')
    auto = bool(data.get('rescreen', True))

    base = ['--target', str(target), '--delay', f'{delay:g}', '--output', output,
            '--min-likes', str(min_likes), '--llm', 'off']

    def screen_done(code):
        with _COLLECT['lock']:
            if _COLLECT['stopped']:
                _COLLECT['phase'] = 'stopped'
                _COLLECT['stopped'] = False
            else:
                _COLLECT['phase'] = 'done' if code == 0 else 'error'

    def collect_done(code):
        with _COLLECT['lock']:
            if _COLLECT['stopped']:
                _COLLECT['phase'] = 'stopped'
                _COLLECT['stopped'] = False
                return
        if code != 0:
            with _COLLECT['lock']:
                _COLLECT['phase'] = 'error'
            return
        if auto:
            _coll_log('Collection finished -- screening and saving frame info now (no LLM).')
            _spawn_collector(['--rescreen', '--target', str(target), '--output', output,
                              '--llm', 'off'], 'screen', on_exit=screen_done)
        else:
            with _COLLECT['lock']:
                _COLLECT['phase'] = 'done'

    _spawn_collector(base, 'collect', on_exit=collect_done)
    return {'message': 'Collection started -- the browser browses the feed by itself. '
                       'Keep its window open.'}


def do_collect_stop():
    p = _COLLECT['proc']
    if p is None or p.poll() is not None:
        return {'message': 'Nothing is running.'}
    with _COLLECT['lock']:
        _COLLECT['stopped'] = True
    _coll_log('Stop requested -- closing the collector...')
    try:
        p.terminate()
    except Exception as exc:
        _coll_log(f'stop error: {exc}')

    def kill_later():
        time.sleep(5)
        if p.poll() is None:
            p.kill()

    threading.Thread(target=kill_later, daemon=True).start()
    return {'message': 'Stopping...'}


def _port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        s.connect(('127.0.0.1', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_port(port, timeout=15.0):
    """Wait until a server is listening on 127.0.0.1:port (startup takes a few
    seconds: imports + team pull). Without this, the browser tab opens too
    early and shows a connection-refused page."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.2)
    return False


def do_review():
    if not rt.session_user():
        raise RuntimeError('Log in first (step 3).')
    launch = not _port_open(REVIEW_PORT)
    if launch:
        subprocess.Popen([sys.executable, str(rt.ROOT / 'review_gui.py'),
                          '--no-browser'],
                         cwd=str(rt.ROOT), start_new_session=True)
        if not _wait_port(REVIEW_PORT):
            raise RuntimeError('The review queue took too long to start -- '
                               'click "Open review queue" again (it may just '
                               'need a moment).')
    return {'launch': launch, 'port': REVIEW_PORT}


# --------------------------------------------------------------------------
# tiny local server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?')[0] == '/':
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split('?')[0] == '/api/state':
            self.send_json(state())
            return
        if self.path.split('?')[0] == '/api/collect_state':
            with _COLLECT['lock']:
                log = '\n'.join(_COLLECT['log'][-200:])
                phase = _COLLECT['phase']
                running = _COLLECT['proc'] is not None and _COLLECT['proc'].poll() is None
            self.send_json({'ok': True, 'phase': phase, 'running': running,
                            'log': log, 'prereqs': collect_prereqs()})
            return
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
        except Exception:
            data = {}
        try:
            path = self.path.split('?')[0]
            if path == '/api/setup':
                result = do_setup(data.get('url'), data.get('token'))
            elif path == '/api/forget':
                result = do_forget()
            elif path == '/api/create':
                result = do_create(str(data.get('name') or ''), str(data.get('pw') or ''))
            elif path == '/api/login':
                result = do_login(str(data.get('name') or ''), str(data.get('pw') or ''))
            elif path == '/api/logout':
                result = do_logout()
            elif path == '/api/password':
                result = do_password(str(data.get('old') or ''), str(data.get('nu') or ''))
            elif path == '/api/sync':
                result = do_sync(data.get('action'))
            elif path == '/api/pool_add':
                result = do_pool_add(data.get('urls'), data.get('username'),
                                     data.get('caption'), data.get('likes'))
            elif path == '/api/collect_start':
                result = do_collect_start(data)
            elif path == '/api/collect_stop':
                result = do_collect_stop()
            elif path == '/api/ig_login':
                result = do_ig_login()
            elif path == '/api/review':
                result = do_review()
            else:
                self.send_error(404)
                return
        except (ValueError, RuntimeError) as exc:
            self.send_json({'error': str(exc)})
            return
        except Exception as exc:
            traceback.print_exc()
            self.send_json({'error': f'internal error: {exc}'})
            return
        if isinstance(result, dict):
            self.send_json({'ok': True, **result})
        else:
            self.send_json({'ok': True, 'message': result})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8766, help='local server port')
    ap.add_argument('--no-browser', action='store_true', help='do not open the browser')
    ap.add_argument('--collect', action='store_true',
                    help='open the page on the collect card (card 7)')
    args = ap.parse_args()
    hash_part = '#collect' if args.collect else ''
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        url = f'http://127.0.0.1:{args.port}'
        print(f'Team hub is already running: {url}')
        if not args.no_browser:
            webbrowser.open(url + hash_part)
        return
    url = f'http://127.0.0.1:{args.port}'
    if rt.session_user() and not _port_open(REVIEW_PORT):
        # Someone is logged in on this machine: have the review queue ready
        # before the page loads, so its open button works instantly.
        subprocess.Popen([sys.executable, str(rt.ROOT / 'review_gui.py'),
                          '--no-browser'],
                         cwd=str(rt.ROOT), start_new_session=True)
        print('Review queue started in the background (already logged in).')
    print(f'Team hub: {url}   (review queue lives on port {REVIEW_PORT})')
    print('Ctrl-C to quit.')
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, [url + hash_part]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
