"""
YouTube Comment Analyzer
Paste a YouTube link, pick a mode, and see what viewers are talking about.

Run:  py app.py   then open http://127.0.0.1:5000
The API key stays on the server (in the .env file) and is never sent to the browser.
"""
import os
import re
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()
API_KEY = os.environ.get("YOUTUBE_API_KEY")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Topic rules. Each topic is a keyword pattern. A comment can match several.
# ---------------------------------------------------------------------------
MODES = {
    "product": {
        "label": "Product review video",
        "topics": {
            "price": ("Price and value", r"price|pricey|expensive|overpriced|cost|cheap|afford|worth|discount|\$"),
            "durability": ("Durability and build", r"crease|durab|scratch|hinge|break|broke|crack|dust|water|fragile|sturdy"),
            "camera": ("Camera", r"camera|photo|zoom|telephoto|lens|selfie"),
            "battery": ("Battery and charging", r"battery|charg|power bank|screen on time"),
            "design": ("Design and size", r"design|thin|slim|wide|size|aspect ratio|weight|heavy|colou?r|form factor"),
            "performance": ("Performance and software", r"performance|\blag|snapdragon|exynos|processor|\bchip|software|one ui|\bupdate"),
            "trust": ("Trust (sponsored or fake doubts)", r"sponsor|paid|\bads?\b|shill|affiliate|fake|bias|promot"),
        },
    },
    "creator": {
        "label": "Creator feedback",
        "topics": {
            "requests": ("Content requests", r"please (make|do|review|show|cover)|can you (make|do|review|show|cover)|next video|make a video|would love to see|do a (video|review)|tutorial on"),
            "questions": ("Questions", r"\?"),
            "praise": ("Praise", r"love|great|amazing|awesome|best|thank|helpful|excellent|brilliant|well done|good job|underrated|favou?rite"),
            "complaints": ("Complaints", r"too long|boring|clickbait|annoying|waste|disappoint|hate|worst|misleading|stretched|rambl"),
            "av_quality": ("Audio, video and editing", r"audio|\bmic\b|microphone|volume|loud|music|sound|editing|resolution|blurry|subtitle|caption|\bcc\b"),
        },
    },
}

SPAM_RE = re.compile(
    r"https?://|www\.|subscribe to my|check (out )?my channel|sub4sub|giveaway|"
    r"whatsapp|telegram|dm me|contact me|crypto|bitcoin|promo ?code|click (the )?link",
    re.I,
)

VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")
CACHE_SECONDS = 600
_cache = {}


def video_id_from_url(url):
    match = VIDEO_ID_RE.search(url or "")
    return match.group(1) if match else None


def fetch_video(video_id, limit, order):
    """Get the video title, channel and up to `limit` top-level comments."""
    key = (video_id, limit, order)
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    youtube = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)
    meta = youtube.videos().list(part="snippet", id=video_id).execute()
    items = meta.get("items", [])
    if not items:
        raise LookupError("Video not found. Check the link.")
    title = items[0]["snippet"]["title"]
    channel = items[0]["snippet"]["channelTitle"]

    comments, token = [], None
    while len(comments) < limit:
        resp = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            order=order,
            textFormat="plainText",
            pageToken=token,
        ).execute()
        for item in resp.get("items", []):
            s = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": s.get("textDisplay", ""),
                "likes": s.get("likeCount", 0),
            })
        token = resp.get("nextPageToken")
        if not token:
            break

    data = {"title": title, "channel": channel, "comments": comments[:limit]}
    _cache[key] = (time.time(), data)
    return data


def analyze(comments, mode):
    """Count how many comments touch each topic and pick the most-liked examples."""
    topics_cfg = MODES[mode]["topics"]
    patterns = {t: re.compile(p, re.I) for t, (_, p) in topics_cfg.items()}

    clean = [c for c in comments if c["text"].strip()]
    spam = [c for c in clean if SPAM_RE.search(c["text"])]
    real = [c for c in clean if not SPAM_RE.search(c["text"])]
    n = len(real)

    topics = []
    for topic, rx in patterns.items():
        hits = [c for c in real if rx.search(c["text"])]
        hits.sort(key=lambda c: c["likes"], reverse=True)
        topics.append({
            "topic": topic,
            "label": topics_cfg[topic][0],
            "count": len(hits),
            "share": round(100 * len(hits) / n, 1) if n else 0.0,
            "top_comments": [{"text": c["text"][:300], "likes": c["likes"]} for c in hits[:3]],
        })
    topics.sort(key=lambda t: t["count"], reverse=True)

    return {
        "analyzed": n,
        "spam_removed": len(spam),
        "topics": topics,
        "summary": build_summary(topics, n, len(spam)),
    }


def build_summary(topics, n, spam_count):
    if n == 0:
        return "No readable comments were found for this video."
    top = [t for t in topics if t["count"] > 0][:2]
    if spam_count == 1:
        spam_note = " 1 spam-like comment was removed first."
    elif spam_count:
        spam_note = f" {spam_count} spam-like comments were removed first."
    else:
        spam_note = ""
    if not top:
        return f"None of the topic keywords matched in {n} comments.{spam_note}"
    parts = [f"{t['label'].lower()} ({t['share']}%)" for t in top]
    joined = " and ".join(parts)
    return f"Out of {n} comments, viewers talk most about {joined}.{spam_note}"


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/analyze")
def api_analyze():
    if not API_KEY:
        return jsonify(error="The server has no YOUTUBE_API_KEY. Add it to the .env file."), 500

    mode = request.args.get("mode", "product")
    if mode not in MODES:
        return jsonify(error="Unknown mode."), 400

    order = request.args.get("order", "relevance")
    if order not in ("time", "relevance"):
        order = "relevance"

    try:
        limit = int(request.args.get("limit", "300"))
    except ValueError:
        limit = 300
    limit = max(50, min(limit, 500))

    video_id = video_id_from_url(request.args.get("url", ""))
    if not video_id:
        return jsonify(error="That does not look like a YouTube video link."), 400

    try:
        video = fetch_video(video_id, limit, order)
    except LookupError as err:
        return jsonify(error=str(err)), 404
    except HttpError as err:
        text = str(err)
        if "commentsDisabled" in text:
            return jsonify(error="Comments are turned off on this video."), 400
        if "quotaExceeded" in text:
            return jsonify(error="The daily YouTube API quota is used up. Try again tomorrow."), 429
        return jsonify(error="YouTube refused the request. Check the link and the API key."), 502

    result = analyze(video["comments"], mode)
    result.update({
        "video_id": video_id,
        "title": video["title"],
        "channel": video["channel"],
        "mode": mode,
        "mode_label": MODES[mode]["label"],
        "fetched": len(video["comments"]),
    })
    return jsonify(result)


if __name__ == "__main__":
    print("Open http://127.0.0.1:5000 in your browser")
    app.run(host="127.0.0.1", port=5000, debug=False)
