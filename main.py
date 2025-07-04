# main.py
# webhook_test
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import PlainTextResponse
import subprocess
import hmac
import hashlib

app = FastAPI()


GITHUB_SECRET = b"no_secret"

def verify_github_signature(request_body: bytes, signature_header: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    signature = signature_header.split("=")[1]
    mac = hmac.new(GITHUB_SECRET, msg=request_body, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()

    return hmac.compare_digest(expected_signature, signature)

@app.post("/payload")
async def github_webhook(request: Request):
    signature = request.headers.get("X-Hub-Signature-256")
    body = await request.body()
    if not verify_github_signature(body, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")
    user_agent = request.headers.get("User-Agent", "")
    if not user_agent.startswith("GitHub-Hookshot/"):
        raise HTTPException(status_code=403, detail="Invalid User-Agent")
    payload = await request.json()
    print("Received valid GitHub webhook:", payload)
    subprocess.run("nohup bash restart_app.sh > restart.log 2>&1 &", shell=True)
    return PlainTextResponse("Pulled and restarted", status_code=200)

@app.post("/test2")
async def webhook(request: Request):
    return PlainTextResponse("Auto restart working", status_code=200)
