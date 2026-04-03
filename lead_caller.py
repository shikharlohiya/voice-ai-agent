import os
import certifi

os.environ['SSL_CERT_FILE'] = certifi.where()

import asyncio
import json
import random
import logging
import httpx
from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lead-caller")

# --- CONFIGURATION ---
CRM_API_BASE = os.getenv("CRM_API_BASE", "http://localhost:5009")
FETCH_URL = f"{CRM_API_BASE}/api/website-inquiries/latest"
UPDATE_URL = f"{CRM_API_BASE}/api/website-inquiries"  # /{id}/call-update
POLL_INTERVAL = 30  # seconds between checks
CALL_GAP = 15  # seconds between calls

# Track leads already called in this session (prevents duplicate calls)
called_lead_ids = set()


# --- Category-wise prompts for IB Group ---
CATEGORY_PROMPTS = {
    "Broiler Integration": {
        "system_prompt": """You are a helpful business executive from IB Group calling a potential partner about contract broiler farming.

**Your Goal:** Understand their interest in contract farming and collect key details.

**Language:** Always respond in Hindi. Use simple Hindi that common people understand. You can mix English business words like "contract farming", "poultry farm", "integration" naturally.

**Key Behaviors:**
1. Introduce yourself as calling from IB Group regarding their inquiry.
2. Ask about: Farm location, Land size (in acres), Poultry experience (years), Investment budget
3. Be concise — 1-2 sentences per response.
4. If they have questions about contract terms, say "Hamare regional team aapko poori details denge, main unka visit schedule kara deta hoon."
5. End by saying their details will be shared with the regional team who will contact within 24 hours.

**CRITICAL:**
- If they say they are busy, politely ask for a good time to call back.
- If they say not interested, thank them and end the call.
- Do NOT make up contract terms, pricing, or technical details.""",
        "greeting": "Introduce yourself as calling from IB Group. Mention that they had inquired about broiler contract farming on the website. Ask if they can talk for 2 minutes."
    },

    "Broiler Sales": {
        "system_prompt": """You are a helpful sales executive from IB Group calling about a broiler purchase/sales inquiry.

**Your Goal:** Understand if they want to buy broilers or sell, and collect their requirements.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from IB Group regarding their broiler inquiry.
2. Ask: Are they a buyer or seller? What quantity? Which location? How often?
3. Be concise — 1-2 sentences per response.
4. Say "Hamare sales team aapko rate list aur delivery details share karenge."

**CRITICAL:**
- If they say they are busy, ask for a good time to call back.
- Do NOT quote prices or rates.""",
        "greeting": "Introduce yourself as calling from IB Group sales team. Mention their inquiry about broiler sales. Ask if this is a good time to talk."
    },

    "Parivartan": {
        "system_prompt": """You are a helpful executive from IB Group calling about their Parivartan EC Poultry Farm program.

**Your Goal:** Explain briefly about the Parivartan program and collect interested farmer details.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from IB Group Parivartan program.
2. Briefly say: "Parivartan program mein hum EC poultry farm setup mein help karte hain — construction se lekar operation tak."
3. Ask: Land available? Location? Investment capacity? Timeline?
4. Say the regional team will visit and explain the full process.

**CRITICAL:**
- Do NOT quote investment amounts or guarantee returns.
- If busy, ask for callback time.""",
        "greeting": "Introduce yourself as calling from IB Group Parivartan program. Mention they inquired about EC poultry farming. Ask if they have 2 minutes."
    },

    "Parivartan GenNxt": {
        "system_prompt": """You are a helpful executive from IB Group calling about their Parivartan GenNxt program.

**Your Goal:** Understand their interest and collect details for the regional team.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from IB Group Parivartan GenNxt program.
2. Ask: Location, Land size, Experience in poultry, Timeline to start
3. Say the team will share detailed project report and visit their site.

**CRITICAL:**
- Do NOT quote investment amounts.
- If busy, ask for callback time.""",
        "greeting": "Introduce yourself as calling from IB Group Parivartan GenNxt program regarding their inquiry. Ask if they can talk briefly."
    },

    "ABIS Chicken Delight": {
        "system_prompt": """You are a helpful sales executive from IB Group / ABIS calling about frozen chicken product inquiry.

**Your Goal:** Understand their product requirements and connect them with the sales team.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from ABIS Chicken Delight, a brand of IB Group.
2. Ask: Which products they need? Quantity? Delivery location? Business type (retail/wholesale/restaurant)?
3. Say the nearest distribution team will share rate list and delivery options.

**CRITICAL:**
- Do NOT quote prices.""",
        "greeting": "Introduce yourself as calling from ABIS Chicken Delight regarding their product inquiry. Ask if this is a good time."
    },

    "ABIS Poultry Feed": {
        "system_prompt": """You are a helpful executive from IB Group / ABIS calling about poultry feed inquiry.

**Your Goal:** Understand their feed requirements.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from ABIS Poultry Feed.
2. Ask: Farm size? Bird count? Current feed brand? Delivery location?
3. Say the feed sales team will share rate list.

**CRITICAL:**
- Do NOT quote prices.""",
        "greeting": "Introduce yourself as calling from ABIS Poultry Feed regarding their inquiry. Ask if they can talk."
    },

    "ABIS Fish Feed": {
        "system_prompt": """You are a helpful executive from IB Group / ABIS calling about fish feed inquiry.

**Your Goal:** Understand their fish feed requirements.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from ABIS Fish Feed.
2. Ask: Fish type? Pond size? Feed quantity needed? Delivery location?
3. Say the team will share rate list and delivery schedule.

**CRITICAL:**
- Do NOT quote prices.""",
        "greeting": "Introduce yourself as calling from ABIS Fish Feed regarding their inquiry. Ask if they have a moment."
    },

    "Chick Sales": {
        "system_prompt": """You are a helpful executive from IB Group calling about chick/hatchery inquiry.

**Your Goal:** Understand their hatchery or chick purchase needs.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from IB Group regarding their chick/hatchery inquiry.
2. Ask: Are they looking to buy chicks or start a contract hatchery? What capacity? Location?
3. Connect with the hatchery division team.

**CRITICAL:**
- Do NOT quote prices or terms.""",
        "greeting": "Introduce yourself as calling from IB Group hatchery division regarding their inquiry. Ask if this is a good time."
    },
}

