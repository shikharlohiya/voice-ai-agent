# AI Voice Agent - Complete Guide

## 1. Current Architecture

```
Customer's Phone
    --> Vobiz (SIP/Phone Line)         Rs 1.50/min
    --> LiveKit Cloud (Audio Router)   Rs 0.67/min
    --> Deepgram Nova-2 (STT/Ears)     Rs 0.36/min    Listens to speech
    --> Groq Llama 3.3 (LLM/Brain)     Rs 0.12/min    Thinks & responds
    --> Sarvam Anushka (TTS/Mouth)     Rs 0.85/min    Speaks in Hindi
    --> LiveKit --> Vobiz --> Customer hears the reply

    TOTAL: Rs 3.50/min
```

## 2. Current Tech Stack

| Component | Service | Purpose |
|-----------|---------|---------|
| STT | Deepgram Nova-2 | Converts voice to text |
| LLM | Groq (Llama 3.3 70B) | Generates replies |
| TTS | Sarvam (Bulbul v2, Anushka) | Converts text to Hindi voice |
| VAD | Silero | Detects when someone is speaking |
| Audio | LiveKit Cloud | Routes audio in real-time |
| Phone | Vobiz SIP | Dials real phone numbers |

## 3. File Structure

```
agent.py          - Main AI agent (brain of the system)
config.py         - System prompt, model settings, voices
make_call.py      - CLI tool to make outbound calls
create_trunk.py   - Create SIP trunk in LiveKit
setup_trunk.py    - Update SIP trunk credentials
list_trunks.py    - List all SIP trunks
.env              - API keys and secrets (never commit)
call_logs/        - Saved call transcripts (JSON)
dashboard/        - Next.js web dashboard
```

## 4. How to Run

### Terminal 1 - Start Agent:
```
cd "E:\AI Voice Agent\LIvekitAIVoice-main\LIvekitAIVoice-main"
.\venv\Scripts\activate
python agent.py start
```

### Terminal 2 - Make a Call:
```
cd "E:\AI Voice Agent\LIvekitAIVoice-main\LIvekitAIVoice-main"
.\venv\Scripts\activate
python make_call.py --to +918839699199
```

### Start Dashboard (Optional):
```
cd dashboard
npm install
npm run dev
```
Dashboard runs at http://localhost:3000

## 5. Call Flow

```
1. make_call.py sends dispatch request to LiveKit
2. LiveKit creates a room and notifies agent.py
3. agent.py joins the room
4. agent.py tells LiveKit to dial the phone via Vobiz SIP trunk
5. Phone rings, customer picks up
6. Conversation loop:
   Customer speaks --> Deepgram transcribes --> Groq generates reply --> Sarvam speaks
7. Call transcript saved to call_logs/ folder
8. Call ends when customer hangs up
```

## 6. Configuration (config.py)

### System Prompt
Change `SYSTEM_PROMPT` to change the AI's personality and behavior.

### TTS Providers (Voice)
| Provider | Voice | Language | Set TTS_PROVIDER to |
|----------|-------|----------|---------------------|
| Sarvam | anushka (female), aravind (male) | Hindi/Indian | "sarvam" |
| Deepgram | aura-asteria-en | English | "deepgram" |
| OpenAI | alloy, shimmer, echo | English + Hindi | "openai" |
| Cartesia | sonic-2 | English | "cartesia" |

### LLM Providers (Brain)
| Provider | Model | Set LLM_PROVIDER to |
|----------|-------|---------------------|
| Groq | llama-3.3-70b-versatile | "groq" |
| OpenAI | gpt-4o-mini | "openai" |

### STT Settings
| Setting | Value | Notes |
|---------|-------|-------|
| STT_MODEL | "nova-2" | or "nova-3" for newest |
| STT_LANGUAGE | "en" | "hi" for Hindi, "multi" for auto-detect |

## 7. Cost Breakdown Per Minute

| Service | Cost/min (INR) | Cost/min (USD) |
|---------|----------------|----------------|
| Deepgram STT | Rs 0.36 | $0.0043 |
| Groq LLM | Rs 0.12 | $0.0015 |
| Sarvam TTS | Rs 0.85 | $0.010 |
| LiveKit Cloud | Rs 0.67 | $0.008 |
| Vobiz SIP | Rs 1.50 | $0.018 |
| **TOTAL** | **Rs 3.50** | **$0.044** |

