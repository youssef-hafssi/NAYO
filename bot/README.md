# NAYO WhatsApp bot

After checkout, the client taps **"Confirmer ma commande sur WhatsApp"**. WhatsApp opens with this message already written:

> Bonjour NAYO, je confirme ma commande NAYO-1043 – 209 MAD – Salma

Because **the client writes first**, every reply we send in the next 24 hours is a free "service" message on the official WhatsApp Cloud API. The bot never sends paid template messages.

The bot then:
1. Thanks the client and asks for their city and full address.
2. Repeats the details back: "Salma, Agadir, Hay Salam rue 12, 209 MAD à la livraison — c'est bon ?"
3. On "oui / wakha / واخا", marks the order **confirmed** in your Google Sheet.

It answers in French, in Darija written in Latin letters (Arabizi), or in Darija written in Arabic script, whichever the client uses. It can change the quantity, cancel an order, and hand the conversation to you. When it hands over, it tells the client a team member will answer and sends you an alert on WhatsApp.

```
website ──POST /orders──▶ bot ──▶ Google Sheet "orders"   (you read it here)
client  ──WhatsApp──────▶ Meta ──POST /webhook──▶ bot ──▶ Gemini (understands the message)
                                                   └──▶ Postgres (bot memory: counter, history…)
```

---

## What you need (all free to start)

| Account | Used for |
|---|---|
| Meta (Facebook) developer account + a Meta Business portfolio | WhatsApp Cloud API |
| Google account | Google Sheet + service account, Gemini API key |
| Supabase account | free Postgres database for the bot's memory |
| Render (or Google Cloud) account | hosting the bot |
| GitHub account | Render deploys from a GitHub repository |

Write each secret into `bot/.env` as you go: copy `.env.example` to `.env` first. **Never commit `.env` or the service-account JSON file** (both are already in `.gitignore`).

---

## Step 1: WhatsApp Cloud API (Meta)

1. Go to **developers.facebook.com → My Apps → Create app**. Choose the use case **"Connect with customers through WhatsApp"** (or type **Business**), and link it to your Meta Business portfolio.
2. In the app, open **WhatsApp → API Setup**.
   - Meta gives you a **test number** first. It can only message up to 5 numbers that you verify. That's enough for testing.
   - Copy the **Phone number ID** into `WHATSAPP_PHONE_NUMBER_ID`. It's an ID, not the phone number itself.
   - When you're ready for real clients, **add your own business phone number** on the same page (Step 2, "Add phone number"). Verify it by SMS. Then copy *its* Phone number ID.
     A number registered on the Cloud API can no longer be used in the normal WhatsApp or WhatsApp Business app, so use a dedicated SIM.
   - Put that same number, digits only (e.g. `212663760384`), into the **website** `.env` as `VITE_WHATSAPP_NUMBER`.
3. **App secret:** go to **App settings → Basic → App secret → Show**. Put it in `WHATSAPP_APP_SECRET`. The bot uses it to check that webhook calls really come from Meta.
4. **Permanent token.** The token shown on API Setup expires after 24h. Create one that doesn't:
   1. Go to **business.facebook.com → Settings → Users → System users → Add**. Give it a name like `nayo-bot` and the **Admin** role.
   2. Click **Assign assets**. Add your **app** (full control) and your **WhatsApp account** (full control).
   3. Click **Generate new token**. Pick your app, set expiry to **Never**, and tick the permissions `whatsapp_business_messaging` and `whatsapp_business_management`.
   4. Copy the token into `WHATSAPP_TOKEN`. It's only shown once.
5. **Webhook.** Do this after the bot is reachable on the internet (Step 5 or Step 6):
   1. Go to **WhatsApp → Configuration → Webhook → Edit**.
   2. **Callback URL**: `https://YOUR-BOT-ADDRESS/webhook`
   3. **Verify token**: any long random string. Put the same string in `WHATSAPP_VERIFY_TOKEN`.
   4. Click **Verify and save**. Meta calls `GET /webhook` and the bot answers.
   5. Under **Webhook fields**, click **Subscribe** next to **messages**.
