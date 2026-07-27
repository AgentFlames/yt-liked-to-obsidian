"""
YouTube Liked Videos (txt list) -> Obsidian Notes
--------------------------------------------------
Reads a list of YouTube video URLs from a text file (one per line, this is
what you exported via the browser console script), pulls each video's
metadata + transcript, uses a Groq-hosted LLM to (a) decide if it's
actually useful resource content vs "waffle" (dances, edits, memes, sports
clips, vlogs with no info), and (b) if useful, extracts
tools/websites/tags/summary into an Obsidian markdown note.

SETUP:
  pip install yt-dlp youtube-transcript-api openai

USAGE:
  1. Set GROQ_API_KEY below (or as env var).
  2. Set INPUT_FILE to your liked_videos.txt path.
  3. Set OUTPUT_DIR to a folder inside your Obsidian vault.
  4. Run: python yt_to_obsidian.py
"""

import os
import json
import time
import re
from pathlib import Path

from openai import OpenAI
from yt_dlp import YoutubeDL
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# ---------------- CONFIG ----------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "YOUR_API_KEY_HERE")
INPUT_FILE = Path("./liked_videos.txt")
OUTPUT_DIR = Path("./YT_Resources")   # this folder gets created, then drag it into your Obsidian vault
SKIPPED_LOG = Path("./skipped_videos.txt")
CACHE_FILE = Path("./yt_cache.json")
REQUEST_DELAY = 3.5  # spaced out a bit more to stay under Groq's tokens-per-minute cap, not just request count
DAILY_LIMIT = 950  # Groq free tier is ~1000 requests/day per model; keep a small buffer
USAGE_FILE = Path("./daily_usage.json")  # tracks how many requests made today
# Free Groq models, tried in order -- if one is unavailable/rate-limited,
# the script automatically falls back to the next one.
MODEL_CANDIDATES = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

# Tracks models that got rate-limited during this run, so we stop wasting
# calls retrying them every single video. Reset when the script restarts.
_dead_models = set()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_daily_usage():
    """Returns (date_str, count) for today's usage, resetting if it's a new day."""
    import datetime
    today = datetime.date.today().isoformat()
    if USAGE_FILE.exists():
        data = json.loads(USAGE_FILE.read_text())
        if data.get("date") == today:
            return today, data.get("count", 0)
    return today, 0


def save_daily_usage(today, count):
    USAGE_FILE.write_text(json.dumps({"date": today, "count": count}))






def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def extract_video_id(url):
    match = re.search(r"[?&]v=([^&]+)", url)
    return match.group(1) if match else None


def load_urls(path):
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen = set()
    videos = []
    for url in lines:
        vid = extract_video_id(url)
        if vid and vid not in seen:
            seen.add(vid)
            videos.append({"id": vid, "url": f"https://www.youtube.com/watch?v={vid}"})
    return videos


def get_video_meta(video_id):
    ydl_opts = {"quiet": True, "skip_download": True}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get("title", "Untitled"),
                "description": info.get("description", "") or "",
            }
    except Exception as e:
        return {"title": "Unknown", "description": "", "_error": str(e)}


def get_transcript(video_id):
    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join(seg["text"] for seg in segments)
    except (TranscriptsDisabled, NoTranscriptFound, Exception):
        return ""