### Comparison with Competitors
| Platform | Cost/min (INR) |
|----------|----------------|
| **This setup** | **Rs 3.50** |
| Bland.ai | Rs 7-9 |
| Vapi | Rs 9-17 |
| Air.ai | Rs 10-12 |
| Retell.ai | Rs 8-10 |

## 8. Function Tools (Current)

### lookup_user
- Looks up user details by phone number
- Currently returns mock data
- TODO: Connect to real database

### transfer_call
- Transfers call to another phone number or human agent
- Uses SIP REFER protocol
- Triggered when user asks to talk to admin/principal

## 9. Business Use Case: Website Lead Qualification

### The Problem
Website gets enquiries like:
```json
{
    "id": 7669,
    "category": "Broiler Sales",
    "name": "Rohit",
    "phone": "6303773868",
    "city_name": "Srikakulam",
    "state_name": "Andhra Pradesh",
    "message": "i need growing of broiler",
    "sent_to_emails": "sushmita@ibgroup.co.in"
}
```

Different categories come in: Broiler Sales, ABIS Green, Feed, Job Enquiry, etc.
Users sometimes pick wrong category. The MESSAGE tells the real intent.

### The Solution

#### Step 1: Dynamic System Prompt
Pass ALL lead data to the AI. Let the LLM understand intent from the message, not the category.

```python
SYSTEM_PROMPT = f"""
You are a smart customer representative from IB Group.

You are calling {name} from {city}, {state}.
They submitted this enquiry: "{message}"
Category they selected: {category}

Your job:
1. Greet them, confirm their enquiry
2. Understand what they ACTUALLY need (trust message over category)
3. Ask relevant follow-up questions based on their need:
   - BUYING (broiler/feed/chicks): quantity, frequency, budget, timeline
   - JOB: qualification, experience, role, salary expectation
   - PARTNERSHIP/DEALERSHIP: location, investment capacity, experience
   - COMPLAINT: order details, issue, resolution expected
4. Save the qualified information using the save_lead_data tool
5. Tell them the right team will follow up

Keep it short. Speak Hindi if they prefer.
"""
```

#### Step 2: Add Function Tools

```python
@llm.function_tool(description="Save qualified lead data after gathering info from customer")
async def save_qualified_lead(self,
    intent: str,              # "purchase" / "job" / "partnership" / "complaint"
    business_type: str,       # "farm owner" / "trader" / "fresher"
    requirements: str,        # "5000 broiler birds weekly"
    budget_or_salary: str,    # "80-90 per kg" or "25k expected salary"
    timeline: str,            # "next week" / "immediate"
    callback_time: str,       # "tomorrow 11 AM"
    notes: str                # any additional info
):
    # Save to database (Supabase/PostgreSQL)
    # Send email notification to assigned team
    # Return confirmation
    pass

@llm.function_tool(description="Check product availability or job openings")
async def check_availability(self, product_or_role: str, location: str):
    # Query database
    # Return available products/jobs for that location
    pass
```

#### Step 3: Auto-Trigger Calls from Website

```python
# Webhook receives new lead from website
# Reads lead data
# Builds dynamic prompt
# Triggers make_call.py with metadata

metadata = {
    "phone_number": lead["phone"],
    "customer_name": lead["name"],
    "category": lead["category"],
    "message": lead["message"],
    "city": lead["city_name"],
    "state": lead["state_name"],
    "email": lead["email"],
    "assigned_to": lead["sent_to_emails"]
}
```

#### Step 4: What Business Department Receives

```json
{
    "lead_id": 7669,
    "name": "Rohit",
    "phone": "+916303773868",
    "location": "Srikakulam, Andhra Pradesh",
    "original_message": "i need growing of broiler",

    "ai_qualified_data": {
        "intent": "purchase",
        "business_type": "Farm owner, 2 acres",
        "requirements": "5000 broiler birds per batch",
        "budget": "85-90 per kg",
        "frequency": "Monthly",
        "timeline": "Needs supply by next week",
        "callback_time": "Tomorrow 11 AM",
        "lead_score": "Hot",
        "call_duration": "1 min 45 sec",
        "call_transcript": "[full conversation]"
    },

    "routed_to": "Sales Team - sushmita@ibgroup.co.in",
    "status": "Qualified - Pending Sales Follow-up"
}
```

