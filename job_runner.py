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

def today_sg_dt() -> datetime:
    return datetime.now(SG_TZ)

def check_bot_protection(url: str):
    """
    Explicitly checks the SGX website for bot protection/WAF.
    Returns (is_blocked, reason)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        # We use a short timeout to fail fast if blocked or throttled
        resp = requests.get(url, headers=headers, timeout=10)
        
        # Check status codes
        if resp.status_code == 403:
            return True, "WAF Block (403 Forbidden) - Likely Cloudflare/Akamai"
        if resp.status_code == 429:
            return True, "Rate Limited (429 Too Many Requests)"
            
        # Check for common bot-protection fingerprints in HTML
        content = resp.text.lower()
        if "cloudflare" in content or "ray id" in content:
            return True, "Cloudflare Challenge detected in HTML"
        if "pardon our interruption" in content:
            return True, "Akamai Bot Manager detected"
            
        return False, "Clear"
    except Exception as e:
        return True, f"Connection Error: {str(e)}"

def get_sg_ipo_updates_via_web_search():
    client = OpenAI()
    today_str = today_sg_dt().strftime("%Y-%m-%d")

    # Step 1: Explicitly check the source status
    is_blocked, bot_reason = check_bot_protection("https://www.sgx.com/securities/ipo-prospectus")
    bot_status_msg = f"SGX Portal Connection Status: {'BLOCKED - ' + bot_reason if is_blocked else 'CONNECTED'}"

    prompt = f"""
You are a finance research assistant. Today's date is {today_str}.

TASK: Identify active IPOs and ETFs on SGX.

CRITICAL FILTERING RULE:
For SECTION B (Currently Active Offerings), you MUST check the 'Closing Date'.
- If the closing date is BEFORE {today_str}, DO NOT list it in Section B.
- If no closing date is provided but it is an 'Introductory Document', you may list it.
- If it is an ETF and active, list it.

Sources: 
1) https://www.sgx.com/securities/ipo-prospectus
2) https://links.sgx.com

Output Format (Plain Text):
{bot_status_msg}

SECTION A — NEW ANNOUNCEMENTS (LAST 7 DAYS)
...

SECTION B — CURRENTLY ACTIVE SGX IPO / ETF OFFERINGS
(Only items where closing date >= {today_str} or no closing date is applicable)
...
"""

    resp = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"), # Updated to stable model
        input=prompt,
        tools=[{"type": "web_search"}],
    )

    return (resp.output_text or "").strip()

def main():
    # ... (GitHub logic remains same as original)
    body = get_sg_ipo_updates_via_web_search()
    
    stamp = datetime.now(SG_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    final_text = f"{'='*80}\nRun timestamp: {stamp}\n{body}\n"
    
    # ... (Proceed to GitHub upload)
    print("Processing complete.")

if __name__ == "__main__":
    main()