def classify_and_extract(title, description, transcript):
    prompt = f"""You are organizing a personal knowledge base from YouTube videos
someone liked. Many of these are genuinely useful (tutorials, tool
recommendations, tips, how-tos, resource roundups) but many are just
entertainment with no real informational content (dances, memes, comedy
skits, sports highlights, music videos, pure vlogs/storytimes with no
actionable info, edits/montages).

Decide if this video is USEFUL (contains actionable info, tools, websites,
techniques, or resources worth saving to a knowledge base) or WAFFLE
(pure entertainment/no real info).

Return ONLY valid JSON, no markdown fences, no preamble, in this exact shape:

{{
  "keep": true or false,
  "summary": "1-2 sentence summary (only if keep=true, else empty string)",
  "tools_and_websites": ["tool or site name", "..."],
  "tags": ["generic-searchable-tag", "..."],
  "category": "broad category like 'productivity', 'ai-tools', 'fitness', 'finance', etc"
}}

Rules:
- If unsure/borderline, lean toward keep=true (better to over-include than lose something useful).
- tags: lowercase, generic search terms, 3-6 of them.
- tools_and_websites: ONLY actual named tools/apps/websites/products mentioned. Empty list if none.

TITLE: {title}
DESCRIPTION: {description[:500]}
TRANSCRIPT: {transcript[:3000]}
"""
    last_error = None
    live_models = [m for m in MODEL_CANDIDATES if m not in _dead_models]
    if not live_models:
        # every model already died earlier this run -- don't bother calling anything
        return {
            "keep": True,
            "summary": "[all models rate-limited for today -- review manually]",
            "tools_and_websites": [],
            "tags": ["needs-review"],
            "category": "uncategorized",
        }
    for model_name in live_models:
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            text = completion.choices[0].message.content.strip()
            # Strip markdown code fences if present
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            # Some models add commentary before/after the JSON -- pull out
            # just the {...} block so stray text doesn't break parsing.
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                text = match.group(0)
            if not text:
                raise ValueError("empty response from model")
            return json.loads(text)
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "429" in err_str or "rate" in err_str.lower():
                print(f"  {model_name} rate limited -- benching it for the rest of this run.")
                _dead_models.add(model_name)
                continue
            # model unavailable, not found, or other error -> try next model
            print(f"  {model_name} failed ({e}), trying next model...")
            continue
    # every model in the fallback list failed
    return {
        "keep": True,
        "summary": f"[auto-extraction failed after trying all models: {last_error} -- review manually]",
        "tools_and_websites": [],
        "tags": ["needs-review"],
        "category": "uncategorized",
    }


def safe_filename(title, video_id):
    clean = re.sub(r'[\\/*?:"<>|]', "", title)[:80].strip()
    return f"{clean} - {video_id}.md"


def write_note(video, title, extracted):
    tags_yaml = ", ".join(extracted["tags"])
    tools_list = "\n".join(f"- {t}" for t in extracted["tools_and_websites"]) or "- (none found)"

    content = f"""---
title: "{title}"
url: "{video['url']}"
category: {extracted['category']}
tags: [{tags_yaml}]
---

## Summary
{extracted['summary']}

## Tools/Resources mentioned
{tools_list}

## Link
{video['url']}
"""
    filepath = OUTPUT_DIR / safe_filename(title, video["id"])
    filepath.write_text(content, encoding="utf-8")


def log_skipped(title, url):
    with open(SKIPPED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{title} -- {url}\n")


def main():
    cache = load_cache()
    videos = load_urls(INPUT_FILE)
    print(f"Loaded {len(videos)} unique video URLs.")

    today, used_today = load_daily_usage()
    print(f"Used {used_today}/{DAILY_LIMIT} requests today so far.")

    kept, skipped = 0, 0

    for i, video in enumerate(videos):
        vid = video["id"]
        if vid in cache:
            continue

        if used_today >= DAILY_LIMIT:
            print(f"\nHit today's limit of {DAILY_LIMIT} requests. Stopping for now.")
            print("Just rerun this same script tomorrow -- it'll pick up right where it left off.")
            break

        meta = get_video_meta(vid)
        title = meta["title"]
        description = meta["description"]

        print(f"[{i+1}/{len(videos)}] ({used_today+1}/{DAILY_LIMIT} today) {title}")

        transcript = get_transcript(vid)
        result = classify_and_extract(title, description, transcript)

        if result.get("keep"):
            write_note(video, title, result)
            kept += 1
        else:
            log_skipped(title, video["url"])
            skipped += 1

        cache[vid] = True
        save_cache(cache)

        used_today += 1
        save_daily_usage(today, used_today)

        time.sleep(REQUEST_DELAY)

    remaining = len([v for v in videos if v["id"] not in cache])
    print(f"\nSession done. Kept: {kept}, Skipped as waffle: {skipped}")
    if remaining > 0:
        print(f"{remaining} videos still left to process -- rerun tomorrow to continue.")
    else:
        print("All videos processed!")
    print(f"Notes written to: {OUTPUT_DIR.resolve()}")
    print(f"Skipped log: {SKIPPED_LOG.resolve()}")


if __name__ == "__main__":
    main()
