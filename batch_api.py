"""PrefectOS batch API + minimal built-in UI (upload, watch, open reports).

Entrypoint for the document-processing service:
    python -m uvicorn batch_api:app --reload --port 8000     (dev, laptop)
    systemd: prefectos.service -> uvicorn batch_api:app       (VM)

Serves:
    /                    service status JSON
    /ui                  built-in batch console (upload, live status, reports)
    /ingest/...          the batch_ingest router (batches, metrics, SSE)
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from batch_ingest.api import router, ingest_lifespan
from batch_ingest.worker import OUTPUT_ROOT

app = FastAPI(title="PrefectOS batch API", lifespan=ingest_lifespan)
app.include_router(router)


@app.get("/")
def root():
    return {"service": "PrefectOS batch API", "status": "up",
            "endpoints": ["/ui", "/ingest/batches", "/ingest/metrics"]}


@app.get("/ingest/batches/{batch_id}/files")
def batch_files(batch_id: str):
    d = Path(OUTPUT_ROOT) / batch_id
    if not d.is_dir():
        return {"batch_id": batch_id, "files": []}
    return {"batch_id": batch_id,
            "files": sorted(p.name for p in d.iterdir() if p.is_file())}


@app.get("/ingest/batches/{batch_id}/file/{name}")
def batch_file(batch_id: str, name: str):
    p = (Path(OUTPUT_ROOT) / batch_id / name).resolve()
    if not str(p).startswith(str(Path(OUTPUT_ROOT).resolve())) or not p.is_file():
        raise HTTPException(404, "not found")
    media = "text/html" if p.suffix == ".html" else "application/json"
    return FileResponse(p, media_type=media)


@app.get("/ui", response_class=HTMLResponse)
def ui():
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>PrefectOS — batch console</title>
<style>
 body{font:15px/1.5 system-ui;max-width:820px;margin:2rem auto;padding:0 1rem;color:#1B2431}
 h1{font-size:20px} .card{border:1px solid #D5DDE9;border-radius:10px;padding:16px;margin:14px 0}
 button{background:#1B2431;color:#fff;border:0;border-radius:8px;padding:8px 18px;cursor:pointer}
 table{border-collapse:collapse;width:100%;font-size:13px}
 td,th{border-bottom:1px solid #E5EAF2;padding:6px 8px;text-align:left}
 .ok{color:#1E6B4E;font-weight:600} .warn{color:#A33B2E;font-weight:600}
 a{color:#185FA5} code{background:#F3F6FA;padding:1px 5px;border-radius:4px}
</style></head><body>
<h1>PrefectOS — batch console</h1>
<div class="card">
 <b>Upload a batch</b> (PDFs, up to 100)<br><br>
 <input type="file" id="files" multiple accept=".pdf">
 <input type="text" id="user" value="pilot" size="8">
 <button onclick="go()">Process</button>
 <div id="msg"></div>
</div>
<div class="card"><b>Batch status</b><div id="status">—</div></div>
<div class="card"><b>Outputs</b><div id="out">—</div></div>
<script>
let bid=null, timer=null;
async function go(){
 const fs=document.getElementById('files').files;
 if(!fs.length){document.getElementById('msg').textContent='pick at least one PDF';return}
 const fd=new FormData();
 for(const f of fs) fd.append('files', f);
 const u=document.getElementById('user').value||'pilot';
 const r=await fetch('/ingest/batches?user_id='+encodeURIComponent(u),{method:'POST',body:fd});
 const j=await r.json();
 if(!r.ok){document.getElementById('msg').textContent=JSON.stringify(j);return}
 bid=j.batch_id;
 document.getElementById('msg').innerHTML='Submitted <code>'+bid+'</code> ('+j.accepted+' docs)';
 if(timer)clearInterval(timer); timer=setInterval(poll,700); poll();
}
async function poll(){
 const r=await fetch('/ingest/batches/'+bid); const s=await r.json();
 document.getElementById('status').innerHTML =
  '<table><tr><th>done</th><th>clean</th><th>AI-repaired</th><th>escalated</th><th>failed</th><th>p95 ms</th></tr>'+
  '<tr><td>'+s.done+'/'+s.total+'</td><td class="ok">'+s.clean+'</td><td>'+s.resolved_by_llm+
  '</td><td class="warn">'+s.escalated+'</td><td class="warn">'+s.failed+'</td><td>'+(s.p95_ms??'—')+'</td></tr></table>';
 if(s.complete){clearInterval(timer); files();}
}
async function files(){
 const r=await fetch('/ingest/batches/'+bid+'/files'); const j=await r.json();
 document.getElementById('out').innerHTML = j.files.length ?
  j.files.map(f=>'<a target="_blank" href="/ingest/batches/'+bid+'/file/'+f+'">'+f+'</a>').join('<br>') : 'no files';
}
</script></body></html>"""
