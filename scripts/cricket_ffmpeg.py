#!/usr/bin/env python3
"""Editable FFmpeg commands for the cricket clip recorder.

Keep this file deliberately small: operators can tune FFmpeg flags here
without changing the WhatsApp command/plugin layer.
"""

import os

PRE_CLIP_SECONDS = int(os.environ.get("CRICKET_PRE_CLIP_SECONDS", "10"))
POST_CLIP_SECONDS = int(os.environ.get("CRICKET_POST_CLIP_SECONDS", "25"))
SEGMENT_SECONDS = int(os.environ.get("CRICKET_SEGMENT_SECONDS", "2"))
SEGMENT_WRAP = int(os.environ.get("CRICKET_SEGMENT_WRAP", "15"))


def buffer_command(stream_url, buffer_dir):
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", stream_url,
        "-c", "copy", "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-segment_wrap", str(SEGMENT_WRAP), "-reset_timestamps", "1", "-y",
        os.path.join(buffer_dir, "seg_%03d.ts")
    ]


def post_command(stream_url, output_file):
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", stream_url,
        "-t", str(POST_CLIP_SECONDS), "-c", "copy", "-y", output_file
    ]


def concat_command(list_file, output_file):
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "concat",
        "-safe", "0", "-i", list_file, "-c", "copy", "-y", output_file
    ]
