"""E2E test server: real email_review API + stub ingest + built UI."""
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from email_review import router as email_router
from governance_api import router as governance_router
import uuid

app = FastAPI()
app.include_router(email_router)
app.include_router(governance_router)

@app.post("/ingest/batches")
async def stub_ingest(user_id: str, files: list[UploadFile] = File(...)):
    return {"batch_id": "batch_" + uuid.uuid4().hex[:6], "accepted": len(files),
            "user_id": user_id}

@app.get("/clients")
def clients(): return {"clients": []}

@app.get("/rag/collections")
def rag(): return {"collections": []}

app.mount("/", StaticFiles(directory="ui/dist", html=True), name="ui")