# Default prompt for unknown categories
DEFAULT_PROMPT = {
    "system_prompt": """You are a helpful executive from IB Group returning a business inquiry call.

**Your Goal:** Understand what the caller needs and collect their details.

**Language:** Always respond in Hindi. Use simple Hindi with English business words mixed naturally.

**Key Behaviors:**
1. Introduce yourself as calling from IB Group regarding their website inquiry.
2. Ask what they are looking for.
3. Collect: Name confirmation, Location, Requirement details
4. Say the concerned team will get back to them within 24 hours.

**CRITICAL:**
- If busy, ask for callback time.
- Do NOT make up information.""",
    "greeting": "Introduce yourself as calling from IB Group regarding their website inquiry. Ask how you can help them."
}


def get_prompt_for_lead(lead: dict) -> dict:
    """Build a dynamic prompt based on lead category and details."""
    category = lead.get("category", "")
    prompt_config = CATEGORY_PROMPTS.get(category, DEFAULT_PROMPT)

    # Personalize the system prompt with lead details
    name = lead.get("name", "")
    city = lead.get("city_name", "")
    state = lead.get("state_name", "")
    message = lead.get("message", "")

    extra_context = f"""

**Caller Details (from website inquiry):**
- Name: {name}
- Location: {city}, {state}
- Their message: "{message}"

Use their name during the conversation. Reference their location if relevant."""

    return {
        "system_prompt": prompt_config["system_prompt"] + extra_context,
        "greeting": prompt_config["greeting"] + f" Address them as {name} ji."
    }


