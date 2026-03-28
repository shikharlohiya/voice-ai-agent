import os
from dotenv import load_dotenv

load_dotenv()

# =========================================================================================
#  🤖 RAPID X AI - AGENT CONFIGURATION
#  Use this file to customize your agent's personality, models, and behavior.
# =========================================================================================

# --- 1. AGENT PERSONA & PROMPTS ---
# The main instructions for the AI. Defines who it is and how it behaves.
SYSTEM_PROMPT = """
You are a helpful and polite School Receptionist at "Rapid X High School".

**Your Goal:** Answer questions from parents about admissions, fees, and timings.

**Key Behaviors:**
1. **Multilingual:** You can speak fluent English and Hindi. If the user speaks Hindi, switch to Hindi immediately.
2. **Polite & Warm:** Always be welcomed and respectful.
3. **Be Concise:** Keep answers short (1-2 sentences).
4. **Admissions:** If asked about admissions, say they are open for Grade 1 to 10 and ask if they want to schedule a visit.
5. **Fees:** If asked about fees, say "Please visit the school office for exact details, but it starts at roughly 50k per year."

**CRITICAL:**
- Only use `transfer_call` if they explicitly ask to talk to the Principal or Admin.
- If they say "Bye", say "Namaste" or "Goodbye" and end the call.
"""

INITIAL_GREETING = "The user has picked up the call. Introduce yourself as the School Receptionist immediately."

fallback_greeting = "Greet the user immediately."


# --- 2. SPEECH-TO-TEXT (STT) SETTINGS ---
# We use Deepgram for high-speed transcription.
STT_PROVIDER = "deepgram"
STT_MODEL = "nova-2"  # Recommended: "nova-2" (balanced) or "nova-3" (newest)
STT_LANGUAGE = "en"


# --- 3. TEXT-TO-SPEECH (TTS) SETTINGS ---
# Choose your voice provider: "openai", "sarvam" (Indian voices), or "cartesia" (Ultra-fast)
# DEFAULT_TTS_PROVIDER = "sarvam"   # Sarvam has compatibility issue with current plugin
DEFAULT_TTS_PROVIDER = "deepgram"   # Deepgram works, can speak Hindi text
DEFAULT_TTS_VOICE = "aura-asteria-en"

# Sarvam AI Specifics (for Indian Context)
SARVAM_MODEL = "bulbul:v2"
SARVAM_LANGUAGE = "hi-IN" # Hindi

# Cartesia Specifics
CARTESIA_MODEL = "sonic-2"
CARTESIA_VOICE = "f786b574-daa5-4673-aa0c-cbe3e8534c02"


# --- 4. LARGE LANGUAGE MODEL (LLM) SETTINGS ---
# Choose "openai" or "groq"
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_LLM_MODEL = "gpt-4o-mini" # OpenAI default

# Groq Specifics (Faster inference)
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_TEMPERATURE = 0.7


# --- 5. TELEPHONY & TRANSFERS ---
# Default number to transfer calls to if no specific destination is asked.
DEFAULT_TRANSFER_NUMBER = os.getenv("DEFAULT_TRANSFER_NUMBER")

# Vobiz Trunk Details (Loaded from .env usually, but you can hardcode if needed)
SIP_TRUNK_ID = os.getenv("VOBIZ_SIP_TRUNK_ID")
SIP_DOMAIN = os.getenv("VOBIZ_SIP_DOMAIN")
