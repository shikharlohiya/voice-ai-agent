#!/usr/bin/env python3
"""
Real-time Hindi ↔ English Translation Bridge

Architecture:
- Operator Room  (op_room):   You speak Hindi  → bridge translates → customer hears English
- Customer Room  (cust_room): Customer speaks English → bridge translates → you hear Hindi

How it works:
1. car_backend creates two LiveKit rooms
2. Dials your phone (operator) into op_room via SIP
3. Dials customer phone into cust_room via SIP
4. This bridge connects to both rooms simultaneously
5. Translates audio in both directions in real time

Usage:
    python translation_bridge.py <op_room_name> <cust_room_name>
"""

import asyncio
import logging
import os
import sys

import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

from dotenv import load_dotenv
load_dotenv(".env")

import io
import aiohttp
import av as pyav
import numpy as np
from livekit import rtc
from livekit.api import AccessToken, VideoGrants
from livekit.agents import stt as lk_stt
from livekit.plugins import deepgram, openai as lk_openai  # noqa: F401
import config

# Deepgram TTS for fast English, Sarvam direct for Hindi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BRIDGE] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("translation-bridge")

LIVEKIT_URL       = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY   = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")


# ─── Token Helper ─────────────────────────────────────────────────────────────

def make_token(room_name: str, identity: str) -> str:
    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_grants(VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        ))
    )
    return token.to_jwt()


# ─── Translation via Groq ─────────────────────────────────────────────────────

async def translate_text(groq_client, text: str, from_lang: str, to_lang: str) -> str:
    resp = await groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a real-time phone interpreter.\n"
                    f"Your job: translate the input to {to_lang}.\n\n"
                    f"RULES:\n"
                    f"1. DETECT the actual language of the input first.\n"
                    f"2. If the input is ALREADY in {to_lang}, return it UNCHANGED.\n"
                    f"3. If the input is in {from_lang} (or any other language), translate it to {to_lang}.\n"
                    f"4. Translate LITERALLY. Same length, same tone. Do NOT add words.\n"
                    f"5. A single word stays a single word. A question stays a question.\n"
                    f"6. Return ONLY the translated text. No explanation, no quotes."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()


# ─── Direct Sarvam TTS (bypasses plugin decoder issue) ───────────────────────

