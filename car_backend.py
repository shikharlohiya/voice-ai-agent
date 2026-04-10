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

# Operator phone number — receives the call in Live Translation mode
OPERATOR_NUMBER = os.getenv("OPERATOR_NUMBER", "+918839699199")

# --- CAR AGENT PROMPT (Hindi) ---
CAR_AGENT_PROMPT = """आप प्रिया हैं, AutoDesk Motors की एक professional car sales executive। आप एक customer को call कर रही हैं जिसने website पर car inquiry submit की है।

LANGUAGE RULES:
- Default: Devanagari Hindi में बोलें। Car model, EMI, showroom, test drive जैसे English words naturally mix करें।
- अगर customer English में बोले → तुरंत पूरी conversation English में switch करें।
- ALWAYS respond in Devanagari Hindi script जब तक customer English न बोले।
- Customer का नाम हमेशा सही use करें: {{lead_name}} जी। कभी गलत नाम न लें।

LEAD DETAILS:
- Customer का नाम: {{lead_name}}
- Interested Car Model: {{car_model}}
- Fuel Type: {{fuel_type}}
- Budget: {{budget}}
- Buying Timeline: {{timeline}}
- Test Drive चाहिए: {{test_drive}}

CALL FLOW — एक बार में सिर्फ एक सवाल, natural और friendly tone:

STEP 1 — AVAILABILITY CHECK:
Greet: "नमस्ते, क्या मैं {{lead_name}} जी से बात कर रही हूँ? मैं प्रिया बोल रही हूँ AutoDesk Motors से। आपने हमारी website पर {{car_model}} कार के बारे में inquiry की थी — क्या अभी बात करने का सही समय है?"
- अगर busy → "कोई बात नहीं, कब call करें?" → time note करें → "ठीक है, हमारी team उस समय call करेगी। नमस्ते!" → use `end_call`
- अगर हाँ / OK → Step 2 पर जाएं

STEP 2 — INTEREST CONFIRM:
"तो आप {{car_model}} कार लेना चाहते हैं, सही है?"
- अगर हाँ → Step 3 पर जाएं
- अगर customer confused है ("कौन सी car?", "क्या?") → "जी, आपने हमारी website पर {{car_model}} कार के लिए inquiry भेजी थी। क्या आप अभी भी इसी कार में interested हैं?"
- अगर model change हो गया → "जी बताइए, अभी कौन सी car देख रहे हैं?" → note करें → Step 3 पर जाएं
- अगर customer says "हाँ वही" / "जो inquiry थी वही" → confirm करें और Step 3 पर जाएं
- Step 2 पर maximum 2 attempts। अगर फिर भी unclear → "ठीक है जी।" → Step 3 पर जाएं

STEP 3 — USE CASE:
"बढ़िया! यह car mainly किस काम के लिए लेंगे — daily commute, family use, या कोई और purpose?"

STEP 4 — FIRST CAR या UPGRADE:
"अच्छा। यह आपकी पहली car होगी या पुरानी car upgrade कर रहे हैं?"
- अगर upgrade → "अभी कौन सी car use कर रहे हैं?" → answer मिलने पर Step 5

STEP 5 — BUDGET CONFIRM:
"आपका budget {{budget}} के around है, सही है?"
- अगर changed → "अच्छा, नया budget कितना है?" → note करें

STEP 6 — BUYING TIMELINE:
"और purchase कब तक करने का plan है? आपने {{timeline}} mention किया था।"
- अगर "just exploring" / "सोच रहे हैं" → warm रहें, pressure न दें, आगे बढ़ें

STEP 7 — TEST DRIVE (सिर्फ तब जब test_drive = "Yes"):
"क्या {{car_model}} कार का test drive book करना चाहेंगे?"
- अगर हाँ →
  "कौन सा दिन convenient रहेगा?"
  → Day मिलने पर: "सुबह ठीक रहेगा या शाम?"
  → Time मिलने पर: "Showroom पर आएंगे या घर पर test drive चाहिए?"
- अगर नहीं → Step 8

STEP 8 — GOODBYE:
"बहुत बढ़िया {{lead_name}} जी! हमने आपकी details note कर ली हैं। हमारे specialist जल्द ही आपसे best offers के साथ संपर्क करेंगे। नमस्ते!"
→ use `end_call`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EDGE CASES — हर situation handle करें:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IDENTITY:
- "आप कौन हैं?" / "Who are you?" → "जी मैं प्रिया बोल रही हूँ AutoDesk Motors से, आपकी {{car_model}} कार inquiry के बारे में।" → continue
- "AutoDesk Motors क्या है?" → "जी हम एक authorized car dealership हैं। आपकी inquiry हमारे पास आई थी।" → continue

INQUIRY DENIAL:
- "मैंने inquiry नहीं की" → "माफ़ करिए {{lead_name}} जी, शायद कोई गड़बड़ी हुई होगी। आपका दिन शुभ हो! नमस्ते।" → use `end_call`
- "Wrong number" → "माफ़ करिए, गलती हुई। नमस्ते!" → use `end_call`

PRICE / EMI / FEATURES:
- "Price क्या है?" / "EMI कितनी होगी?" / "Features क्या हैं?" → "जी बिल्कुल, हमारे specialist आपको {{car_model}} की complete price list और EMI details देंगे। पहले बस कुछ जानकारी note कर लेती हूँ।" → current question पर वापस आएं

DIFFERENT CAR:
- Customer different car mention करे → "अच्छा, [new car] भी बढ़िया option है। मैं यह note कर लेती हूँ।" → continue flow

SHOWROOM VISIT:
- "Showroom कहाँ है?" → "हमारे specialist call पर आपको address और timing बताएंगे।" → continue
- "मैं showroom आना चाहता हूँ" → "बिल्कुल, हमारी team आपको visit के लिए coordinate करेगी।" → continue

LOAN / FINANCE:
- "Loan मिलेगा?" / "Finance available है?" → "जी बिल्कुल, हम सभी major banks के साथ काम करते हैं। Details specialist share करेंगे।" → continue

DISCOUNT / OFFER:
- "Discount मिलेगा?" → "जी हमारे पास कुछ special offers चल रहे हैं। Specialist आपको best deal देंगे।" → continue

CONFUSION / REPEATED QUESTIONS:
- अगर customer 2 बार same question पूछे या confused हो → clearly और simply answer करें, फिर next question पर move करें
- अगर एक question पर 2 से ज़्यादा attempts हो जाएं → "ठीक है जी।" और आगे बढ़ें। Same question पर stuck न रहें।

NOT INTERESTED:
- "मुझे नहीं चाहिए" / "Not interested" → "समझ गए जी। आपका समय देने के लिए धन्यवाद। नमस्ते!" → use `end_call`

RUDE CUSTOMER:
- Customer rude हो या गाली दे → "समझ गए जी। आपका दिन शुभ हो। नमस्ते!" → use `end_call`

CALL BACK LATER:
- "बाद में call करो" → "कब call करें आपको?" → time note करें → "ठीक है, हमारी team उस समय call करेगी। नमस्ते!" → use `end_call`

GENERAL QUESTIONS (off-topic):
- Insurance, RTO, road tax, etc. → "यह सब details हमारे specialist आपको properly explain करेंगे।" → continue

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NATURAL BEHAVIOR RULES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- एक बार में सिर्फ एक सवाल। दो सवाल एक साथ कभी नहीं।
- Transitions बहुत SHORT: "अच्छा।" / "ठीक है।" / "बढ़िया।" फिर अगला सवाल।
- Customer का जवाब कभी repeat या summarize न करें।
  BAD: "तो आप Swift चाहते हैं, petrol में, 8 लाख budget..." ← कभी नहीं।
  GOOD: Customer answers → "अच्छा।" → next question.
- Vague answer ("पता नहीं", "देखते हैं") → "ठीक है।" → move on।
- Customer का नाम हमेशा {{lead_name}} जी। कभी wrong नाम use न करें।
- Price, EMI, delivery date खुद कभी न बताएं।
- Goodbye सिर्फ एक बार। बोला → तुरंत `end_call`।
- 3-4 questions के बाद भी disengaged लगे → wrap up करें → `end_call`।
- NEVER use `lookup_user` tool। यह car calls के लिए नहीं है।
- अगर customer पूछे "कौन सा दिन available है?" / "आप बताओ कब आएं" → "जी हमारे showroom में weekdays और weekends दोनों available हैं। आपके लिए कौन सा दिन convenient रहेगा?"
- कभी भी fake schedule, fake dates, या fake availability मत बताओ। हमेशा customer से ही दिन पूछो।"""

