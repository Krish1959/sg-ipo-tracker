import os
import sys
import base64
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI

SG_TZ = ZoneInfo("Asia/Singapore")

# Where the file will live in your GitHub repo
GITHUB_PATH = "ipo_results/singapore_ipos.txt"


def get_env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "").strip()
    if required and not val:
        raise RuntimeError(f"Missing env var {name}")
    return val


def get_sg_ipo_updates_via_web_search() -> str:
    """
    Uses OpenAI Responses API with web_search tool to find SG IPO updates.
    """
    client = OpenAI()
    today = datetime.now(SG_TZ).strftime("%Y-%m-%d")

    prompt = f"""
You are a finance research assistant.

Task:
Find newly announced or upcoming Initial Public Offerings (IPOs) relevant to Singapore (SGX listings, Singapore-based issuers, or listings strongly tied to Singapore) in the last 7 days as of {today}.

Requirements:
- Prefer authoritative sources: SGX announcements, company press releases, reputable financial news.
- For each item provide:
  1) Company / issuer name
  2) Expected listing date (or TBA)
  3) Exchange/board (SGX Mainboard/Catalist) if available
  4) Brief description (1–2 lines)
  5) Source URL(s)

Output format (plain text):
Singapore IPO Watch – {today}
1) ...
2) ...

If there are no credible new updates, say:
No credible new Singapore IPO announcements found in the last 7 days.

Do NOT invent IPOs. Only include items supported by sources.
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
    """
    Returns (sha, existing_text) if file exists, else (None, "").
    """
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
    content_b64 = data.get("content", "")
    content_b64 = content_b64.replace("\n", "")

    existing = ""
    if content_b64:
        existing = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    return sha, existing


def github_put_file(repo: str, branch: str, path: str, token: str, new_text: str, sha: str | None, message: str):
    """
    Create or update a file in GitHub using Contents API.
    """
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


def build_new_file_content(existing: str, new_block: str) -> str:
    """
    Appends a timestamped block to the existing content (with basic de-dupe).
    """
    stamp = datetime.now(SG_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    section = "\n".join([
        "=" * 80,
        f"Run timestamp: {stamp}",
        new_block.strip(),
        ""
    ])

    if section in existing:
        return existing  # no change
    if not existing.strip():
        return section + "\n"
    return existing.rstrip() + "\n" + section + "\n"


def main():
    # Required env vars on Render:
    openai_key = get_env("OPENAI_API_KEY", required=True)
    github_token = get_env("GITHUB_TOKEN", required=True)

    # Optional env vars:
    repo = os.environ.get("GITHUB_REPO", "Krish1959/sg-ipo-tracker").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip()

    # 1) Get IPO updates
    new_block = get_sg_ipo_updates_via_web_search()

    # 2) Read current file from GitHub (if any)
    sha, existing_text = github_get_file(repo, branch, GITHUB_PATH, github_token)

    # 3) Build updated content
    updated_text = build_new_file_content(existing_text, new_block)

    if updated_text == existing_text:
        print("No changes detected; nothing to update in GitHub.")
        return

    # 4) Push updated content to GitHub
    today = datetime.now(SG_TZ).strftime("%Y-%m-%d")
    msg = f"Update Singapore IPO watch – {today}"

    github_put_file(
        repo=repo,
        branch=branch,
        path=GITHUB_PATH,
        token=github_token,
        new_text=updated_text,
        sha=sha,
        message=msg,
    )

    print(f"Updated {GITHUB_PATH} in {repo} on branch {branch}.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        # Print response text to help debugging auth/permissions
        print("HTTP error:", e)
        try:
            print("Response:", e.response.text)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