async def sarvam_synthesize(text: str, http_session: aiohttp.ClientSession, lang_code: str = "hi-IN", sample_rate: int = 24000):
    """
    Call Sarvam TTS directly, decode MP3 → PCM, return list of rtc.AudioFrame.
    Bypasses the livekit plugin which has a mime_type mismatch on Windows.
    """
    payload = {
        "inputs": [text],
        "target_language_code": lang_code,
        "speaker": config.DEFAULT_TTS_VOICE,
        "model": config.SARVAM_MODEL,
        "speech_sample_rate": sample_rate,
        "enable_preprocessing": False,
        "output_audio_bitrate": 64000,
        "pace": 1.2,
    }
    headers = {
        "api-subscription-key": os.getenv("SARVAM_API_KEY"),
        "Content-Type": "application/json",
    }
    async with http_session.post(
        "https://api.sarvam.ai/text-to-speech",
        json=payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()

    import base64
    audio_b64 = data["audios"][0]
    mp3_bytes = base64.b64decode(audio_b64)

    # Decode MP3 → PCM frames using PyAV
    frames = []
    container = pyav.open(io.BytesIO(mp3_bytes))
    resampler = pyav.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    for packet in container.demux(container.streams.audio[0]):
        for frame in packet.decode():
            for rf in resampler.resample(frame):
                pcm = bytes(rf.planes[0])
                audio_frame = rtc.AudioFrame(
                    data=pcm,
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=len(pcm) // 2,
                )
                frames.append(audio_frame)
    container.close()
    return frames


# ─── One Direction of the Bridge ──────────────────────────────────────────────

async def run_direction(
    label: str,
    src_room: rtc.Room,
    dst_audio_source: rtc.AudioSource,
    stt_language: str,
    tts_engine,
    groq_client,
    from_lang: str,
    to_lang: str,
    http_session: aiohttp.ClientSession = None,
    use_sarvam: bool = False,
    sarvam_lang_code: str = "hi-IN",
    timeout_secs: int = 180,
):
    """
    Listen to audio in src_room, translate, push translated audio into dst_audio_source.

    :param label: e.g. "OP→CUST" or "CUST→OP" for log readability
    :param src_room: LiveKit Room to listen in
    :param dst_audio_source: AudioSource connected to a track published in the OTHER room
    :param stt_language: Deepgram language code ("hi" or "en")
    :param tts_engine: Sarvam (Hindi) or OpenAI (English) TTS
    :param groq_client: Groq async client
    :param from_lang / to_lang: "Hindi" / "English" (used in translation prompt)
    :param timeout_secs: how long to wait for the participant to join
    """
    logger.info(f"[{label}] Waiting for participant (timeout={timeout_secs}s)…")

    # ── Wait for a subscribed audio track ────────────────────────────────────
    track_ready   = asyncio.Event()
    audio_track_holder = {"track": None}

    def is_human_participant(identity: str) -> bool:
        """Only subscribe to SIP phone participants, NOT the bridge's own translated tracks."""
        return identity in ("operator", "customer") or identity.startswith("sip_")

    def on_track_subscribed(track, publication, participant):
        if (track.kind == rtc.TrackKind.KIND_AUDIO
                and audio_track_holder["track"] is None
                and is_human_participant(participant.identity)):
            logger.info(f"[{label}] Audio track subscribed from '{participant.identity}'")
            audio_track_holder["track"] = track
            track_ready.set()

    src_room.on("track_subscribed", on_track_subscribed)

    # Also pick up tracks that were already subscribed before we registered the handler
    for participant in src_room.remote_participants.values():
        if not is_human_participant(participant.identity):
            continue
        for pub in participant.track_publications.values():
            if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track:
                logger.info(f"[{label}] Using existing track from '{participant.identity}'")
                audio_track_holder["track"] = pub.track
                track_ready.set()
                break
        if track_ready.is_set():
            break

    try:
        await asyncio.wait_for(track_ready.wait(), timeout=timeout_secs)
    except asyncio.TimeoutError:
        logger.error(f"[{label}] No participant joined in {timeout_secs}s — giving up.")
        return

    audio_track = audio_track_holder["track"]
    logger.info(f"[{label}] Pipeline starting: STT({stt_language}) → Groq({from_lang}→{to_lang}) → TTS")

    # ── STT → Translate → TTS pipeline ───────────────────────────────────────
    # OP→CUST: detect_language=True so operator can mix Hindi+English naturally
    # CUST→OP: English only
    stt_plugin   = deepgram.STT(
        model="nova-3",
        language=stt_language,
        http_session=http_session,
    )
    audio_stream = rtc.AudioStream(audio_track, sample_rate=16000, num_channels=1)
    stt_stream   = stt_plugin.stream()

    # Deduplication: skip if same text seen within last 3 seconds
    last_text = {"text": "", "time": 0.0}

    async def push_audio():
        """Feed audio frames from the room into the STT stream."""
        async for frame_event in audio_stream:
            stt_stream.push_frame(frame_event.frame)
        logger.info(f"[{label}] Audio stream ended — closing STT stream.")
        await stt_stream.aclose()

    async def process_text():
        """Read STT transcripts, translate, and speak."""
        import time
        async for event in stt_stream:
            if event.type != lk_stt.SpeechEventType.FINAL_TRANSCRIPT:
                continue
            text = event.alternatives[0].text.strip() if event.alternatives else ""
            if not text:
                continue

            # Skip duplicate — same text within 3 seconds
            now = time.time()
            if text == last_text["text"] and (now - last_text["time"]) < 3.0:
                logger.info(f"[{label}] Skipping duplicate: {text}")
                continue
            last_text["text"] = text
            last_text["time"] = now

            # Skip very short noise like "Hmm", "Uh", single chars
            if len(text) < 2:
                continue

            logger.info(f"[{label}] {from_lang}: {text}")
            try:
                translated = await translate_text(groq_client, text, from_lang, to_lang)
                logger.info(f"[{label}] {to_lang}: {translated}")
                if not translated:
                    continue
                # Push translated TTS audio into the destination room
                if use_sarvam:
                    try:
                        frames = await sarvam_synthesize(translated, http_session, lang_code=sarvam_lang_code)
                        logger.info(f"[{label}] Sarvam TTS OK — {len(frames)} frames")
                        for frame in frames:
                            await dst_audio_source.capture_frame(frame)
                    except Exception as sarvam_err:
                        logger.error(f"[{label}] Sarvam TTS FAILED: {sarvam_err}")
                else:
                    async for audio in tts_engine.synthesize(translated):
                        await dst_audio_source.capture_frame(audio.frame)
            except Exception as exc:
                logger.error(f"[{label}] Translation/TTS error: {exc}")

    await asyncio.gather(push_audio(), process_text())
    logger.info(f"[{label}] Direction finished.")


# ─── Main Bridge ──────────────────────────────────────────────────────────────

# ─── Language Configuration ───────────────────────────────────────────────────
# Customer language → STT code, Sarvam TTS code, Groq language name, Deepgram TTS model
LANGUAGE_CONFIG = {
    "english": {"stt": "en",  "sarvam_tts": None,    "name": "English", "deepgram_tts": "aura-asteria-en"},
    "tamil":   {"stt": "ta",  "sarvam_tts": "ta-IN", "name": "Tamil",   "deepgram_tts": None},
    "telugu":  {"stt": "te",  "sarvam_tts": "te-IN", "name": "Telugu",  "deepgram_tts": None},
    "kannada": {"stt": "kn",  "sarvam_tts": "kn-IN", "name": "Kannada", "deepgram_tts": None},
    "bengali": {"stt": "bn",  "sarvam_tts": "bn-IN", "name": "Bengali", "deepgram_tts": None},
    "malayalam":{"stt": "ml", "sarvam_tts": "ml-IN", "name": "Malayalam","deepgram_tts": None},
    "marathi": {"stt": "mr",  "sarvam_tts": "mr-IN", "name": "Marathi", "deepgram_tts": None},
    "gujarati":{"stt": "gu",  "sarvam_tts": "gu-IN", "name": "Gujarati","deepgram_tts": None},
    "punjabi": {"stt": "pa",  "sarvam_tts": "pa-IN", "name": "Punjabi", "deepgram_tts": None},
    "odia":    {"stt": "or",  "sarvam_tts": "od-IN", "name": "Odia",    "deepgram_tts": None},
}


async def main(op_room_name: str, cust_room_name: str, cust_language: str = "english"):
    from groq import AsyncGroq
    groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

    # ── Resolve customer language config ──────────────────────────────────────
    lang_cfg = LANGUAGE_CONFIG.get(cust_language.lower(), LANGUAGE_CONFIG["english"])
    cust_stt_lang   = lang_cfg["stt"]
    cust_lang_name  = lang_cfg["name"]
    cust_sarvam_tts = lang_cfg["sarvam_tts"]
    cust_deepgram   = lang_cfg["deepgram_tts"]

    logger.info(f"Customer language: {cust_lang_name} (STT={cust_stt_lang}, TTS={'Sarvam' if cust_sarvam_tts else 'Deepgram'})")

    # ── Shared aiohttp session for all plugins ────────────────────────────────
    async with aiohttp.ClientSession() as http_session:

        # ── Connect to both rooms ─────────────────────────────────────────────
        op_room   = rtc.Room()
        cust_room = rtc.Room()

        logger.info(f"Connecting to rooms: op={op_room_name} | cust={cust_room_name}")
        await op_room.connect(LIVEKIT_URL,   make_token(op_room_name,   "translator"))
        await cust_room.connect(LIVEKIT_URL, make_token(cust_room_name, "translator"))
        logger.info("Connected to both rooms.")

        # ── Audio sources (output) ────────────────────────────────────────────
        cust_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        op_source   = rtc.AudioSource(sample_rate=24000, num_channels=1)

        cust_track = rtc.LocalAudioTrack.create_audio_track("translation-cust", cust_source)
        op_track   = rtc.LocalAudioTrack.create_audio_track("translation-op", op_source)

        await cust_room.local_participant.publish_track(
            cust_track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        await op_room.local_participant.publish_track(
            op_track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        logger.info("Output tracks published in both rooms.")

        # ── TTS engines ───────────────────────────────────────────────────────
        # OP→CUST: Customer hears their language
        #   - English → Deepgram (fast)
        #   - Indian languages → Sarvam (direct API)
        # CUST→OP: Operator always hears Hindi → Sarvam direct
        if cust_deepgram:
            cust_tts = deepgram.TTS(model=cust_deepgram, http_session=http_session)
            use_sarvam_for_cust = False
        else:
            cust_tts = None
            use_sarvam_for_cust = True

        logger.info(f"Translation bridge is LIVE ({cust_lang_name}). Waiting for both parties…")

        # ── Run both directions concurrently ──────────────────────────────────
        await asyncio.gather(
            run_direction(
                label="OP→CUST",
                src_room=op_room,
                dst_audio_source=cust_source,
                stt_language="hi",
                tts_engine=cust_tts,
                groq_client=groq_client,
                from_lang="Hindi",
                to_lang=cust_lang_name,
                http_session=http_session,
                use_sarvam=use_sarvam_for_cust,
                sarvam_lang_code=cust_sarvam_tts,
            ),
            run_direction(
                label="CUST→OP",
                src_room=cust_room,
                dst_audio_source=op_source,
                stt_language=cust_stt_lang,
                tts_engine=None,
                groq_client=groq_client,
                from_lang=cust_lang_name,
                to_lang="Hindi",
                http_session=http_session,
                use_sarvam=True,
                sarvam_lang_code="hi-IN",
            ),
        )

        logger.info("Both directions ended — disconnecting.")
        await op_room.disconnect()
        await cust_room.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python translation_bridge.py <op_room> <cust_room> [language]")
        print("Languages: english, tamil, telugu, kannada, bengali, malayalam, marathi, gujarati, punjabi, odia")
        sys.exit(1)

    cust_lang = sys.argv[3] if len(sys.argv) > 3 else "english"
    asyncio.run(main(sys.argv[1], sys.argv[2], cust_lang))
