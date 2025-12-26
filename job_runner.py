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


def today_sg() -> str:
    return datetime.now(SG_TZ).strftime("%Y-%m-%d")


def make_output_path() -> str:
    # e.g., ipo_results/singapore_ipos_2025-12-23.txt
    return f"{OUTPUT_DIR}/singapore_ipos_{today_sg()}.txt"


def get_sg_ipo_updates_via_web_search() -> str:
    """
    Uses OpenAI Responses API with web_search tool to find SG IPO updates.
    Enforces plain-text output (no Markdown) and prioritizes SGX/MAS.
    """
    client = OpenAI()
    today = today_sg()

    prompt = f"""
You are a careful finance research assistant.

Goal:
Find newly announced or upcoming Initial Public Offerings (IPOs) relevant to Singapore in the last 7 days (as of {today}).
Relevance = intended SGX listing, Singapore-registered issuer listing on SGX, or officially announced Singapore listing plans.

Start by searching authoritative PUBLIC sources first:
1) SGX main site: https://www.sgx.com
2) SGX Securities section: https://www.sgx.com/securities
3) SGX “links.sgx.com” documents (prospectus / offer documents / announcements): https://links.sgx.com
4) MAS site (only if relevant to IPO filings/announcements): https://www.mas.gov.sg
5) SGX ipo listing https://www.sgx.com/securities/ipo-prospectus

Optional / secondary sources:
- Business Times / other news sites MAY be paywalled. Do NOT rely on paywalled pages for confirmation unless the relevant facts are visible publicly elsewhere.

Hard rules:
- PLAIN TEXT ONLY. Do not use Markdown. No bullet symbols like “•” are fine, but avoid Markdown link formatting [text](url).
- Do NOT invent IPOs. Every IPO item must have at least one source URL that supports it.
- If you are not sure, do not claim it as confirmed. Put it under “WATCHLIST (Unconfirmed)”.

Output format (plain text):
Singapore IPO Watch - {today}

CONFIRMED (with sources)
1) Company:
   Exchange/Board:
   Expected listing date (or TBA):
   Brief notes (1-2 lines):
   Sources:
   - https://...

(Repeat…)

WATCHLIST (Unconfirmed)
(Only if you found credible hints but cannot confirm from authoritative public sources)

If there are no credible new updates, output exactly:
No credible new Singapore IPO announcements found in the last 7 days.
And then list the public sources you checked (raw URLs).
"""

    resp = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        input=prompt,
        tools=[{"type": "web_search"}],
    )

    text = (resp.output_text or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned empty output_text.")
    return text


def github_get_file(repo: str, branch: str, path: str, token: str):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "sg-ipo-tracker-bot",
    }
    r = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    if r.status_code == 404:
        return None, ""
    r.raise_for_status()
    data = r.json()
    sha = data.get("sha")
    content_b64 = (data.get("content") or "").replace("\n", "")
    existing = ""
    if content_b64:
        existing = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    return sha, existing


def github_put_file(repo: str, branch: str, path: str, token: str, new_text: str, sha: str | None, message: str):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "sg-ipo-tracker-bot",
    }
    content_b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")

    payload = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    get_env("OPENAI_API_KEY", required=True)
    github_token = get_env("GITHUB_TOKEN", required=True)

    repo = os.environ.get("GITHUB_REPO", "Krish1959/sg-ipo-tracker").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip()

    output_path = make_output_path()

    # 1) Fetch IPO updates (plain text)
    body = get_sg_ipo_updates_via_web_search()

    # 2) Wrap with a run timestamp (still plain text)
    stamp = datetime.now(SG_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    final_text = "\n".join([
        "=" * 80,
        f"Run timestamp: {stamp}",
        body.strip(),
        "",
    ])

    # 3) Create/update dated file in GitHub
    sha, existing = github_get_file(repo, branch, output_path, github_token)

    # If already exists with same content, do nothing
    if existing.strip() == final_text.strip():
        print("No changes detected; file already up to date.")
        return

    msg = f"Singapore IPO watch - {today_sg()}"
    github_put_file(
        repo=repo,
        branch=branch,
        path=output_path,
        token=github_token,
        new_text=final_text,
        sha=sha,
        message=msg,
    )

    print(f"Updated {output_path} in {repo} on branch {branch}.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print("HTTP error:", e)
        try:
            print("Response:", e.response.text)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
