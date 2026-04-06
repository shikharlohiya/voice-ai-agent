"""
Car Inquiry Backend — Auto-Call on Form Submit
Flask + SQLite + LiveKit dispatch
When customer submits form → save to DB → immediately trigger AI agent call
"""

import os
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

import json
import random
import asyncio
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
import sqlite3
from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")

app = Flask(__name__)
DB_FILE = "car_inquiries.db"
FORM_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("car-backend")

# LiveKit credentials from .env
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
SIP_TRUNK_ID = os.getenv("SIP_TRUNK_ID")

SELF_BASE_URL = os.getenv("CAR_BACKEND_URL", "http://localhost:5010")

# --- CAR CATEGORY PROMPTS ---
CAR_PROMPTS = {
    "New Car Inquiry": {
        "prompt": """आप एक car dealership executive हैं जो customer को नई कार के बारे में जानकारी दे रही हैं।
Language Rules:
- Default: Devanagari Hindi में जवाब दें। English words जैसे car model, EMI, showroom naturally mix करें।
- अगर customer English में बोले → पूरी conversation English में करें।

CALL FLOW — एक बार में एक सवाल पूछें:
1. Greet: "नमस्ते [Name] जी, मैं [Dealership] से बोल रही हूँ, आपने नई कार के बारे में inquiry की थी। मैं आपकी कैसे मदद कर सकती हूँ?"
2. "आप कौन सी कार में interested हैं? या कोई preference है जैसे hatchback, sedan, या SUV?"
3. "आपका budget range क्या है?"
4. "क्या आप cash purchase करना चाहते हैं या finance/loan लेना चाहते हैं?"
5. "आप कब तक कार लेने की सोच रहे हैं?"
6. Goodbye: "धन्यवाद [Name] जी, हमने आपकी details note कर ली हैं। हमारी team जल्द आपसे संपर्क करेगी। नमस्ते।" → use `end_call`

HOW TO BEHAVE:
- Ask ONE question at a time. NEVER summarize previous answers.
- Keep responses SHORT — "अच्छा", "ठीक है" then next question.
- If unclear answer → "ठीक है" and MOVE ON.
- If not interested → "धन्यवाद, नमस्ते।" → use `end_call`
- If busy → "कब call करें?" → use `end_call`
- NEVER say goodbye more than once.""",
        "greeting": "नई कार inquiry के बारे में call कर रहे हैं। हिंदी में 1 sentence में बात करें।"
    },
    "Test Drive": {
        "prompt": """आप एक car dealership executive हैं जो customer का test drive schedule कर रही हैं।
Language Rules:
- Default: Devanagari Hindi। English car model names naturally mix करें।
- अगर customer English में बोले → English में switch करें।

CALL FLOW — एक बार में एक सवाल:
1. Greet: "नमस्ते [Name] जी, मैं [Dealership] से बोल रही हूँ, आपने test drive के लिए inquiry की थी।"
2. "आप कौन सी कार का test drive लेना चाहते हैं?"
3. "आप कब आना चाहेंगे — weekday या weekend?"
4. "क्या आप showroom आ सकते हैं या home test drive चाहिए?"
5. Goodbye: "धन्यवाद [Name] जी, हमने आपकी test drive request note कर ली है। हमारी team जल्द confirm करेगी। नमस्ते।" → use `end_call`

HOW TO BEHAVE:
- ONE question at a time. SHORT responses.
- If not interested → "धन्यवाद, नमस्ते।" → use `end_call`
- NEVER say goodbye more than once.""",
        "greeting": "Test drive inquiry के बारे में call कर रहे हैं। हिंदी में 1 sentence में बात करें।"
    },
    "Car Service": {
        "prompt": """आप एक car service center executive हैं।
Language Rules:
- Default: Devanagari Hindi। Technical words naturally mix करें।
- अगर customer English में बोले → English में switch करें।

CALL FLOW — एक बार में एक सवाल:
1. Greet: "नमस्ते [Name] जी, मैं [Dealership] service center से बोल रही हूँ, आपने service के लिए inquiry की थी।"
2. "आपकी कार का model क्या है?"
3. "कार में क्या problem है या routine service चाहिए?"
4. "आप कब service के लिए आना चाहेंगे?"
5. Goodbye: "धन्यवाद [Name] जी, हमने आपकी service request note कर ली है। हमारी team जल्द appointment confirm करेगी। नमस्ते।" → use `end_call`

HOW TO BEHAVE:
- ONE question at a time. SHORT responses.
- If not interested → "धन्यवाद, नमस्ते।" → use `end_call`
- NEVER say goodbye more than once.""",
        "greeting": "Car service inquiry के बारे में call कर रहे हैं। हिंदी में 1 sentence में बात करें।"
    },
    "Finance": {
        "prompt": """आप एक car finance executive हैं।
Language Rules:
- Default: Devanagari Hindi। Finance terms naturally mix करें।
- अगर customer English में बोले → English में switch करें।

CALL FLOW — एक बार में एक सवाल:
1. Greet: "नमस्ते [Name] जी, मैं [Dealership] finance team से बोल रही हूँ, आपने car loan के बारे में inquiry की थी।"
2. "आप कितने amount का loan लेना चाहते हैं?"
3. "आप कितने साल में loan repay करना चाहते हैं?"
4. "क्या आप salaried हैं या self-employed?"
5. Goodbye: "धन्यवाद [Name] जी, हमने आपकी details note कर ली हैं। हमारी finance team जल्द आपसे संपर्क करेगी। नमस्ते।" → use `end_call`

HOW TO BEHAVE:
- ONE question at a time. SHORT responses.
- If not interested → "धन्यवाद, नमस्ते।" → use `end_call`
- NEVER say goodbye more than once.""",
        "greeting": "Car finance inquiry के बारे में call कर रहे हैं। हिंदी में 1 sentence में बात करें।"
    },
    "Exchange": {
        "prompt": """आप एक car exchange executive हैं।
Language Rules:
- Default: Devanagari Hindi। Exchange terms naturally mix करें।
- अगर customer English में बोले → English में switch करें।

CALL FLOW — एक बार में एक सवाल:
1. Greet: "नमस्ते [Name] जी, मैं [Dealership] से बोल रही हूँ, आपने car exchange के बारे में inquiry की थी।"
2. "आपकी current कार का model और year क्या है?"
3. "कार की current condition कैसी है? कोई major damage तो नहीं?"
4. "आप exchange में कौन सी नई कार लेना चाहेंगे?"
5. Goodbye: "धन्यवाद [Name] जी, हमने आपकी details note कर ली हैं। हमारी team जल्द आपसे संपर्क करेगी। नमस्ते।" → use `end_call`

HOW TO BEHAVE:
- ONE question at a time. SHORT responses.
- If not interested → "धन्यवाद, नमस्ते।" → use `end_call`
- NEVER say goodbye more than once.""",
        "greeting": "Car exchange inquiry के बारे में call कर रहे हैं। हिंदी में 1 sentence में बात करें।"
    },
}