async def fetch_latest_lead() -> dict | None:
    """Fetch the latest uncalled lead from CRM API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(FETCH_URL)
            data = resp.json()

            if data.get("success") and data.get("data"):
                lead = data["data"]
                # Skip if already called in this session
                if lead["id"] in called_lead_ids:
                    logger.info(f"Lead {lead['id']} already called in this session. Skipping.")
                    return None
                # Check if already called via CRM status
                if lead.get("ai_call_status") != "not_called":
                    logger.info(f"Lead {lead['id']} already has status: {lead.get('ai_call_status')}")
                    return None
                return lead
            return None
    except Exception as e:
        logger.error(f"Failed to fetch lead: {e}")
        return None


async def update_lead_status(lead_id: int, status: str, summary: str = None):
    """Update lead status in CRM after call."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {
                "ai_call_status": status,
                "ai_called_at": __import__('datetime').datetime.now().isoformat(),
            }
            if summary:
                payload["ai_call_summary"] = summary

            resp = await client.put(
                f"{UPDATE_URL}/{lead_id}/call-update",
                json=payload
            )
            result = resp.json()
            if result.get("success"):
                logger.info(f"Lead {lead_id} updated to '{status}'")
            else:
                logger.error(f"Failed to update lead {lead_id}: {result}")
    except Exception as e:
        logger.error(f"Error updating lead {lead_id}: {e}")


async def dispatch_call(lead: dict):
    """Dispatch a call to the lead via LiveKit agent."""
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not (url and api_key and api_secret):
        logger.error("LiveKit credentials missing in .env")
        return

    phone_number = lead.get("phone", "")
    # Ensure phone number has country code
    if not phone_number.startswith("+"):
        phone_number = f"+91{phone_number}"
    # Remove leading 0 after country code (08787283444 → +918787283444)
    if phone_number.startswith("+910"):
        phone_number = "+91" + phone_number[4:]

    # Get category-specific prompts
    prompt_data = get_prompt_for_lead(lead)

    room_name = f"lead-{lead['id']}-{random.randint(1000, 9999)}"

    # Build metadata — keep it small, prompts are built in agent.py
    metadata = {
        "phone_number": phone_number,
        "lead_id": lead["id"],
        "lead_name": lead.get("name", ""),
        "lead_category": lead.get("category", ""),
        "lead_message": lead.get("message", ""),
        "lead_city": lead.get("city_name", ""),
        "lead_state": lead.get("state_name", ""),
        "crm_update_url": f"{UPDATE_URL}/{lead['id']}/call-update",
    }

    lk_api = api.LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret)

    try:
        # Mark as "calling" before dispatching
        await update_lead_status(lead["id"], "calling")

        dispatch_request = api.CreateAgentDispatchRequest(
            agent_name="outbound-caller",
            room=room_name,
            metadata=json.dumps(metadata)
        )

        dispatch = await lk_api.agent_dispatch.create_dispatch(dispatch_request)

        # Remember this lead so we don't call again
        called_lead_ids.add(lead["id"])
        logger.info(f"[OK] Call dispatched for lead {lead['id']} ({lead['name']}) to {phone_number}")
        logger.info(f"Room: {room_name} | Dispatch ID: {dispatch.id}")

    except Exception as e:
        logger.error(f"[ERROR] Failed to dispatch call for lead {lead['id']}: {e}")
        await update_lead_status(lead["id"], "failed", f"Dispatch error: {e}")

    finally:
        await lk_api.aclose()


async def run_poller():
    """Main polling loop — checks for new leads every POLL_INTERVAL seconds."""
    logger.info("=" * 60)
    logger.info("IB Group Lead Auto-Caller Started")
    logger.info(f"Polling: {FETCH_URL}")
    logger.info(f"Interval: {POLL_INTERVAL} seconds")
    logger.info("=" * 60)

    while True:
        lead = await fetch_latest_lead()

        if lead:
            logger.info(f"New lead found: {lead['name']} ({lead.get('category')}) - {lead.get('phone')}")
            await dispatch_call(lead)
            # Wait for call to finish before checking next lead
            logger.info(f"Waiting {CALL_GAP} seconds before next check...")
            await asyncio.sleep(CALL_GAP)
        else:
            logger.info("No new leads. Waiting...")

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_poller())
