#!/usr/bin/env python3
"""Non-interactive Cricbuzz service used by the WhatsApp cricket plugin."""
import argparse
import glob
import html
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from cricket_ffmpeg import (PRE_CLIP_SECONDS, SEGMENT_SECONDS, SEGMENT_WRAP,
                             buffer_command, concat_command, post_command)

BASE_URL = "https://www.cricbuzz.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Android 11) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36"}
TEAM_CODES = {"india": "IND", "sri lanka": "SL", "pakistan": "PAK", "australia": "AUS", "england": "ENG", "south africa": "SA", "new zealand": "NZ", "bangladesh": "BAN", "afghanistan": "AFG", "west indies": "WI", "ireland": "IRE", "zimbabwe": "ZIM"}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).replace("\xa0", " ")).strip()


def short_team(value):
    value = clean(value)
    return TEAM_CODES.get(value.lower(), value.upper() if re.fullmatch(r"[A-Za-z]{2,5}", value) else value)


def fetch(url):
    try:
        response = requests.get(url, headers=HEADERS, params={"_": time.time_ns()}, timeout=15)
        return response.text if response.status_code == 200 else ""
    except requests.RequestException:
        return ""


def title(soup):
    tag = soup.find("meta", attrs={"property": "og:title"})
    return clean(tag.get("content", "")) if tag else clean(soup.title.get_text(" ", strip=True) if soup.title else "")


