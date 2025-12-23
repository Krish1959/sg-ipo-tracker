import os
import re
import sys
import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI


SG_TZ = ZoneInfo("Asia/Singapore")
OUTPUT_DIR = "ipo_results"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "singapore_ipos.txt")


def run_cmd(cmd, check=True, capture=True):
    """Run a shell command safely and return stdout."""
    result = subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def ensure_git_identity():
    """Ensure git has user.name and user.email set (required for commit on many hosts)."""
    name = run_cmd(["git", "config", "--get", "user.name"], check=False)
    email = run_cmd(["git", "config", "--get", "user.email"], check=False)

    if not name:
        run_cmd(["git", "config", "user.name", "sg-ipo-bot"], check=True)
    if not email:
        run_cmd(["git", "config", "user.email", "sg-ipo-bot@users.noreply.github.com"], check=True)


def configure_git_remote_with_token():
    """
    Render typically clones your repo with a read-only deploy key remote.
    To PUSH back to GitHub, we re-point origin to HTTPS with a token.

    Requires:
      - GITHUB_TOKEN: PAT with repo write permission
      - GITHUB_REPO: like "Krish1959/sg-ipo-tracker" (optional; defaults to that)
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing env var GITHUB_TOKEN (needed to push to GitHub).")

    repo = os.environ.get("GITHUB_REPO", "Krish1959/sg-ipo-tracker").strip()

    # Token-safe pattern GitHub accepts:
    # https://x-access-token:<TOKEN>@github.com/<OWNER>/<REPO>.git
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    # Set origin URL
    run_cmd(["git", "remote", "set-url", "origin", remote_url], check=True)


def get_sg_ipo_updates_via_web_search():
    """
    Uses OpenAI Responses API with the built-in web_search tool.
    Docs:
      - Web search tool guide
      - Responses API reference
    """
    client = OpenAI()

    today = datetime.now(SG_TZ).strftime("%Y-%m-%d")

    prompt = f"""
You are a finance research assistant.

Task:
Find *newly announced* or *upcoming* Initial Public Offerings (IPOs) relevant to Singapore (SGX listings, Singapore-based issuers, or listings strongly tied to Singapore) since the last 7 days, as of {today}.

Requirements:
- Prefer authoritative sources: SGX announcements, company press releases, MAS/filings where relevant, reputable Singapore/Asia financial news (e.g., Business Times, Bloomberg, Reuters, etc.)
- For each IPO item, provide:
  1) Company / issuer name
  2) Expected listing date (or “TBA”)
  3) Exchange/board (e.g., SGX Mainboard/Catalist) if available
  4) Brief description (1–2 lines)
  5) Source URL(s)

Output format (plain text):
- Start with a short heading: "Singapore IPO Watch – {today}"
- Then a numbered list.
- If there are no credible new updates, say: "No credible new Singapore IPO announcements found in the last 7 days."

Be careful: Do NOT invent IPOs. Only include items supported by sources.
"""

    # Ask model to use web_search tool, and include sources from the tool output.
    resp = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        input=prompt,
        tools=[{"type": "web_search"}],
        include=["web_search_call.action.sources"],
    )

    # The SDK provides resp.output_text as the assistant's final text.
    text = (resp.output_text or "").strip()

    # Collect sources (URLs) if present in tool call outputs
    sources = []
    try:
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) == "web_search_call":
                action = getattr(item, "action", None)
                if action and isinstance(action, dict):
                    srcs = action.get("sources") or []
                    for s in srcs:
                        url = s.get("url")
                        if url:
                            sources.append(url)
    except Exception:
        # If parsing sources fails, we still keep the model text.
        pass

    # De-duplicate sources while keeping order
    seen = set()
    uniq_sources = []
    for u in sources:
        if u not in seen:
            seen.add(u)
            uniq_sources.append(u)

    return text, uniq_sources


def append_results_to_file(block_text: str, sources: list[str]) -> bool:
    """
    Append a dated section to OUTPUT_FILE.
    Returns True if the file was changed (new content added), else False.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now = datetime.now(SG_TZ)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    section = []
    section.append("=" * 80)
    section.append(f"Run timestamp: {stamp}")
    section.append(block_text)
    if sources:
        section.append("")
        section.append("Sources discovered by web search tool (may include duplicates of those cited above):")
        for u in sources:
            section.append(f"- {u}")
    section.append("\n")

    section_text = "\n".join(section)

    # Simple de-dupe: if the exact block already exists, skip
    existing = ""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = f.read()

    if section_text in existing:
        return False

    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(section_text)

    return True


def git_commit_and_push_if_needed(commit_message: str):
    """
    Stage output file, commit if there are changes, push to origin.
    """
    # Stage
    run_cmd(["git", "add", OUTPUT_FILE], check=True)

    # Check if anything staged
    status = run_cmd(["git", "status", "--porcelain"], check=True)
    if not status.strip():
        print("No changes detected; nothing to commit.")
        return

    # Commit
    run_cmd(["git", "commit", "-m", commit_message], check=True)

    # Push
    branch = os.environ.get("GITHUB_BRANCH", "main").strip()
    run_cmd(["git", "push", "origin", branch], check=True)
    print(f"Pushed commit to {branch}.")


def main():
    # Basic env checks
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Missing env var OPENAI_API_KEY.")

    # 1) Fetch IPO updates via OpenAI web search
    text, sources = get_sg_ipo_updates_via_web_search()

    if not text:
        raise RuntimeError("OpenAI returned empty text. Check logs and try again.")

    # 2) Write to text file
    changed = append_results_to_file(text, sources)
    if not changed:
        print("Output block already exists; file unchanged.")
        return

    # 3) Configure git for pushing back to GitHub
    ensure_git_identity()
    configure_git_remote_with_token()

    # 4) Commit & push
    today = datetime.now(SG_TZ).strftime("%Y-%m-%d")
    msg = f"Update Singapore IPO watch – {today}"
    git_commit_and_push_if_needed(msg)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print("Command failed:", e)
        if e.stdout:
            print("STDOUT:\n", e.stdout)
        if e.stderr:
            print("STDERR:\n", e.stderr)
        sys.exit(1)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