#### Step 5: Department Routing

| Detected Intent | Route To |
|-----------------|----------|
| Purchase (broiler/feed/chicks) | Sales Team |
| Job/Research/Career | HR Team |
| Partnership/Dealership | Business Development |
| Complaint | Customer Support |
| General Enquiry | Customer Support |

### Architecture Diagram

```
Website Form Submitted
    |
    v
Database (stores lead)
    |
    v
Webhook/Cron triggers AI call
    |
    v
agent.py reads lead data from DB
    |
    v
Builds dynamic prompt (based on message + category)
    |
    v
AI calls customer via Vobiz
    |
    v
AI asks relevant questions (LLM decides based on conversation)
    |
    v
AI calls save_qualified_lead() tool --> saves to DB
    |
    v
Notification sent to right department (email/WhatsApp)
    |
    v
Admin Dashboard shows qualified lead with all details
```

## 10. Deployment

### Recommended: Railway ($5-10/month)
- Push to GitHub, connect Railway, add env vars, done
- Dockerfile already included

### AWS Free Tier (12 months free)
- EC2 t3.micro (1 vCPU, 1 GB RAM)
- Region: Mumbai (ap-south-1) for lowest latency
- Run agent.py as systemd service

### Docker
```bash
docker-compose up -d
```

## 11. Multilingual Support

| Language | Deepgram STT | Groq LLM | Sarvam TTS |
|----------|-------------|-----------|------------|
| English | Yes | Yes | Yes |
| Hindi | Yes | Yes | Yes (hi-IN) |
| Tamil | Yes | Yes | Yes (ta-IN) |
| Telugu | Yes | Yes | Yes (te-IN) |
| Kannada | Yes | Yes | Yes (kn-IN) |
| Bengali | Yes | Yes | Yes (bn-IN) |
| Marathi | Yes | Yes | Yes (mr-IN) |
| Gujarati | Yes | Yes | Yes (gu-IN) |

To switch language: change `STT_LANGUAGE` in config.py and `SARVAM_LANGUAGE` to match.

## 12. Known Issues & Fixes

| Issue | Fix |
|-------|-----|
| Port 8081 already in use | Kill old process: `netstat -ano \| findstr 8081` then `taskkill /F /PID <pid>` |
| Sarvam TTS WAV error | Fixed: Changed mime_type from "audio/wav" to "audio/mpeg" in sarvam/tts.py |
| lookup_user crash | Fixed: Changed `def` to `async def` |
| Emoji print crash (Windows) | Fixed: Replaced emojis with [OK]/[ERROR] in print statements |
| SIP trunk 404 error | Run `python create_trunk.py` to register trunk in LiveKit, update .env with LiveKit trunk ID (starts with ST_) |

## 13. Multi-Tenant SaaS Architecture (50+ Clients)

### System Architecture

```
                          ┌─────────────────────────────┐
                          │      ADMIN SUPER DASHBOARD   │
                          │   (Your master control panel) │
                          │   - Manage all clients        │
                          │   - Billing & usage           │
                          │   - Monitor all calls         │
                          └──────────┬──────────────────┘
                                     │
                          ┌──────────v──────────────────┐
                          │        API GATEWAY           │
                          │   (Next.js / FastAPI)        │
                          │   - Auth per client          │
                          │   - Rate limiting            │
                          │   - Webhook receiver         │
                          └──────────┬──────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
     ┌────────v────────┐  ┌─────────v─────────┐  ┌────────v────────┐
     │  Client: Salon  │  │ Client: Hospital  │  │ Client: Business│
     │  - Own prompt   │  │ - Own prompt      │  │ - Own prompt    │
     │  - Own number   │  │ - Own number      │  │ - Own number    │
     │  - Own dashboard│  │ - Own dashboard   │  │ - Own dashboard │
     └────────┬────────┘  └─────────┬─────────┘  └────────┬────────┘
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     │
                          ┌──────────v──────────────────┐
                          │      DATABASE (Supabase)     │
                          │   - clients table            │
                          │   - calls table              │
                          │   - appointments table       │
                          │   - leads table              │
                          │   - transcripts table        │
                          │   - billing table            │
                          └──────────┬──────────────────┘
                                     │
                          ┌──────────v──────────────────┐
                          │      AI AGENT (agent.py)     │
                          │   - Reads client config      │
                          │   - Loads dynamic prompt     │
                          │   - Makes calls via Vobiz    │
                          │   - Saves results to DB      │
                          └─────────────────────────────┘
```