6. **API version:** `GRAPH_API_VERSION=v26.0` was current in November 2026. Check developers.facebook.com/docs/graph-api/changelog once in a while and update it.

> **Pricing:** replies inside the 24h window that the client opens are free on the Cloud API. Meta's rules change from time to time, so check developers.facebook.com/docs/whatsapp/pricing. The bot only ever sends free-form text, never templates.

## Step 2: Google Sheet + service account

1. Create a Google Sheet, e.g. "NAYO commandes". Copy the long ID from its URL (`docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`) into `GOOGLE_SHEET_ID`.
   The bot creates an `orders` tab with these columns:
   `order_number | created_at | name | phone | quantity | total | status | city | address | whatsapp_from | notes | updated_at`
   (`quantity` was added to your list so quantity changes are visible.)
2. Go to **console.cloud.google.com** and create a project, e.g. `nayo`.
3. Go to **APIs & Services → Library**, search for **Google Sheets API**, and click **Enable**.
4. Go to **IAM & Admin → Service accounts → Create service account**. Give it a name like `nayo-sheets`; it doesn't need any role.
5. Open the service account, then **Keys → Add key → Create new key → JSON**. A file downloads. Put it in `bot/` as `service-account.json`. That's the default `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Open the downloaded JSON and copy the `client_email` (…@….iam.gserviceaccount.com). In your Google Sheet, click **Share**, paste that email, and give it **Editor** access. Without this step the bot can't see the sheet.

### Simpler alternative: Google Sheet mirror (no service account)

The bot keeps its orders in Supabase (`ORDERS_BACKEND=db`) and **copies** every new or changed order to your
sheet through a small Apps Script. Each order is one row, updated in place.

1. Open the sheet → **Extensions → Apps Script**. Delete what's there and paste `bot/google-apps-script.gs`.
2. Replace `PASTE-THE-SHEET_WEBHOOK_SECRET-HERE` with a long random string. Put **the same string** in
   `SHEET_WEBHOOK_SECRET`, both on Vercel and in `bot/.env`.
3. Make sure the tab is called `Feuille 1`, or change `SHEET_NAME` in the script. If the tab has old content,
   empty it: the script writes the headers itself on the first order.
4. **Deploy → New deployment → Web app**: *Execute as* **Me**, *Who has access* **Anyone** → **Deploy**,
   then authorise. Copy the **Web app URL** (`https://script.google.com/macros/s/…/exec`) into `SHEET_WEBHOOK_URL`.
5. Redeploy the bot. If the sheet is ever unreachable, orders still work: the bot only logs a warning.

If you edit the script later, use **Deploy → Manage deployments → Edit → New version** to keep the same URL.

Status values in the sheet: `new` → `awaiting_details` → `confirmed` | `cancelled` | `needs_human`.
When a row is `needs_human`, the bot stays silent for that client and you take over in WhatsApp. To give a conversation back to the bot, change the status back to `awaiting_details`.

## Step 3: Gemini API key

1. Go to **aistudio.google.com → Get API key → Create API key**. Put it in `GEMINI_API_KEY`.
2. `GEMINI_MODEL=gemini-3.8-flash` was Google's current Flash model in November 2026. Check ai.google.dev/gemini-api/docs/models and change it if Google retires it.