DEFAULT_PROMPT = CAR_PROMPTS["New Car Inquiry"]


# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            city_name TEXT,
            state_name TEXT,
            category TEXT NOT NULL,
            message TEXT,
            ai_call_status TEXT DEFAULT 'not_called',
            ai_call_summary TEXT,
            ai_called_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Initialized.")


# ─── LIVEKIT DISPATCH ────────────────────────────────────────────────────────

async def dispatch_call_async(lead: dict):
    """Trigger LiveKit agent call immediately for the lead."""
    if not (LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        logger.error("[CALL] LiveKit credentials missing in .env")
        return

    phone = lead.get("phone", "")
    if not phone.startswith("+"):
        phone = f"+91{phone}"
    if phone.startswith("+910"):
        phone = "+91" + phone[4:]

    prompt_config = CAR_PROMPTS.get(lead.get("category", ""), DEFAULT_PROMPT)

    room_name = f"car-{lead['id']}-{random.randint(1000, 9999)}"

    metadata = {
        "phone_number": phone,
        "lead_id": lead["id"],
        "lead_name": lead.get("name", ""),
        "lead_category": lead.get("category", ""),
        "lead_message": lead.get("message", ""),
        "lead_city": lead.get("city_name", ""),
        "lead_state": lead.get("state_name", ""),
        "crm_update_url": f"{SELF_BASE_URL}/api/inquiry/{lead['id']}/call-update",
        "system_prompt": prompt_config["prompt"],
        "greeting": prompt_config["greeting"] + f" उन्हें {lead.get('name', '')} जी बोलकर संबोधित करें।",
    }

    lk_api = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)

    try:
        # Mark as calling
        conn = get_db()
        conn.execute("UPDATE inquiries SET ai_call_status='calling', ai_called_at=? WHERE id=?",
                     (datetime.now().isoformat(), lead["id"]))
        conn.commit()
        conn.close()

        dispatch_request = api.CreateAgentDispatchRequest(
            agent_name="outbound-caller",
            room=room_name,
            metadata=json.dumps(metadata)
        )
        dispatch = await lk_api.agent_dispatch.create_dispatch(dispatch_request)
        logger.info(f"[CALL DISPATCHED] Lead {lead['id']} ({lead['name']}) → {phone} | Room: {room_name} | Dispatch: {dispatch.id}")

    except Exception as e:
        logger.error(f"[CALL ERROR] Lead {lead['id']}: {e}")
        conn = get_db()
        conn.execute("UPDATE inquiries SET ai_call_status='failed' WHERE id=?", (lead["id"],))
        conn.commit()
        conn.close()

    finally:
        await lk_api.aclose()


