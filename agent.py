import os
import certifi

# Fix for macOS SSL Certificate errors - MUST be before other imports
os.environ['SSL_CERT_FILE'] = certifi.where()

import logging
import json
import asyncio
import httpx
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from livekit import agents, api
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import (
    openai,
    cartesia,
    deepgram,
    noise_cancellation,
    silero,
    sarvam,
)
from livekit.agents import llm
from typing import Annotated, Optional

# Load environment variables
load_dotenv(".env")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbound-agent")

import config   

# TRUNK ID - Now loaded from config.py
# You can find this by running 'python setup_trunk.py --list' or checking LiveKit Dashboard


# --- Category-wise prompts for IB Group leads ---
LEAD_PROMPTS = {
    "Broiler Integration": {
        "prompt": """You are a business executive from IB Group calling about contract broiler farming.
Language: ALWAYS respond in Devanagari Hindi script (हिंदी में लिखो). Mix English words like IB Group, contract farming naturally. NEVER write in Roman/English script.

STRICT CALL FLOW (complete within 1 minute):
1. Greet: "नमस्ते [Name] जी, मैं IB Group से बोल रहा हूँ, आपने contract farming के बारे में inquiry की थी।"
2. Ask: "आपकी location कहाँ है?" (wait for answer)
3. Ask: "आपके पास कितनी ज़मीन है?" (wait for answer)
4. Ask: "क्या आप चाहेंगे कि हमारी team आपसे मिलने आए?" (wait for answer)
5. End: "धन्यवाद [Name] जी, हमारी regional team 24 घंटे में आपसे संपर्क करेगी। नमस्ते।" → use `end_call`

CRITICAL RULES:
- ONLY 1 short sentence per response. NEVER give long answers.
- Ask MAXIMUM 3 questions, then end the call.
- If they ask about pricing/terms: "हमारी team आपको पूरी details देगी।" Then move to next question.
- If they ask about other products (Parivartan, Feed, etc.): "मैं यह note कर लेता हूँ, concerned team आपको call करेगी।" Then end call.
- If busy: "कब call करें?" Note the time → use `end_call`
- If not interested: "धन्यवाद, नमस्ते।" → use `end_call` immediately.
- NEVER stay on call beyond 3-4 exchanges. Always use `end_call` to hang up after collecting details.
- Do NOT make up terms or pricing.""",
        "greeting": "IB Group से call कर रहे हैं, उन्होंने website पर broiler contract farming के बारे में inquiry की थी। हिंदी में 1 sentence में बात करें।"
    },
    "Broiler Sales": {
        "prompt": """You are a sales executive from IB Group calling about a broiler purchase/sales inquiry.
Your Goal: Understand if they want to buy or sell broilers and collect requirements.
Language: ALWAYS respond in Devanagari Hindi script (हिंदी में लिखो). You can mix English words like IB Group, contract farming, poultry naturally. Example: "नमस्ते, मैं IB Group से बोल रहा हूँ।" NEVER write in Roman/English script.
Key Behaviors:
1. Introduce yourself as calling from IB Group regarding their broiler inquiry.
2. Ask: Buyer or seller? Quantity? Location? Frequency?
3. Be concise. Say sales team will share rate list and delivery details.
CRITICAL: Do NOT quote prices. If busy, ask callback time.""",
        "greeting": "IB Group sales team से call कर रहे हैं, broiler sales inquiry के बारे में। हिंदी में बात करें।"
    },
    "Parivartan": {
        "prompt": """You are an executive from IB Group calling about the Parivartan EC Poultry Farm program.
Language: ALWAYS respond in Devanagari Hindi script (हिंदी में लिखो). Mix English words like IB Group, Parivartan, EC farm naturally. NEVER write in Roman/English script.

CALL FLOW — Ask ONE question at a time, be natural like a real person:
1. Greet: "नमस्ते [Name] जी, मैं एबीस फूड्स एंड प्रोटीन से बोल रही हूँ, आपने EC poultry farm के बारे में inquiry की थी। हमें कुछ जानकारी चाहिए ताकि हमारी team आपकी बेहतर मदद कर सके।"
2. "आपके पास कितनी land available है?"
3. "वहाँ water available है क्या?"
4. "Electricity available है क्या?"
5. "EC poultry farm के लिए आपका budget कितना है?"
6. Goodbye: "धन्यवाद [Name] , हमने आपकी inquiry note कर ली है। हमारी team जल्द से जल्द आपसे संपर्क करेगी। नमस्ते।" → use `end_call`

HOW TO BEHAVE NATURALLY:
- Ask ONE question, wait for answer, then DIRECTLY ask the next question. NEVER summarize or repeat previous answers.
- BAD example: "यह जानना अच्छा लगा कि आपके पास 6 एकड़ जमीन है और पानी भी है। अब अगला सवाल..." ← NEVER do this.
- GOOD example: Customer says "हां है" → You say "अच्छा, electricity available है?" ← Short, direct, no summary.
- Keep responses VERY short — maximum 5-6 words before the question. Just "अच्छा", "ठीक है", "जी" then ask next question.
- If answer is unclear ("पता नहीं", "देखना पड़ेगा") → say "ठीक है" and MOVE ON to next question. Do NOT ask again.
- If customer asks about other products (fish feed, oil, etc.) → "जी, मैंने आपका concern note कर लिया है, इसके लिए concerned team आपको call करेगी। मैं आपको Parivartan EC poultry farm से related जानकारी दे सकती हूँ।" Then MOVE ON to next pending question.
- If customer asks about Parivartan project details, investment, process, returns → "हमारी team आपसे connect करेगी और सारी details आपको बताएगी। आप मुझे बस कुछ जानकारी दे दीजिए।" Then continue asking questions.
- If customer asks "किस चीज़ के लिए?" → explain naturally: "EC poultry farm setup के लिए" — don't just repeat the question.
- If customer asks "तुम कौन हो?" / "Who are you?" → "जी, मैं एबीस फूड्स एंड प्रोटीन की तरफ से call कर रही हूँ, Parivartan EC poultry farm program के बारे में।" Then continue asking questions.
- If customer says "मिलना है" / "I want to meet" → "जी बिल्कुल, हमारी team आपसे मिलने का arrangement करेगी। पहले बस कुछ जानकारी ले लेती हूँ।" Then continue asking questions.
- If customer says "क्यों बताऊं?" / "Why should I tell?" / resists giving info → Convince gently: "जी राकेश जी, यह जानकारी से हम आपको बेहतर guide कर पाएंगे कि आपके लिए कौन सा plan सही रहेगा। कृपया बता दीजिए।" Then re-ask the same question ONE more time. If they still refuse, say goodbye and use `end_call`.
- If customer seems confused or uninterested after 2-3 questions → skip remaining questions, say goodbye and use `end_call`.
- NEVER ask the same question more than once. If they didn't answer, skip it.
- NEVER say the goodbye message more than once. Say it once → immediately use `end_call`.
- If customer says "मैंने inquiry नहीं की" / "I didn't inquire" / denies inquiry → "जी शायद किसी ने आपके नाम से inquiry की होगी। कोई बात नहीं, अगर आप EC poultry farm के बारे में जानना चाहें तो हमारी team आपकी मदद कर सकती है। धन्यवाद, नमस्ते।" → use `end_call`
- If busy: "कब call करें?" → use `end_call`
- If not interested: "धन्यवाद, नमस्ते।" → use `end_call`
- Do NOT make up investment amounts or guarantee returns.""",
        "greeting": "IB Group Parivartan program से call कर रहे हैं, EC poultry farming inquiry के बारे में। हिंदी में 1 sentence में बात करें।"
    },
    "Parivartan GenNxt": {
        "prompt": """You are an executive from IB Group calling about the Parivartan GenNxt program.
Your Goal: Understand interest and collect details for regional team.
Language: Always respond in Hindi. Mix English words naturally.
Key Behaviors:
1. Introduce yourself from IB Group Parivartan GenNxt.
2. Ask: Location, Land size, Poultry experience, Timeline to start.
3. Say team will share detailed project report.
CRITICAL: Do NOT quote investment amounts.""",
        "greeting": "IB Group Parivartan GenNxt program से call कर रहे हैं, उनकी inquiry के बारे में। हिंदी में बात करें।"
    },
    "ABIS Chicken Delight": {
        "prompt": """You are a sales executive from ABIS Chicken Delight (IB Group) calling about frozen chicken inquiry.
Your Goal: Understand product requirements and connect with sales team.
Language: Always respond in Hindi. Mix English words naturally.
Key Behaviors:
1. Introduce yourself from ABIS Chicken Delight.
2. Ask: Which products? Quantity? Delivery location? Business type?
3. Say distribution team will share rate list.
CRITICAL: Do NOT quote prices.""",
        "greeting": "ABIS Chicken Delight से call कर रहे हैं, product inquiry के बारे में। हिंदी में बात करें।"
    },
    "ABIS Poultry Feed": {
        "prompt": """You are an executive from ABIS Poultry Feed (IB Group) calling about feed inquiry.
Language: Always respond in Hindi. Mix English words naturally.
Ask: Farm size? Bird count? Current feed? Delivery location?
Say feed sales team will share rate list. Do NOT quote prices.""",
        "greeting": "ABIS Poultry Feed से call कर रहे हैं, feed inquiry के बारे में। हिंदी में बात करें।"
    },
    "ABIS Fish Feed": {
        "prompt": """You are an executive from ABIS Fish Feed (IB Group) calling about fish feed inquiry.
Language: Always respond in Hindi. Mix English words naturally.
Ask: Fish type? Pond size? Feed quantity? Delivery location?
Say team will share rate list. Do NOT quote prices.""",
        "greeting": "ABIS Fish Feed से call कर रहे हैं, fish feed inquiry के बारे में। हिंदी में बात करें।"
    },
    "Chick Sales": {
        "prompt": """You are an executive from IB Group hatchery division calling about chick/hatchery inquiry.
Language: Always respond in Hindi. Mix English words naturally.
Ask: Buy chicks or start contract hatchery? Capacity? Location?
Connect with hatchery division. Do NOT quote prices.""",
        "greeting": "IB Group hatchery division से call कर रहे हैं, chick/hatchery inquiry के बारे में। हिंदी में बात करें।"
    },
}