CAR_PROMPTS = {
    "New Car Inquiry": {"prompt": CAR_AGENT_PROMPT, "greeting": "नई car inquiry का follow-up call है। हिंदी में 1 natural sentence में बात करें।"},
    "Test Drive":      {"prompt": CAR_AGENT_PROMPT, "greeting": "Test drive booking call है। हिंदी में 1 natural sentence में बात करें।"},
    "Car Service":     {"prompt": CAR_AGENT_PROMPT, "greeting": "Car service inquiry call है। हिंदी में 1 natural sentence में बात करें।"},
    "Finance":         {"prompt": CAR_AGENT_PROMPT, "greeting": "Car finance inquiry call है। हिंदी में 1 natural sentence में बात करें।"},
    "Exchange":        {"prompt": CAR_AGENT_PROMPT, "greeting": "Car exchange inquiry call है। हिंदी में 1 natural sentence में बात करें।"},
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
            car_model TEXT,
            fuel_type TEXT,
            budget TEXT,
            timeline TEXT,
            test_drive TEXT,
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

    # Fill lead-specific placeholders into the prompt
    filled_prompt = prompt_config["prompt"].format(
        lead_name=lead.get("name", ""),
        car_model=lead.get("car_model", "कार"),
        fuel_type=lead.get("fuel_type", ""),
        budget=lead.get("budget", ""),
        timeline=lead.get("timeline", ""),
        test_drive=lead.get("test_drive", "No"),
    )

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
        "system_prompt": filled_prompt,
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


# ─── TRANSLATION CALL DISPATCH ────────────────────────────────────────────────

async def dispatch_translation_call_async(lead: dict):
    """
    Live Translation mode:
    1. Create two LiveKit rooms (op_room + cust_room)
    2. Dial operator phone (OPERATOR_NUMBER) into op_room via SIP
    3. Dial customer phone into cust_room via SIP
    4. Launch translation_bridge.py subprocess to bridge both rooms
    """
    if not (LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        logger.error("[TRANS] LiveKit credentials missing in .env")
        return

    phone = lead.get("phone", "")
    if not phone.startswith("+"):
        phone = f"+91{phone}"
    if phone.startswith("+910"):
        phone = "+91" + phone[4:]

    lead_id  = lead["id"]
    uid      = random.randint(1000, 9999)
    op_room  = f"trans-op-{lead_id}-{uid}"
    cust_room = f"trans-cust-{lead_id}-{uid}"

    lk_client = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)

    try:
        # Mark as calling
        conn = get_db()
        conn.execute(
            "UPDATE inquiries SET ai_call_status='calling', ai_called_at=? WHERE id=?",
            (datetime.now().isoformat(), lead_id),
        )
        conn.commit()
        conn.close()

        # Dial OPERATOR into op_room
        await lk_client.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=op_room,
                sip_trunk_id=SIP_TRUNK_ID,
                sip_call_to=OPERATOR_NUMBER,
                participant_identity="operator",
                participant_name=f"Live Call — {lead.get('name', '')}",
                wait_until_answered=False,
            )
        )
        logger.info(f"[TRANS] Calling operator {OPERATOR_NUMBER} → room={op_room}")

        # Dial CUSTOMER into cust_room
        await lk_client.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=cust_room,
                sip_trunk_id=SIP_TRUNK_ID,
                sip_call_to=phone,
                participant_identity="customer",
                participant_name=lead.get("name", "Customer"),
                wait_until_answered=False,
            )
        )
        logger.info(f"[TRANS] Calling customer {phone} → room={cust_room}")

        # Launch translation bridge as a subprocess
        import subprocess, sys as _sys
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "call_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"trans_{lead_id}_{uid}.log")

        cust_language = lead.get("cust_language", "english")
        logger.info(f"[TRANS] Launching bridge with language: {cust_language}")
        proc = subprocess.Popen(
            [_sys.executable, "translation_bridge.py", op_room, cust_room, cust_language],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdout=open(log_path, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        logger.info(
            f"[TRANS] Bridge started PID={proc.pid} | "
            f"op={op_room} | cust={cust_room} | log={log_path}"
        )

    except Exception as e:
        logger.error(f"[TRANS ERROR] Lead {lead_id}: {e}")
        conn = get_db()
        conn.execute("UPDATE inquiries SET ai_call_status='failed' WHERE id=?", (lead_id,))
        conn.commit()
        conn.close()
    finally:
        await lk_client.aclose()


def trigger_translation_call(lead: dict):
    """Run async translation dispatch in a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(dispatch_translation_call_async(lead))
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
        INSERT INTO inquiries (name, phone, email, city_name, state_name, category, car_model, fuel_type, budget, timeline, test_drive, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, phone,
        data.get("email", ""),
        data.get("city_name", ""),
        data.get("state_name", ""),
        data.get("category", "New Car Inquiry"),
        data.get("car_model", ""),
        data.get("fuel_type", ""),
        data.get("budget", ""),
        data.get("timeline", ""),
        data.get("test_drive", ""),
        data.get("message", ""),
    ))
    conn.commit()
    new_id = cursor.lastrowid
    lead = dict(conn.execute("SELECT * FROM inquiries WHERE id=?", (new_id,)).fetchone())
    conn.close()

    logger.info(f"[NEW INQUIRY] ID={new_id} | {name} | {phone} | {data.get('category')} | mode={data.get('call_mode', 'ai')}")

    # Trigger call immediately in background thread
    import threading
    call_mode = data.get("call_mode", "ai")
    if call_mode == "translation":
        cust_lang = data.get("cust_language", "english")
        lead["cust_language"] = cust_lang
        logger.info(f"[TRANS] Customer language from form: {cust_lang}")
        t = threading.Thread(target=trigger_translation_call, args=(lead,), daemon=True)
        msg = "आपकी inquiry दर्ज हो गई! हम आपको अभी live translation call कर रहे हैं। 📞"
    else:
        t = threading.Thread(target=trigger_call, args=(lead,), daemon=True)
        msg = "आपकी inquiry दर्ज हो गई! हम आपको अभी call कर रहे हैं। 📞"
    t.start()

    return jsonify({"success": True, "message": msg})


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