def trigger_call(lead: dict):
    """Run async dispatch in a background thread (Flask is sync)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(dispatch_call_async(lead))
    loop.close()


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/")
def serve_form():
    return send_from_directory(FORM_DIR, "car_form.html")


@app.route("/customerinquirydata")
def serve_portal():
    return send_from_directory(FORM_DIR, "car_portal.html")


@app.route("/api/inquiry", methods=["POST"])
def submit_inquiry():
    """Customer submits form → save to DB → trigger call immediately."""
    data = request.json or request.form.to_dict()

    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()

    if not name or not phone:
        return jsonify({"success": False, "message": "नाम और मोबाइल नंबर जरूरी है।"}), 400

    if len(phone) != 10 or not phone.isdigit():
        return jsonify({"success": False, "message": "10 अंकों का सही मोबाइल नंबर दर्ज करें।"}), 400

    # Save to DB
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO inquiries (name, phone, email, city_name, state_name, category, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        name, phone,
        data.get("email", ""),
        data.get("city_name", ""),
        data.get("state_name", ""),
        data.get("category", "New Car Inquiry"),
        data.get("message", ""),
    ))
    conn.commit()
    new_id = cursor.lastrowid
    lead = dict(conn.execute("SELECT * FROM inquiries WHERE id=?", (new_id,)).fetchone())
    conn.close()

    logger.info(f"[NEW INQUIRY] ID={new_id} | {name} | {phone} | {data.get('category')}")

    # Trigger call immediately in background thread
    import threading
    t = threading.Thread(target=trigger_call, args=(lead,), daemon=True)
    t.start()

    return jsonify({"success": True, "message": "आपकी inquiry दर्ज हो गई! हम आपको अभी call कर रहे हैं। 📞"})


@app.route("/api/inquiry/<int:inquiry_id>/call-update", methods=["PUT"])
def update_inquiry(inquiry_id):
    """Agent updates call result after call ends."""
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE inquiries
        SET ai_call_status=?, ai_call_summary=?, ai_called_at=?
        WHERE id=?
    """, (
        data.get("ai_call_status", "called"),
        data.get("ai_call_summary", ""),
        datetime.now().isoformat(),
        inquiry_id,
    ))
    conn.commit()
    conn.close()
    logger.info(f"[UPDATED] ID={inquiry_id} | status={data.get('ai_call_status')}")
    return jsonify({"success": True, "message": "Updated."})


@app.route("/api/inquiries", methods=["GET"])
def list_all():
    """View all inquiries."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM inquiries ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify({"success": True, "data": [dict(r) for r in rows], "total": len(rows)})


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("=" * 55)
    print("  Car Inquiry Backend — Auto Call on Submit")
    print("  Form:      http://localhost:5010")
    print("  All leads: http://localhost:5010/api/inquiries")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5010, debug=False)