LEAD_DEFAULT_PROMPT = {
    "prompt": """You are a helpful executive from IB Group returning a business inquiry call.
Language: Always respond in Hindi. Mix English words naturally.
Ask what they need. Collect: Name, Location, Requirements.
Say concerned team will contact within 24 hours. Do NOT make up information.""",
    "greeting": "IB Group से call कर रहे हैं, उनकी website inquiry के बारे में। हिंदी में बात करें। पूछें कैसे मदद कर सकते हैं।"
}


def build_lead_prompt(lead_category, lead_name, lead_city, lead_state, lead_message):
    """Build dynamic system prompt from lead data."""
    prompt_config = LEAD_PROMPTS.get(lead_category, LEAD_DEFAULT_PROMPT)

    extra = f"""
Caller Details:
- Name: {lead_name}
- Location: {lead_city}, {lead_state}
- Their message: "{lead_message}"
बातचीत में उनका नाम इस्तेमाल करें। उनकी location का reference दें।"""

    return {
        "system_prompt": prompt_config["prompt"] + extra,
        "greeting": prompt_config["greeting"] + f" उन्हें {lead_name} जी बोलकर संबोधित करें।"
    }


def _build_tts(config_provider: str = None, config_voice: str = None):
    """Configure the Text-to-Speech provider based on env vars or dynamic config."""
    # Priority: Config > Env Var > Default
    provider = (config_provider or os.getenv("TTS_PROVIDER", config.DEFAULT_TTS_PROVIDER)).lower()
    
    # If using Sarvam Voice names (Anushka/Aravind), force Sarvam provider
    if config_voice in ["anushka", "aravind", "amartya", "dhruv"]:
        provider = "sarvam"

    if provider == "cartesia":
        logger.info("Using Cartesia TTS")
        model = os.getenv("CARTESIA_TTS_MODEL", config.CARTESIA_MODEL)
        voice = os.getenv("CARTESIA_TTS_VOICE", config.CARTESIA_VOICE)
        return cartesia.TTS(model=model, voice=voice)
    
    if provider == "sarvam":
        logger.info(f"Using Sarvam TTS (Voice: {config_voice})")
        model = os.getenv("SARVAM_TTS_MODEL", config.SARVAM_MODEL)
        # Use dynamic voice or env var or default
        voice = config_voice or os.getenv("SARVAM_VOICE", "anushka")
        language = os.getenv("SARVAM_LANGUAGE", config.SARVAM_LANGUAGE)
        return sarvam.TTS(model=model, speaker=voice, target_language_code=language, encoding="wav")

    if provider == "deepgram":
        logger.info("Using Deepgram TTS")
        model = os.getenv("DEEPGRAM_TTS_MODEL", "aura-asteria-en")
        return deepgram.TTS(model=model)

    # Default to OpenAI
    logger.info(f"Using OpenAI TTS (Voice: {config_voice})")
    model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
    voice = config_voice or os.getenv("OPENAI_TTS_VOICE", config.DEFAULT_TTS_VOICE)
    return openai.TTS(model=model, voice=voice)