### Database Schema

```sql
-- Clients (your customers)
CREATE TABLE clients (
    id UUID PRIMARY KEY,
    name TEXT,                    -- "Glamour Salon", "City Hospital"
    business_type TEXT,           -- "salon", "hospital", "showroom"
    phone_number TEXT,            -- Their outbound caller ID
    sip_trunk_id TEXT,            -- Their SIP trunk
    system_prompt TEXT,           -- Custom AI personality
    greeting TEXT,                -- Custom greeting message
    language TEXT DEFAULT 'en',   -- "en", "hi", "multi"
    voice TEXT DEFAULT 'anushka', -- TTS voice
    max_call_duration INT DEFAULT 120,  -- seconds
    webhook_url TEXT,             -- Their website webhook
    api_key TEXT,                 -- For API access
    monthly_minutes_limit INT,
    created_at TIMESTAMP
);

-- Calls log
CREATE TABLE calls (
    id UUID PRIMARY KEY,
    client_id UUID REFERENCES clients(id),
    phone_number TEXT,
    direction TEXT,              -- "outbound" / "inbound"
    status TEXT,                 -- "completed" / "failed" / "no_answer" / "busy"
    duration_seconds INT,
    cost DECIMAL,
    room_name TEXT,
    started_at TIMESTAMP,
    ended_at TIMESTAMP
);

-- Transcripts
CREATE TABLE transcripts (
    id UUID PRIMARY KEY,
    call_id UUID REFERENCES calls(id),
    role TEXT,                   -- "user" / "agent"
    message TEXT,
    timestamp TIMESTAMP
);

-- Appointments (for salon, hospital, showroom)
CREATE TABLE appointments (
    id UUID PRIMARY KEY,
    client_id UUID REFERENCES clients(id),
    call_id UUID REFERENCES calls(id),
    customer_name TEXT,
    customer_phone TEXT,
    service TEXT,                -- "haircut", "doctor visit", "car service"
    date DATE,
    time TIME,
    status TEXT,                 -- "confirmed" / "cancelled" / "completed"
    notes TEXT,
    created_at TIMESTAMP
);

-- Leads (for business enquiries)
CREATE TABLE leads (
    id UUID PRIMARY KEY,
    client_id UUID REFERENCES clients(id),
    call_id UUID REFERENCES calls(id),
    customer_name TEXT,
    customer_phone TEXT,
    intent TEXT,                 -- "purchase" / "job" / "partnership"
    requirements TEXT,
    budget TEXT,
    timeline TEXT,
    lead_score TEXT,             -- "hot" / "warm" / "cold"
    assigned_to TEXT,
    status TEXT,                 -- "new" / "qualified" / "converted" / "lost"
    created_at TIMESTAMP
);

-- Billing
CREATE TABLE billing (
    id UUID PRIMARY KEY,
    client_id UUID REFERENCES clients(id),
    month TEXT,                  -- "2026-03"
    total_minutes DECIMAL,
    total_calls INT,
    amount DECIMAL,
    status TEXT,                 -- "pending" / "paid"
    created_at TIMESTAMP
);
```

### How Multi-Tenant Works

```
Client "Glamour Salon" signs up
    → You create entry in clients table
    → Set their custom prompt: "You are receptionist at Glamour Salon..."
    → Assign them a phone number
    → Give them API key + dashboard login

When their customer calls or lead comes in:
    → System reads client config from DB
    → Loads THEIR prompt, THEIR voice, THEIR language
    → AI behaves as THEIR receptionist
    → Data saved under THEIR client_id
    → THEIR dashboard shows only THEIR data
```

