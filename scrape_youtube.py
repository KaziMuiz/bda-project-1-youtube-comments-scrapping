"""
Scrape YouTube comments for Big Data Analytics Project 1.

Collects top-level comments from a list of videos using the YouTube Data API v3
and saves them to data/youtube_comments.csv (about 400 comments per video).

Setup (Colab):
  1. Add your API key in Colab: left sidebar -> Secrets -> name it YOUTUBE_API_KEY
     and turn on notebook access. Never paste the key into code you push to GitHub.
  2. Fill in VIDEOS below with 5 videos (url + category).
  3. Run the script / cell.
"""
import os
import re

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---- 1. API key (.env file locally, Colab secret, or environment variable) ----
try:
    from dotenv import load_dotenv
    load_dotenv()  # reads YOUTUBE_API_KEY from a .env file in the project folder
except ImportError:
    pass

try:
    from google.colab import userdata
    API_KEY = userdata.get("YOUTUBE_API_KEY")
except Exception:
    API_KEY = os.environ.get("YOUTUBE_API_KEY")

if not API_KEY:
    raise SystemExit("No API key found. Set YOUTUBE_API_KEY (Colab secret or env var).")

# ---- 2. Your videos: (url, category) ----
# Suggested: 3 product-review videos + 2 creator videos, about 400 comments each.
VIDEOS = [
    ("https://www.youtube.com/watch?v=Z6z_feacXW8", "full_review"),
    ("https://www.youtube.com/watch?v=8Hx2yvWSgs0", "to_confirm"),
    ("https://www.youtube.com/watch?v=HZOYCMkic0E", "durability_test"),
    ("https://www.youtube.com/watch?v=QHuIU2oE4Hg", "hands_on"),
    ("https://www.youtube.com/watch?v=Lgwa3Ze0tv4", "hands_on"),
]
PER_VIDEO = 400          # comments to collect per video
OUTPUT = "data/youtube_comments.csv"


def video_id_from_url(url):
    match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    if not match:
        raise ValueError(f"Could not find a video id in: {url}")
    return match.group(1)


def get_title(youtube, vid):
    resp = youtube.videos().list(part="snippet", id=vid).execute()
    items = resp.get("items", [])
    return items[0]["snippet"]["title"] if items else ""


def fetch_comments(youtube, vid, limit):
    """Most recent top-level comments (order='time'), up to `limit`."""
    rows, token = [], None
    while len(rows) < limit:
        resp = youtube.commentThreads().list(
            part="snippet",
            videoId=vid,
            maxResults=100,
            order="time",
            textFormat="plainText",
            pageToken=token,
        ).execute()
        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]
            s = top["snippet"]
            rows.append({
                "comment_id": top["id"],
                "text": s.get("textDisplay", ""),
                "likes": s.get("likeCount", 0),
                "reply_count": item["snippet"].get("totalReplyCount", 0),
                "published_at": s.get("publishedAt"),
            })
        token = resp.get("nextPageToken")
        if not token:
            break
    return rows[:limit]


def main():
    youtube = build("youtube", "v3", developerKey=API_KEY)
    all_rows = []
    for url, category in VIDEOS:
        vid = video_id_from_url(url)
        try:
            title = get_title(youtube, vid)
            rows = fetch_comments(youtube, vid, PER_VIDEO)
        except HttpError as err:
            print(f"Skipped {vid}: {err}")  # e.g. comments disabled on that video
            continue
        for r in rows:
            r.update({"video_id": vid, "video_title": title, "category": category})
        all_rows.extend(rows)
        print(f"{vid}: {len(rows)} comments | {title[:60]}")

    df = pd.DataFrame(all_rows).drop_duplicates(subset="comment_id")
    df = df[["video_id", "video_title", "category", "comment_id",
             "text", "likes", "reply_count", "published_at"]]
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    df.to_csv(OUTPUT, index=False)
    print("\nSaved", OUTPUT, "| shape:", df.shape)
    print(df.groupby("video_title").size())


if __name__ == "__main__":
    main()