def _build_llm(config_provider: str = None):
    """Configure the LLM provider based on config or env vars."""
    provider = (config_provider or os.getenv("LLM_PROVIDER", config.DEFAULT_LLM_PROVIDER)).lower()

    if provider == "groq":
        logger.info("Using Groq LLM")
        return openai.LLM(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL", config.GROQ_MODEL),
            temperature=float(os.getenv("GROQ_TEMPERATURE", str(config.GROQ_TEMPERATURE))),
        )
    
    # Default to OpenAI
    logger.info("Using OpenAI LLM")
    return openai.LLM(model=config.DEFAULT_LLM_MODEL)



class TransferFunctions(llm.ToolContext):
    def __init__(self, ctx: agents.JobContext, phone_number: str = None):
        super().__init__(tools=[])
        self.ctx = ctx
        self.phone_number = phone_number

    @llm.function_tool(description="Look up user details by phone number.")
    async def lookup_user(self, phone: str):
        """
        Mock function to look up user details.

        Args:
            phone: The phone number to look up
        """
        logger.info(f"Looking up user: {phone}")
        return f"User found: Shreyas Raj. Status: Premium. Last order: Coffee setup (Delivered)."

    @llm.function_tool(description="End/hang up the call. Use this ONLY after you have already spoken the goodbye message to the customer.")
    async def end_call(self):
        """End the call. Called AFTER goodbye message is spoken."""
        logger.info("Agent ending the call. Waiting for goodbye to finish...")
        # Wait 8 seconds for the goodbye TTS to finish speaking before disconnecting
        await asyncio.sleep(8)
        try:
            # Remove the SIP participant to hang up
            participant_identity = None
            if self.phone_number:
                participant_identity = f"sip_{self.phone_number}"
            else:
                for p in self.ctx.room.remote_participants.values():
                    participant_identity = p.identity
                    break

            if participant_identity:
                await self.ctx.api.room.remove_participant(
                    api.RoomParticipantIdentity(
                        room=self.ctx.room.name,
                        identity=participant_identity,
                    )
                )
                return "Call ended successfully."
            return "Could not find participant to disconnect."
        except Exception as e:
            logger.error(f"Error ending call: {e}")
            return f"Error ending call: {e}"

    @llm.function_tool(description="Transfer the call to a human support agent or another phone number.")
    async def transfer_call(self, destination: Optional[str] = None):
        """
        Transfer the call.
        """
        if destination is None:
            destination = config.DEFAULT_TRANSFER_NUMBER
            if not destination:
                 return "Error: No default transfer number configured."
        if "@" not in destination:
            # If no domain is provided, append the SIP domain
            if config.SIP_DOMAIN:
                # Ensure clean number (strip tel: or sip: prefix if present but no domain)
                clean_dest = destination.replace("tel:", "").replace("sip:", "")
                destination = f"sip:{clean_dest}@{config.SIP_DOMAIN}"
            else:
                # Fallback to tel URI if no domain configured
                if not destination.startswith("tel:") and not destination.startswith("sip:"):
                     destination = f"tel:{destination}"
        elif not destination.startswith("sip:"):
             destination = f"sip:{destination}"
        
        logger.info(f"Transferring call to {destination}")
        
        # Determine the participant identity
        # For outbound calls initiated by this agent, the participant identity is typically "sip_<phone_number>"
        # For inbound, we might need to find the remote participant.
        participant_identity = None
        
        # If we stored the phone number from metadata, we can construct the identity
        if self.phone_number:
            participant_identity = f"sip_{self.phone_number}"
        else:
            # Try to find a participant that is NOT the agent
            for p in self.ctx.room.remote_participants.values():
                participant_identity = p.identity
                break
        
        if not participant_identity:
            logger.error("Could not determine participant identity for transfer")
            return "Failed to transfer: could not identify the caller."

        try:
            logger.info(f"Transferring participant {participant_identity} to {destination}")
            await self.ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=self.ctx.room.name,
                    participant_identity=participant_identity,
                    transfer_to=destination,
                    play_dialtone=False
                )
            )
            return "Transfer initiated successfully."
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return f"Error executing transfer: {e}"