### Per-Industry Configuration

#### SALON

```python
# System Prompt
"""
You are a friendly receptionist at {salon_name}.
Services: {services_list}  # Haircut, Facial, Manicure, etc.
Stylists: {stylists_list}  # Priya, Rahul, etc.

Your job:
1. Greet warmly
2. Ask what service they want
3. Check available slots using check_slots tool
4. Book appointment using book_appointment tool
5. Confirm date, time, stylist
"""

# Function Tools
- check_slots(date, service) → "3 PM, 4 PM, 5:30 PM available"
- book_appointment(name, phone, service, date, time, stylist)
- cancel_appointment(appointment_id)
- get_pricing(service) → "Haircut: Rs 500, Facial: Rs 1500"

# Example Call
AI: "Hi! Glamour Salon se bol rahi hoon. Kya aap appointment book karna chahenge?"
User: "Haan, kal facial karwana hai"
AI calls check_slots("2026-03-29", "facial") → "2 PM aur 4 PM available hai"
AI: "Kal 2 PM ya 4 PM, kaunsa time suit karega?"
User: "4 PM"
AI calls book_appointment("Shikhar", "+91xxx", "facial", "2026-03-29", "16:00")
AI: "Done! Kal 4 PM ko facial book ho gaya. See you!"
```

#### HOSPITAL / CLINIC

```python
# System Prompt
"""
You are a polite receptionist at {hospital_name}.
Doctors: {doctors_list}     # Dr. Sharma (Cardiology), Dr. Patel (Ortho)
OPD Timings: {opd_timings}  # Mon-Sat 9AM-5PM

Your job:
1. Greet politely
2. Ask which doctor/department they need
3. Check doctor availability using check_doctor_slots tool
4. Book OPD appointment using book_opd tool
5. Remind them to bring ID and previous reports

IMPORTANT: Never give medical advice. Always say "Please consult the doctor."
"""

# Function Tools
- check_doctor_slots(doctor_name, date) → "10:30 AM, 11:00 AM"
- book_opd(patient_name, phone, doctor, date, time, reason)
- get_doctor_info(department) → "Dr. Sharma - Cardiology - Mon/Wed/Fri"
- send_reminder(appointment_id) → sends WhatsApp reminder

# Example Call
AI: "Namaste! City Hospital se bol rahi hoon. Kaise help kar sakti hoon?"
User: "Dr. Sharma se milna hai"
AI calls check_doctor_slots("Dr. Sharma", "2026-03-29")
AI: "Dr. Sharma kal available hain 10:30 aur 11 baje. Kaunsa time chahiye?"
User: "10:30"
AI calls book_opd("Rohit", "+91xxx", "Dr. Sharma", "2026-03-29", "10:30", "checkup")
AI: "Appointment confirmed! Kal 10:30, Dr. Sharma. Apna ID aur purane reports le aayein."
```

#### CAR SHOWROOM / SERVICE CENTER

```python
# System Prompt
"""
You are a service advisor at {showroom_name}.
Services: Regular Service, Extended Warranty, Body Repair, Insurance

You are calling {customer_name}.
Their car: {car_model}, last serviced: {last_service_date}.
Next service due: {due_date}.

Your job:
1. Inform them about upcoming service
2. Check available slots
3. Book service appointment
4. Mention any offers/discounts
"""

# Function Tools
- check_service_slots(date) → "9 AM, 10 AM, 2 PM"
- book_service(customer, car, date, time, service_type)
- get_service_cost(car_model, service_type) → "Regular service: Rs 5,500"
- get_customer_history(phone) → last service details

# Example Call
AI: "Hi Shikhar ji, XYZ Motors se bol raha hoon. Aapki Honda City ki
     second servicing due hai. Kal 2 slots available hain - 9 AM aur 10 AM."
User: "10 AM chalega"
AI calls book_service("Shikhar", "Honda City", "2026-03-29", "10:00", "regular")
AI: "Book ho gaya! Kal 10 AM, regular service Rs 5,500. Thank you!"
```

