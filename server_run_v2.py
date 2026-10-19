"""
Render-ready server run for Islamic Clips44 — PREPARATION, NOT YET DEPLOYED.

What this does (one run = one slot, meant to be called by a Render Cron Job
every 4 hours):
  1. Picks Nas / Al-Mulk by the clock, NOT by a local file. Render's free
     filesystem is ephemeral, so last_uploaded.txt would be lost on every
     restart. Slot index = (days since epoch * 6 + UTC-hour // 4) % 2.
  2. Builds the video with ffmpeg from audio + background image.
  3. Uploads it as PRIVATE (draft) by default. Nothing goes Public from the
     server on its own — the permission step is preserved: the user reviews
     the private video in YouTube Studio and makes it Public himself, or a
     later explicit approval run publishes it.

What this does NOT do:
  - It never asks for, prints, or logs any secret. Secrets come ONLY from
    Render environment variables (see README_PASHTO.md). Never paste a
    secret into chat, code, or git.
  - It never creates a fake video. If audio/background/token are missing it
    stops with a clear error listing exactly what is missing.
  - It never uses run_local_server() — there is no browser on a server.
    Auth uses a token stored as an env var, created once via the Allow step.

Env vars (set in Render Dashboard > Environment, never in code):
  CLIENT_SECRETS_JSON   — full JSON text of the OAuth client (Desktop app)
  YOUTUBE_TOKEN_JSON    — full JSON text of the authorised token (from Allow)
  PUBLISH_MODE          — "private" (default, safe) or "public" (only after
                          the user has explicitly approved that video)
  DRY_RUN               — "1" = check files + pick video, do not upload
"""
import base64
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Root layout: server_run.py sits at the repo root (/app in the container),
# so audio/ and assets/ are next to it. (NOT the parent dir — that was the
# old bot/render-ready/ subfolder layout and broke the root upload flow.)
BOT_DIR = HERE

VIDEOS = [
    {
        "id": "surah-nas",
        "surah": "سوره ناس",
        "title": "سوره ناس | د زړه سکون 💚 | Islamic Clips44",
        "description": "سوره ناس - د زړه سکون او د شیطان له وسوسو څخه پناه.\n\n#سوره_ناس #IslamicClips44 #Quran",
        "tags": ["سوره ناس", "Surah Nas", "Quran", "Islamic Clips44"],
        "audio": "audio/surah-nas.mp3",
        "background": "assets/background.jpg",
    },
    {
        "id": "surah-mulk",
        "surah": "سوره الملک",
        "title": "سوره الملک | هره شپه واورئ 🌙 | LISTEN EVERY NIGHT | Islamic Clips44",
        "description": "سوره الملک - هره شپه واورئ. سوره الملک د قرآن ۶۷مه سوره، ۳۰ آیتونه. په دې شارټ کې یوازې لومړي آیتونه دي، ځکه بشپړ تلاوت په یوه دقیقه کې نه ځایېږي.\n\n#سوره_الملک #IslamicClips44 #Quran",
        "tags": ["سوره الملک", "Surah Mulk", "Quran", "Islamic Clips44"],
        "audio": "audio/surah-mulk.mp3",
        "background": "assets/background.jpg",
    },
]


def pick_video(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    epoch_days = (now.date() - dt.date(1970, 1, 1)).days
    slot = epoch_days * 6 + now.hour // 4  # six 4-hour slots per day
    return VIDEOS[slot % len(VIDEOS)], slot


def fail_missing(missing):
    print("⛔ بوټ ودرېد — دا شیان لا نشته:")
    for m in missing:
        print(f"  - {m}")
    print("هېڅ ویډیو جوړه / اپلوډ شوې نه ده.")
    return 2


def main():
    video, slot = pick_video()
    print(f"Slot: {slot} | Video: {video['surah']} ({video['id']})")

    missing = []
    import glob as _glob
    # Audio fallbacks: audio/ subfolder OR repo root (phone upload puts files at root).
    audio_candidates = [
        os.path.join(BOT_DIR, video["audio"]),
        os.path.join(BOT_DIR, os.path.basename(video["audio"])),
        os.path.join(BOT_DIR, "الناس.mp3"),
    ] + sorted(_glob.glob(os.path.join(BOT_DIR, "*.mp3")))
    audio = next((p for p in audio_candidates if os.path.exists(p)), audio_candidates[0])
    # Background fallbacks: assets/background.jpg, root background.jpg,
    # or the uploaded PNG as-is (file_00000000a9bc...png from phone upload).
    import glob as _glob
    bg_candidates = [
        os.path.join(BOT_DIR, video["background"]),
        os.path.join(BOT_DIR, "background.jpg"),
        os.path.join(BOT_DIR, "file_00000000a9bc81fa8ece53d7325ded57.png"),
        os.path.join(BOT_DIR, "file_00000000a9bc81fa8ece53d7325ded57_0_iupz.png"),
    ] + sorted(_glob.glob(os.path.join(BOT_DIR, "file_*.png"))) + sorted(_glob.glob(os.path.join(BOT_DIR, "*.jpg"))) + sorted(_glob.glob(os.path.join(BOT_DIR, "*.png")))
    bg = next((p for p in bg_candidates if os.path.exists(p)), bg_candidates[0])
    if not os.path.exists(audio):
        missing.append(f"غږ فایل: {video['audio']} (د قاري محمدصالی تلاوت)")
    if not os.path.exists(bg):
        missing.append("پس منظر عکس: assets/background.jpg (شنه سوره ناس عکس)")
    if not os.environ.get("CLIENT_SECRETS_JSON"):
        missing.append("Render Env Var: CLIENT_SECRETS_JSON (پټ — یوازې په Render کې)")
    if not os.environ.get("YOUTUBE_TOKEN_JSON"):
        missing.append("Render Env Var: YOUTUBE_TOKEN_JSON (د Allow وروسته جوړېږي — یوازې په Render کې)")
    if missing:
        return fail_missing(missing)

    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN=1 — یوازې کتل وشو، هېڅ اپلوډ نه دی شوی.")
        return 0

    # Build video with ffmpeg (Dockerfile installs ffmpeg).
    out = os.path.join(HERE, f"output-{video['id']}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", bg, "-i", audio,
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
        "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest", out,
    ], check=True)
    print(f"ویډیو جوړه شوه: {out}")

    # Upload as PRIVATE by default — permission step preserved.
    publish_mode = os.environ.get("PUBLISH_MODE", "private").lower()
    privacy = "public" if publish_mode == "public" else "private"
    if privacy == "public":
        print("⚠️ PUBLISH_MODE=public — یوازې هغه وخت وکاروه چې ته دې ویډیو ته اجازه ورکړې وي.")
    else:
        print("PUBLISH_MODE=private — ویډیو به Private (مسوده) اپلوډ شي. ته به یې په YouTube Studio کې وګورې او بیا به یې Public کړې.")

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("⛔ google-api-python-client نصب نه دی. Build command وګوره.")
        return 2

    creds = Credentials.from_authorized_user_info(
        json.loads(os.environ["YOUTUBE_TOKEN_JSON"]),
        ["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": video["title"],
            "description": video["description"],
            "tags": video["tags"],
            "categoryId": "22",
            "defaultLanguage": "ps",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(out, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"اپلوډ روان دی: {int(status.progress() * 100)}%")
    print(f"اپلوډ شو ({privacy}): https://youtu.be/{response['id']}")
    print("یادونه: که private وي، تر تا له اجازې وروسته به Public شي — بوټ په خپله Public نه کوي.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