class OutboundAssistant(Agent):
    """
    An AI agent tailored for outbound calls.
    Uses dynamic prompt from lead data if available, otherwise falls back to config.
    """
    def __init__(self, tools: list, system_prompt: str = None) -> None:
        super().__init__(
            instructions=system_prompt or config.SYSTEM_PROMPT,
            tools=tools,
        )




async def entrypoint(ctx: agents.JobContext):
    """
    Main entrypoint for the agent.
    
    For outbound calls:
    1. Checks for 'phone_number' in the job metadata.
    2. Connects to the room.
    3. Initiates the SIP call to the phone number.
    4. Waits for answer before speaking.
    """
    logger.info(f"Connecting to room: {ctx.room.name}")
    
    # parse the phone number AND config from the metadata
    phone_number = None
    config_dict = {}
    
    # Check Job Metadata (Legacy/Dispatch)
    try:
        if ctx.job.metadata:
            data = json.loads(ctx.job.metadata)
            phone_number = data.get("phone_number")
            config_dict = data
    except Exception:
        pass
        
    # Check Room Metadata (Dashboard/Route.ts) - Overrides Job Metadata if present
    try:
        if ctx.room.metadata:
            data = json.loads(ctx.room.metadata)
            if data.get("phone_number"):
                phone_number = data.get("phone_number")
            config_dict.update(data) # Merge configs
    except Exception:
        logger.warning("No valid JSON metadata found in Room.")

    # --- Extract lead data if present (from lead_caller.py) ---
    lead_id = config_dict.get("lead_id")
    crm_update_url = config_dict.get("crm_update_url")

    # Build dynamic prompt from lead category
    lead_system_prompt = None
    lead_greeting = None
    if lead_id:
        logger.info(f"Lead call detected: ID={lead_id}, Name={config_dict.get('lead_name')}, Category={config_dict.get('lead_category')}")
        prompt_data = build_lead_prompt(
            config_dict.get("lead_category", ""),
            config_dict.get("lead_name", ""),
            config_dict.get("lead_city", ""),
            config_dict.get("lead_state", ""),
            config_dict.get("lead_message", ""),
        )
        lead_system_prompt = prompt_data["system_prompt"]
        lead_greeting = prompt_data["greeting"]

    # Initialize function context
    fnc_ctx = TransferFunctions(ctx, phone_number)

    # --- Call Transcript Logging ---
    call_start = datetime.now()
    transcript = []
    log_dir = Path("call_logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"call_{phone_number or 'unknown'}_{call_start.strftime('%Y%m%d_%H%M%S')}.json"

    def save_transcript():
        data = {
            "phone_number": phone_number,
            "room": ctx.room.name,
            "started_at": call_start.isoformat(),
            "ended_at": datetime.now().isoformat(),
            "lead_id": lead_id,
            "lead_name": config_dict.get("lead_name"),
            "lead_category": config_dict.get("lead_category"),
            "messages": transcript,
        }
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Transcript saved to {log_file}")

    async def push_result_to_crm(status: str, summary: str = None):
        """Push call result back to CRM after call ends."""
        if not crm_update_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload = {
                    "ai_call_status": status,
                    "ai_call_summary": summary or "Call completed",
                    "ai_called_at": datetime.now().isoformat(),
                }
                resp = await client.put(crm_update_url, json=payload)
                result = resp.json()
                if result.get("success"):
                    logger.info(f"CRM updated: Lead {lead_id} -> {status}")
                else:
                    logger.error(f"CRM update failed: {result}")
        except Exception as e:
            logger.error(f"Error pushing to CRM: {e}")

    # Initialize the Agent Session with plugins
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model=config.STT_MODEL, language=config.STT_LANGUAGE),
        llm=_build_llm(config_dict.get("model_provider")),
        tts=_build_tts(config_dict.get("model_provider"), config_dict.get("voice_id")),
    )

    # --- Event Listeners for Logging ---
    @session.on("user_input_transcribed")
    def on_user_input(event):
        if event.is_final:
            logger.info(f"[USER]: {event.transcript}")
            transcript.append({"role": "user", "text": event.transcript, "time": datetime.now().isoformat()})
            save_transcript()

    @session.on("conversation_item_added")
    def on_conversation_item(event):
        item = event.item
        if item.role == "assistant" and item.text_content:
            logger.info(f"[AGENT]: {item.text_content}")
            transcript.append({"role": "agent", "text": item.text_content, "time": datetime.now().isoformat()})
            save_transcript()

    # Use lead-specific prompt if available, otherwise use config default
    active_system_prompt = lead_system_prompt or config.SYSTEM_PROMPT
    active_greeting = lead_greeting or config.INITIAL_GREETING

    # Start the session
    await session.start(
        room=ctx.room,
        agent=OutboundAssistant(tools=list(fnc_ctx.function_tools.values()), system_prompt=active_system_prompt),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVCTelephony(),
            close_on_disconnect=True, # Close room when agent disconnects
        ),
    )

    # Logic to dial out:
    # 1. If 'phone_number' is present, we MIGHT need to dial.
    # 2. Check if a SIP participant is already in the room (Dashboard dispatch case).
    
    should_dial = False
    if phone_number:
        # Check if any remote participant looks like our user (sip_PHONE)
        user_already_here = False
        for p in ctx.room.remote_participants.values():
            if f"sip_{phone_number}" in p.identity or "sip_" in p.identity:
                user_already_here = True
                break
        
        if not user_already_here:
            should_dial = True
            logger.info("User not in room. Agent will initiate dial-out.")
        else:
            logger.info("User already in room (Dashboard dispatched). output Only generated greeting.")

    if should_dial:
        logger.info(f"Initiating outbound SIP call to {phone_number}...")
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=config.SIP_TRUNK_ID,
                    sip_call_to=phone_number,
                    participant_identity=f"sip_{phone_number}",
                    wait_until_answered=True,
                )
            )
            logger.info("Call answered! Agent is now listening.")

            await session.generate_reply(
                instructions=active_greeting
            )

        except Exception as e:
            logger.error(f"Failed to place outbound call: {e}")
            await push_result_to_crm("failed", f"Call failed: {e}")
            ctx.shutdown()
    else:
        logger.info("Detecting if we should greet...")
        await session.generate_reply(instructions=active_greeting)

    # --- Wait for call to end, then push result to CRM ---
    async def generate_english_summary():
        """Use LLM to generate a clean English summary from the transcript."""
        if not transcript:
            return f"Call with {config_dict.get('lead_name', phone_number)}. No conversation recorded."

        # Build conversation text for LLM
        convo = "\n".join([f"{m['role'].upper()}: {m['text']}" for m in transcript])

        try:
            # Use Groq for fast English summary
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": "Summarize this phone call in 2-3 short English sentences. Include: caller name, what they want, and outcome (interested/not interested/callback). Do NOT mention location. Write ONLY in English."},
                            {"role": "user", "content": convo},
                        ],
                        "max_tokens": 150,
                        "temperature": 0.3,
                    },
                )
                result = resp.json()
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            # Fallback to basic English summary
            return f"Call with {config_dict.get('lead_name', phone_number)}. Category: {config_dict.get('lead_category', 'N/A')}. Total messages: {len(transcript)}."

    @ctx.room.on("participant_disconnected")
    def on_participant_left(participant):
        if participant.identity.startswith("sip_"):
            logger.info(f"Call ended. Participant {participant.identity} disconnected.")

            async def _push():
                summary = await generate_english_summary()
                logger.info(f"English summary: {summary}")
                await push_result_to_crm("called", summary)

            asyncio.ensure_future(_push())


if __name__ == "__main__":
    # The agent name "outbound-caller" is used by the dispatch script to find this worker
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller", 
        )
    )