#### REAL ESTATE

```python
# System Prompt
"""
You are a sales executive at {builder_name}.
Project: {project_name} at {location}
Available: {unit_types}  # 2BHK, 3BHK, plots
Price range: {price_range}

Your job:
1. Follow up on website enquiry
2. Understand their budget and preference
3. Schedule a site visit
4. Collect: budget, family size, possession timeline, loan needed?
"""

# Function Tools
- save_lead(name, phone, budget, unit_preference, timeline, loan_needed)
- schedule_site_visit(name, phone, date, time)
- get_unit_availability(unit_type) → "3 units of 2BHK available"
- get_pricing(unit_type) → "2BHK: Rs 45L - 55L"
```

#### EDUCATION / COACHING

```python
# System Prompt
"""
You are an admissions counselor at {institute_name}.
Courses: {courses_list}  # JEE, NEET, Foundation
Batches: {batch_info}    # Morning 7-9, Evening 5-7
Fee: {fee_structure}

Your job:
1. Follow up on enquiry
2. Understand student's class, target exam
3. Recommend right batch
4. Schedule a demo class
5. Share fee details
"""

# Function Tools
- save_student_lead(name, phone, class, target_exam, preferred_batch)
- schedule_demo(name, phone, course, date, time)
- get_batch_availability(course, batch_time) → "5 seats left"
- get_fee_structure(course) → "JEE 2-year: Rs 1.2L"
```

#### RESTAURANT / FOOD DELIVERY

```python
# System Prompt
"""
You are a friendly order-taker at {restaurant_name}.
Menu: {menu_items}
Delivery areas: {areas}
Timings: {timings}

Your job:
1. Take food orders
2. Confirm items and quantity
3. Confirm delivery address
4. Give estimated delivery time
5. Confirm total amount
"""

# Function Tools
- place_order(items, address, phone, payment_mode)
- check_availability(item) → "Available" / "Out of stock"
- get_delivery_time(area) → "30-40 minutes"
- get_menu(category) → list of items with prices
```

## 14. Target Industries & Market Size

### Tier 1 - High Value (Rs 5,000-15,000/month per client)

| Industry | Use Case | Why they need it | Market Size (India) |
|----------|----------|------------------|---------------------|
| **Hospitals/Clinics** | Appointment booking, reminders, follow-up | Reduce receptionist load, 24/7 availability | 2.5L+ private clinics |
| **Car Showrooms** | Service reminders, test drive booking | Currently done manually, high missed-call rate | 30,000+ showrooms |
| **Real Estate** | Lead follow-up, site visit scheduling | Leads go cold if not called within 1 hour | 50,000+ builders |
| **Insurance** | Policy renewal calls, claim follow-up | Huge volume of repetitive calls | 500+ companies |

### Tier 2 - Medium Value (Rs 2,000-5,000/month per client)

| Industry | Use Case | Market Size |
|----------|----------|-------------|
| **Salons/Spas** | Appointment booking, reminders | 5L+ salons in India |
| **Coaching Institutes** | Enquiry follow-up, demo scheduling | 3L+ coaching centers |
| **Gyms/Fitness** | Membership renewal, class booking | 50,000+ gyms |
| **Restaurants** | Order taking, reservation | 7L+ restaurants |
| **Dental Clinics** | Appointment + reminders | 2L+ dental clinics |

### Tier 3 - Volume Play (Rs 1,000-2,000/month per client)

| Industry | Use Case | Market Size |
|----------|----------|-------------|
| **E-commerce** | Order confirmation, delivery updates | Growing rapidly |
| **Local Services** | Plumber, electrician booking | Huge unorganized market |
| **Event Management** | RSVP, guest confirmation | Seasonal but high volume |
| **Schools** | Fee reminders, PTM scheduling | 15L+ schools |

### Where to Start (Recommended)

```
Month 1-2: Pick ONE vertical
    Recommended: Salons OR Clinics (simple use case, clear ROI)
    Get 3-5 pilot clients at Rs 2,000-3,000/month

Month 3-4: Refine & Expand
    Fix issues from pilot
    Add 10-15 more clients in same vertical
    Build case studies

Month 5-6: Add second vertical
    Use same system, just change prompts
    Target: Hospital/Showroom (higher ticket)

Month 6+: Scale
    Hire 1 sales person
    Target: 50+ clients
    Revenue: Rs 2-5L/month
```

