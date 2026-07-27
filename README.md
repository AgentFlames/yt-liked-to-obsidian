# yt-liked-to-obsidian

Turns your YouTube liked videos into a searchable Obsidian knowledge base — filtering out junk and pulling out any tools/websites mentioned.

<img width="2776" height="1510" alt="Example note in Obsidian" src="https://github.com/user-attachments/assets/63ed9d57-ac24-4fd9-b9d7-5e726f3d14a6" />

## Problem / Motivation

I had 1000+ liked videos on YouTube — everything from short-form content (YT Shorts) to full videos. If I wanted to find that ONE tool or website mentioned in some video (e.g. something that makes Claude smarter), there was no way to search for it. This script fixes that by turning your liked videos into searchable Obsidian notes.

## How it works

1. Export your liked video URLs (via a browser console script, since the Liked Videos playlist can't easily be exported directly)
2. The script pulls each video's title, description, and transcript
3. Sends it to a free LLM (Groq) to classify it as useful vs waffle, and extract tools/tags/summary
4. Writes one `.md` note per useful video, with YAML frontmatter that Obsidian reads as Properties
5. Drag the output folder into your vault

## Setup

### 1. Export your liked video URLs

Open your YouTube Liked Videos playlist:

<img width="2776" height="1510" alt="YouTube liked videos playlist" src="https://github.com/user-attachments/assets/88032fd7-ade2-4b40-b73f-2ca4b0958ded" />

Scroll all the way down until every video has loaded. Then open your browser's console (right-click → Inspect → Console tab) and paste this in:

```javascript
let links = [...document.querySelectorAll('a')]
  .map(a => a.href)
  .filter(href => href.includes('/watch?v='));
let unique = [...new Set(links)];
console.log(unique.length);

let blob = new Blob([unique.join('\n')], {type: 'text/plain'});
let link = document.createElement('a');
link.href = URL.createObjectURL(blob);
link.download = 'liked_videos.txt';
link.click();
```

This downloads a `liked_videos.txt` file containing every video URL on the page.

### 2. Set up your project folder

Make a folder containing:
- the `liked_videos.txt` file you just downloaded
- the `yt_to_obsidian.py` script from this repo

You'll need Python installed, along with a code editor (VS Code, PyCharm, etc. — not a browser-based one).

### 3. Install dependencies

**macOS / Linux:**
```bash
pip3 install yt-dlp youtube-transcript-api openai
```

**Windows:**
```bash
pip install yt-dlp youtube-transcript-api openai
```

### 4. Get a free Groq API key

Sign up at [console.groq.com](https://console.groq.com) (no credit card required) and create an API key.

### 5. Configure the script

Open `yt_to_obsidian.py` and set:
- `GROQ_API_KEY` — paste your key
- `INPUT_FILE` — path to your `liked_videos.txt`
- `OUTPUT_DIR` — where notes get written (defaults to `./YT_Resources`)

## Usage

```bash
python3 yt_to_obsidian.py
```

<img width="2162" height="764" alt="image" src="https://github.com/user-attachments/assets/f3e74166-f649-4963-a8b4-ef26859b0729" />

The script:
- Processes videos one at a time, classifying each as useful or waffle
- Writes useful ones as `.md` notes with tags/tools/summary in the frontmatter
- Logs skipped "waffle" videos to `skipped_videos.txt` for review
- Is fully resumable — safe to stop (Ctrl+C) and rerun anytime; it picks up where it left off
- Respects Groq's free-tier daily limit automatically, stopping cleanly and resuming the next run

## Example output

```markdown
---
title: "Example Video Title"
url: "https://www.youtube.com/watch?v=xxxxxxxxxxx"
category: productivity
tags: [ai-tools, note-taking, chrome-extension]
---

## Summary
A 1-2 sentence summary of what the video covers.

## Tools/Resources mentioned
- Tool Name
- Another Tool

## Link
https://www.youtube.com/watch?v=xxxxxxxxxxx
```

Once generated, drag the `YT_Resources` folder into your Obsidian vault. Every note's tags, category, and title show up in Obsidian's Properties panel and are fully searchable.



## Known limitations

- Free-tier rate limits mean large libraries (1000+ videos) may take multiple runs across a few days
- Waffle-filtering is an LLM judgment call, not perfect — some useful videos might get filtered out, and some junk might slip through
- Shorts without captions/transcripts are classified using title + description only

## License

MIT