def parse_match(raw):
    soup = BeautifulSoup(raw, "html.parser")
    page_title = re.sub(r"\s*(?:\||-)\s*Cricbuzz.*$", "", title(soup), flags=re.I)
    teams = re.search(r"(.+?)\s+(?:vs\.?|v\.?|versus)\s+(.+?)(?:,|\||$)", page_title, re.I)
    score_matches = list(re.finditer(r"\b(\d+)\s*(?:/|-)\s*(\d+)\s*\(\s*(\d+(?:\.\d+)?)\s*ov", clean(soup.get_text(" ", strip=True)), re.I))
    score = {"runs": score_matches[-1].group(1), "wickets": score_matches[-1].group(2), "overs": score_matches[-1].group(3)} if score_matches else {}
    commentary = []
    for node in soup.find_all(string=re.compile(r"^\s*\d{1,3}\.\d+\s*$")):
        ball = clean(node)
        parent = node.parent
        for _ in range(12):
            if parent is None:
                break
            text = clean(parent.get_text(" ", strip=True))
            if " to " in text and "," in text and len(text) < 300:
                commentary.append({"ball": ball, "text": re.sub(r"^\s*\d{1,3}\.\d+\s*", "", text)})
                break
            parent = parent.parent
    unique = []
    seen = set()
    for item in commentary:
        key = (item["ball"], item["text"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    latest = unique[-1] if unique else None
    status = "LIVE" if unique else next((clean(x) for x in re.findall(r"Tea Break|Lunch Break|Stumps|Innings Break|Match delayed|Match abandoned|Rain Delay|Drinks Break", clean(soup.get_text(" ", strip=True)), re.I)), "LIVE")
    return {"team1": short_team(teams.group(1)) if teams else "", "team2": short_team(teams.group(2)) if teams else "", "score": score, "status": status, "latest": latest, "signature": f"{latest['ball']}|{latest['text']}" if latest else f"{score.get('overs', '')}|{score.get('runs', '')}/{score.get('wickets', '')}"}


def print_card(data, footer=""):
    score = data["score"]
    lines = [f"🏏 *{data['team1']} vs {data['team2']}*" if data["team1"] and data["team2"] else "🏏 *Cricket Update*"]
    if score:
        lines.append(f"📌 *{score['runs']}/{score['wickets']} ({score['overs']} Ov)*")
    lines.append(f"⏱️ {clean(data['status'])}")
    if data.get("latest"):
        lines.append(f"💬 *{data['latest']['ball']}* {data['latest']['text']}")
    if footer:
        lines.append(f"\n{footer}")
    return "\n".join(lines)


def live_matches():
    soup = BeautifulSoup(fetch(BASE_URL + "/live-cricket-scores"), "html.parser")
    result, seen = [], set()
    for link in soup.find_all("a", href=True):
        match = re.search(r"/live-cricket-scores/(\d+)", link["href"])
        name = clean(link.get_text(" ", strip=True))
        if match and name and match.group(1) not in seen:
            seen.add(match.group(1)); result.append({"id": match.group(1), "name": name})
    return result


def record_clip(event, stream_url, buffer_dir, clips_dir):
    temp_dir = tempfile.mkdtemp(prefix="cricket_clip_")
    try:
        pre = sorted(glob.glob(os.path.join(buffer_dir, "seg_*.ts")), key=os.path.getmtime)[-max(1, PRE_CLIP_SECONDS // SEGMENT_SECONDS):]
        copied = []
        for index, source in enumerate(pre):
            dest = os.path.join(temp_dir, f"pre_{index:03d}.ts")
            try: shutil.copy2(source, dest); copied.append(dest)
            except OSError: pass
        post = os.path.join(temp_dir, "post.ts")
        subprocess.run(post_command(stream_url, post), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        listing = os.path.join(temp_dir, "list.txt")
        with open(listing, "w", encoding="utf-8") as handle:
            for item in copied + ([post] if os.path.exists(post) else []):
                handle.write(f"file '{os.path.abspath(item)}'\n")
        if not copied and not os.path.exists(post): return ""
        os.makedirs(clips_dir, exist_ok=True)
        output = os.path.join(clips_dir, f"{event}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        subprocess.run(concat_command(listing, output), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return output if os.path.exists(output) else ""
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def track(match_id, stream_url, clips_dir):
    buffer_dir = os.path.join(clips_dir, ".buffer")
    shutil.rmtree(buffer_dir, ignore_errors=True); os.makedirs(buffer_dir, exist_ok=True)
    buffer_proc = subprocess.Popen(buffer_command(stream_url, buffer_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    previous, last_signature, ball_count = {}, "", 0
    footer_ball = random.randint(1, 6)
    try:
        while True:
            raw = fetch(BASE_URL + "/live-cricket-scores/" + match_id)
            if raw:
                data = parse_match(raw)
                if data["signature"] and data["signature"] != last_signature:
                    ball_count += 1
                    current = data.get("score", {})
                    event = ""
                    try:
                        if int(current.get("wickets", 0)) > int(previous.get("wickets", 0)): event = "WICKET"
                        elif int(current.get("runs", 0)) - int(previous.get("runs", 0)) == 6: event = "SIX"
                        elif int(current.get("runs", 0)) - int(previous.get("runs", 0)) == 4: event = "FOUR"
                    except (TypeError, ValueError): pass
                    footer = os.environ.get("CRICKET_FOOTER", "© Powered By Qasim Cricket Bot - 03434571953") if ball_count % 6 == footer_ball else ""
                    clip = record_clip(event, stream_url, buffer_dir, clips_dir) if event else ""
                    print(json.dumps({"type": "update", "text": print_card(data, footer), "event": event, "clip": clip}), flush=True)
                    previous, last_signature = current, data["signature"]
                    if ball_count % 6 == 0: footer_ball = random.randint(1, 6)
            time.sleep(1)
    finally:
        buffer_proc.terminate(); shutil.rmtree(buffer_dir, ignore_errors=True)


parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true")
parser.add_argument("--score")
parser.add_argument("--track")
parser.add_argument("--stream")
parser.add_argument("--clips-dir", default="clips")
args = parser.parse_args()
if args.live: print(json.dumps({"type": "matches", "matches": live_matches()}))
elif args.score: print(json.dumps({"type": "update", "text": print_card(parse_match(fetch(BASE_URL + "/live-cricket-scores/" + args.score)))}))
elif args.track and args.stream: track(args.track, args.stream, args.clips_dir)