### Pricing Strategy

| Plan | Minutes/month | Price | Your cost | Profit |
|------|--------------|-------|-----------|--------|
| **Starter** | 200 min | Rs 2,000/month | Rs 700 | Rs 1,300 |
| **Growth** | 500 min | Rs 4,500/month | Rs 1,750 | Rs 2,750 |
| **Pro** | 1500 min | Rs 10,000/month | Rs 5,250 | Rs 4,750 |
| **Enterprise** | 5000 min | Rs 25,000/month | Rs 17,500 | Rs 7,500 |

### Revenue Projections

| Clients | Avg Plan | Monthly Revenue | Monthly Cost (AI + Hosting) | Profit |
|---------|----------|-----------------|----------------------------|--------|
| 5 | Rs 3,000 | Rs 15,000 | Rs 5,000 | Rs 10,000 |
| 20 | Rs 4,000 | Rs 80,000 | Rs 30,000 | Rs 50,000 |
| 50 | Rs 5,000 | Rs 2,50,000 | Rs 1,00,000 | Rs 1,50,000 |
| 100 | Rs 6,000 | Rs 6,00,000 | Rs 2,50,000 | Rs 3,50,000 |

## 15. Hosting Costs at Scale

| Stage | Clients | Infra | Monthly Cost |
|-------|---------|-------|-------------|
| **Start** | 0-10 | AWS Free Tier + Supabase Free | Rs 0 |
| **Grow** | 10-50 | EC2 t3.small + Supabase Pro | Rs 4,800 |
| **Scale** | 50-200 | EC2 t3.medium + Supabase Pro + Redis | Rs 6,100 |
| **Big** | 200+ | ECS/EKS cluster + RDS + Redis | Rs 15,000-25,000 |

## 16. Sales Pitch (What to Tell Clients)

### For Salon Owner:
> "Aapke salon ka apna AI receptionist. 24/7 appointment booking.
> Customer call kare toh AI slot check karke book kar dega.
> Aapko WhatsApp pe notification aayega. Rs 2,000/month."

### For Hospital:
> "AI-powered OPD booking system. Patient call kare toh doctor ki
> availability check karke appointment book. Automatic reminder bhi
> jayega. No missed appointments. Rs 5,000/month."

### For Showroom:
> "Service due customers ko automatic call. AI slot book karvata hai.
> 50% increase in service bookings. Rs 8,000/month."

### Key Selling Points:
- "24/7 available — never misses a call"
- "Speaks Hindi and English naturally"
- "Books appointments automatically"
- "Sends you WhatsApp notification for every booking"
- "Costs less than hiring a receptionist (Rs 15-20k/month)"
- "No missed leads — calls back within 5 minutes"

## 17. TODO - Features to Build

### Phase 1 - MVP (Week 1-2)
- [ ] Database integration (Supabase)
- [ ] Dynamic prompts based on client config
- [ ] save_appointment function tool
- [ ] Client dashboard (appointments list)
- [ ] Call duration limit

### Phase 2 - Growth (Week 3-4)
- [ ] Multi-tenant (client isolation)
- [ ] Webhook receiver (auto-trigger calls from website)
- [ ] WhatsApp notification on new appointment
- [ ] Client self-service dashboard
- [ ] Usage tracking & billing

### Phase 3 - Scale (Month 2-3)
- [ ] Admin super dashboard
- [ ] Auto-retry failed/unanswered calls
- [ ] Call recording (LiveKit Egress)
- [ ] Concurrent call queue (Redis/BullMQ)
- [ ] Analytics (call volume, conversion rate, avg duration)
- [ ] API for client integrations

### Phase 4 - Enterprise (Month 3+)
- [ ] Custom voice cloning per client
- [ ] CRM integrations (Zoho, Salesforce)
- [ ] Inbound call handling
- [ ] IVR menu before AI
- [ ] Payment collection on call (UPI)
- [ ] Multi-language per client
