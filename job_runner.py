#Improved by Gemini on 7 Jan 2026
import os
import sys
import base64
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from openai import OpenAI

SG_TZ = ZoneInfo("Asia/Singapore")
OUTPUT_DIR = "ipo_results"

def get_env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "").strip()
    if required and not val:
        raise RuntimeError(f"Missing env var {name}")
    return val

def check_sgx_connection():
    """
    Explicitly checks if SGX is blocking the runner.
    """
    target_url = "https://www.sgx.com/securities/ipo-prospectus"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(target_url, headers=headers, timeout=15)
        if response.status_code == 403:
            return "BLOCKED: HTTP 403 (WAF/Bot Protection active)"
        if "cloudflare" in response.text.lower():
            return "BLOCKED: Cloudflare Challenge detected"
        return "SUCCESSFUL: Connected to SGX"
    except Exception as e:
        return f"ERROR: Could not reach SGX ({str(e)})"

def get_sg_ipo_updates_via_web_search() -> str:
    client = OpenAI()
    today = datetime.now(SG_TZ).strftime("%Y-%m-%d")
    
    # 1. Perform connection check
    connection_status = check_sgx_connection()

    prompt = f"""
You are a careful finance research assistant. Today's date is {today}.

TASK: Identify Singapore listings with STRICT filtering.

1. BOT CHECK: 
Current status for SGX connection is: {connection_status}. 
If it says 'BLOCKED', report this at the top of your output.

2. SECTION A (Last 7 Days):
Find newly filed or announced IPOs/ETFs from {today} back to 7 days ago.

3. SECTION B (Active Only):
List ALL entries from the SGX IPO Prospectus page, BUT YOU MUST APPLY A DATE FILTER:
- Logic: If 'Closing Date' < {today}, EXCLUDE it. 
- Goal: Do not list closed or obsolete entries like MetaOptics (Sep 2025) or UltraGreen (Dec 2025).
- Include only those where Closing Date is today, in the future, or marked as 'TBA/To be announced'.

Format: Plain text only. Include SGX source URLs.
"""

    resp = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"), # Using a robust model for date logic
        input=prompt,
        tools=[{"type": "web_search"}],
    )

    text = (resp.output_text or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned empty output.")
    return text

def github_get_file(repo: str, branch: str, path: str, token: str):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    if r.status_code == 404: return None, ""
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data.get("content", "").replace("\n", "")).decode("utf-8")
    return data.get("sha"), content

def github_put_file(repo: str, branch: str, path: str, token: str, text: str, sha: str | None, msg: str):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Content-Type": "application/json"}
    payload = {"message": msg, "content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "branch": branch}
    if sha: payload["sha"] = sha
    r = requests.put(url, headers=headers, data=json.dumps(payload), timeout=30)
    r.raise_for_status()

def main():
    github_token = get_env("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO", "Krish1959/sg-ipo-tracker").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip()
    
    today_str = datetime.now(SG_TZ).strftime("%Y-%m-%d")
    output_path = f"{OUTPUT_DIR}/singapore_ipos_{today_str}.txt"

    # Step 1: Generate Content
    body = get_sg_ipo_updates_via_web_search()
    stamp = datetime.now(SG_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    final_text = f"Run timestamp: {stamp}\n\n{body}"

    # Step 2: Push to GitHub
    sha, existing = github_get_file(repo, branch, output_path, github_token)
    
    # Check if content is truly new (prevents empty "success" runs)
    if existing.strip() == final_text.strip():
        print("No new content found compared to existing file. Skipping update.")
        return

    github_put_file(repo, branch, output_path, github_token, final_text, sha, f"Update IPO watch {today_str}")
    print(f"Successfully updated {output_path}")

if __name__ == "__main__":
    main()