> **Privacy:** on the **free** Gemini tier, Google may use what you send to improve its products. Client messages can contain addresses. Before launch, consider enabling billing on the key (the paid tier doesn't use your data that way, and a Flash model costs very little at this volume), and mention it in your privacy notice.

## Step 4: Supabase (the bot's memory)

Free hosts **wipe their disk** on every restart or redeploy, so the bot keeps its memory in Postgres. Its memory is:
- the order counter
- processed message IDs
- conversation history
- the 24h window
- the conversation stage
- the rate-limit counters

1. Go to **supabase.com → New project**. Pick a region close to Morocco (e.g. Frankfurt or Paris) and a strong database password.
2. Click **Connect**, then copy the **Transaction pooler** URI. It looks like `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres`.
3. Replace `[YOUR-PASSWORD]` with your password. Put the result in `DATABASE_URL` and set `STATE_BACKEND=postgres`.
   The bot creates its own tables on start.

> Supabase **pauses free projects after about a week without activity**. The uptime ping in Step 6 calls `/health`, which also queries the database, so the project stays active.

For local tests only, you can keep `STATE_BACKEND=sqlite`, which uses a `bot-state.db` file.

## Step 5: Run it on your computer (for testing)

In PowerShell, from the `bot` folder:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env      # then fill it in
.venv\Scripts\python -m pytest                 # 69 tests, no internet/keys needed
.venv\Scripts\python test_conversations.py     # ~30 sample messages through the REAL Gemini (needs GEMINI_API_KEY)
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Meta needs a public HTTPS address to reach your computer. Open a tunnel in a second window:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8000
```

It prints an address like `https://something.trycloudflare.com`. Use `https://something.trycloudflare.com/webhook` as the Meta callback URL (Step 1.5). `ngrok http 8000` works too.

For the website, set these in `nayo-landing/.env`, then restart `npm run dev`:
```
VITE_ORDER_ENDPOINT=http://localhost:8000/orders
VITE_ORDER_API_KEY=<same as ORDER_API_KEY>
```
Also add `http://localhost:5173` to `ALLOWED_ORIGINS` in the bot's `.env`.

**Test:** place an order on the site, tap the WhatsApp button, and send the message from a phone that is a verified test recipient. Then:
- The bot should answer within a few seconds.
- A new row should appear in the sheet.
- The terminal shows a log line for every step. Secrets are never logged, and phone numbers are masked.

**Owner alerts:** WhatsApp only lets the bot message you if *you* wrote to it in the last 24h. Send "salam" to the bot number from `OWNER_WHATSAPP` once a day, for example each morning. If an alert can't be delivered, the log says so, and the `notes` column in the sheet always records why an order needs you.

## Step 6: Deploy for free

### Option V: Vercel (website and bot in the same account)

The repository holds two Vercel projects. Import it twice from vercel.com → **Add New → Project**:

| Project | Root Directory | Framework |
|---|---|---|
| `nayo` (website) | `./` (repository root) | Vite (detected automatically) |
| `nayo-bot` (this bot) | `bot` | FastAPI: Vercel serves the `app` defined in `bot/index.py` |

For **nayo-bot**, add every variable from `.env.example` under **Settings → Environment Variables**, and also:
- `PROCESS_INLINE=true`. Required on Vercel: each message is handled before Meta gets its answer.
- `STATE_BACKEND=postgres` and `DATABASE_URL`: the Supabase pooler URL.
- `ORDERS_BACKEND=db` keeps orders in Supabase (Table Editor → orders), with no Google setup needed.
  Later, `ORDERS_BACKEND=sheets` with `GOOGLE_SERVICE_ACCOUNT_JSON` = the **whole JSON on one line** (there is no file on Vercel).
- `ALLOWED_ORIGINS` = the website's address, e.g. `https://nayo.vercel.app`.

For **nayo** (the website):
- `VITE_WHATSAPP_NUMBER` = the bot's WhatsApp number (digits only)
- `VITE_ORDER_ENDPOINT` = `https://<nayo-bot address>/orders`
- `VITE_ORDER_API_KEY` = the same value as `ORDER_API_KEY`

`VITE_` variables are written into the site when it's built, so **redeploy** after changing them.

Finally, set the Meta Callback URL to `https://<nayo-bot address>/webhook`.

### Option A: Render

1. Put the project on GitHub. A private repository is fine. Check that `.env` and `service-account.json` are **not** in it.
2. Go to **render.com → New → Web Service** and pick the repository. Use these settings:
   - **Root directory:** `bot`
   - **Runtime:** Python
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance type:** Free
3. Under **Environment**, add every variable from `.env.example`, plus `PYTHON_VERSION=3.11.9`. For the Google key, add a **Secret File** named `service-account.json` and set `GOOGLE_SERVICE_ACCOUNT_JSON=/etc/secrets/service-account.json`.
4. Deploy. Your bot's address is `https://nayo-bot.onrender.com` or similar. Then:
   - Set the Meta webhook to `https://nayo-bot.onrender.com/webhook`.
   - Set the website's `VITE_ORDER_ENDPOINT=https://nayo-bot.onrender.com/orders`.
   - Put the website's real domain in `ALLOWED_ORIGINS`.

**Render free services fall asleep after ~15 minutes without traffic.** Waking up takes 30–60 seconds. What already handles this:
- The checkout sends `GET /health` as soon as the page opens, to wake the bot early.
- If the bot still isn't up within 10 seconds, the client gets a backup number like `NAYO-W123456`. The order is kept in their browser and re-sent until the bot has it, so nothing is lost.
- Meta retries webhooks that fail, and the bot ignores the duplicates.

The first WhatsApp reply after a long quiet period can still be slow. To avoid that, create a free monitor on **cron-job.org** or **UptimeRobot** that calls `https://nayo-bot.onrender.com/health` every 10 minutes. One always-on service fits within Render's free monthly hours.

### Option B: Google Cloud Run

Cloud Run's free tier needs a billing account to be enabled, though light use like this stays inside the free quota.

```powershell
gcloud run deploy nayo-bot --source . --region europe-west1 --allow-unauthenticated `
  --max-instances 1 --set-env-vars "STATE_BACKEND=postgres,GRAPH_API_VERSION=v26.0,GEMINI_MODEL=gemini-3.8-flash,..."
```
Run it from the `bot` folder; it uses the `Procfile`. Put secrets in Secret Manager. Cloud Run also scales to zero, so it has cold starts too.

---

## How the bot decides

The AI (Gemini) only does two things:
- reads the client's message and returns a fixed JSON object: `reply`, `intent`, `city`, `address`, `quantity`, `needs_human`
- writes short answers to questions

**Python decides everything else**:
- **Statuses and totals:** every status change and every total. Total = quantity × 189 + 20 MAD flat shipping. The maximum quantity is 10; above that, the order goes to you.
- **Fixed messages:** the recap, confirmation, cancellation and new-total messages are fixed texts in the three languages, in `app/texts.py`. The AI never writes them.
- **Prompt injection:** the client's message is passed to the AI as marked data. The AI is told it cannot confirm, cancel, change prices or give discounts, and it has no way to do so anyway.
- **Guessable order numbers:** if someone writes from a different phone than the one on the order, the bot never shows the name or address. It asks them to type the name used on the order. A match ignores capital letters and accents. A wrong name sends the order to you.
- **Order matching:** the bot first looks for an order number in the message (`NAYO-1043`, or a backup `NAYO-W123456`). If there isn't one, it uses the most recent `new` or `awaiting_details` order for that phone. Phone formats like +212, 00212 and 06… are all treated as the same number.
- **Handing over to you:** for a complaint, a question outside the known facts, two messages in a row it doesn't understand, or the AI being down, the order becomes `needs_human`. The client gets "Un membre de notre équipe vous répond très vite 🙏" and you get an alert.
- **Limits:** at most 20 bot replies per phone per hour, and at most 10 orders per hour from one internet address. The bot never sends anything outside the 24h window.

The facts the AI may state are in `app/prompts.py`. Change them there, and only with facts you have confirmed: no formula claims, no delivery delays.

## Files

```
app/main.py      FastAPI: /orders, /webhook, /health
app/flow.py      conversation logic (statuses, matching, verification, hand-over)
app/ai.py        Gemini call, JSON validation, one retry
app/prompts.py   the AI's instructions and fixed facts
app/texts.py     fixed messages (fr / Arabizi / Arabic), language detection
app/orders.py    website order validation + numbering (idempotent per clientId)
app/store.py     Postgres/SQLite memory
app/sheets.py    Google Sheet
app/whatsapp.py  Cloud API send + signature check
index.py         Vercel entry point (FastAPI preset)
tests/           pytest (AI, Sheet and WhatsApp are mocked)
test_conversations.py   real-AI smoke test
```
