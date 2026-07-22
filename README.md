[🇺🇸 English](README.md) | [🇻🇳 Tiếng Việt](README.vi.md)

# 🚀 ChatGPT2API - Ultimate AI Gateway & VN MCP Hub

**📚 Documentation Links (Click to view details):**
- **[📘 Hướng dẫn TIẾNG VIỆT chi tiết từng tab, từng ô cài đặt — đọc trước nếu mới cài lần đầu](HUONG_DAN.md)**
- **[📖 ChatGPT2API User & Login Guide](README_ChatGPT2API.md)**
- **[🧠 VN MCP Hub RAG & Configuration Guide](README_VN_MCP_HUB.md)**

**ChatGPT2API** is a comprehensive project that transforms your ChatGPT Web account into a standard OpenAI API, while acting as a powerful **AI Agent Backend**. This version is specially optimized for smart home systems like **Home Assistant** (filtering formats so TTS smart speakers can read 100% naturally), and is perfect for **Open WebUI**, **n8n**, and any application supporting the OpenAI API standard.

Included is the **VN MCP Hub (Model Context Protocol Hub)** - providing 20+ custom MCP servers to expand your AI's brain with web search, weather updates, news, finance, law, and RAG (Knowledge Base) capabilities.

The project also comes with a **Captcha Solver** to handle Cloudflare barriers and protect automated logins.

---

## 🌟 Key Features

### 🧠 Core ChatGPT2API
- **10+ AI Providers**: Supports ChatGPT Web (Free/Plus), Codex OAuth, OpenCode (Free without account), Gemini (Free AI Studio), DeepSeek, Groq, Mistral, NVIDIA NIM, etc.
- **Model Combo Orchestration**: Smart automatic fallback mechanism. If API A fails, it automatically switches to API B without disrupting the user experience.
- **Smart Speaker (TTS) Optimization**: Smart RTK filter automatically removes Markdown formats (`#`, `*`, `-`) for a smooth, natural voice.
- **Web Dashboard**: Intuitive management interface allowing easy account addition, model configuration, token tracking, and backup.
- **RTK Token Optimizer**: An algorithm that saves 60-90% of token consumption while maintaining the quality of answers.

### 🔌 VN MCP Hub
- **8 Core MCPs**: Built-in Weather (4 sources), News (6 sources), Exchange Rates/Gold, Lunar Calendar, DuckDuckGo Search, Vietnam Law Lookup, Traffic Fines, Stocks.
- **7 Knowledge Base RAGs**: Vietnam's electricity/water, medical first aid, education, foreign languages, science, nature, and society data.
- **Federated Multi-Search**: 9 international search engines running in parallel (Brave, Mojeek, PubMed, etc.).
- **Studio UI**: Intuitive management, creating new KBs (Knowledge Base) from Markdown, Cloudflare R2 storage.
- **OfficeCLI MCP**: Create/read/edit Word, Excel, PowerPoint under `/app/data/office` (see `docs/INTEGRATIONS_OFFICECLI_DEEPTUTOR.md`).
- **DeepTutor sidecar**: Optional tutoring app (`deploy/deeptutor/`) that uses this gateway as an OpenAI-compatible backend.

### 🛡️ Captcha Solver
- **Bypass Cloudflare/Turnstile**: Automatically handles ChatGPT's captcha protection.
- **VNC/API Management**: Supports visual debugging via port 6080.

---

## 💻 System Requirements

| Component | Minimum | Recommended |
| :--- | :--- | :--- |
| **OS** | Linux (Ubuntu/Debian), Raspberry Pi OS, Synology/QNAP | Linux (Ubuntu/Debian) |
| **RAM** | 2GB | 4GB+ (all-in-one image bundles a browser) |
| **Disk** | 5GB | 20GB+ (For RAG and Cache storage) |
| **Software** | Docker & Docker Compose | Latest Docker version (24.0+) |

---

## 🚀 Step-by-Step Installation Guide

Below is a detailed installation guide from basic to advanced on multiple platforms.

### Environment Preparation
Before you begin, your server needs to have Docker and Docker Compose installed.
- **Install Docker on Linux (Ubuntu/Debian):**
  ```bash
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  ```

### Method 1: Quick Install via Docker Compose (Recommended)

As of this version, **ChatGPT2API + VN MCP Hub + Captcha Solver are merged into ONE image / ONE container** (`c2a`). Inside it, `supervisord` runs them all together: the API gateway (port 80), MCP Hub (internal 8005), Captcha Solver (internal 8010), and the noVNC browser (port 6080) for manual web logins. No more separate Docker services for these components.

#### Docker: Full vs Lite

| | **Full** (default) | **Lite** |
| :--- | :--- | :--- |
| Files | `Dockerfile` + `docker-compose.yml` | `Dockerfile.lite` + `docker-compose.lite.yml` |
| Contents | API gateway + Web UI + browser stack (Chromium/noVNC for manual logins) + Captcha Solver + VN MCP Hub + embedded Zalo server | API core only (`main_lite.py` / `api/app_lite.py`) — no Web UI, no browser, no captcha, no MCP hub |
| RAM | 4GB+ recommended (browser bundled) | runs comfortably on ~2GB machines |
| Use when | You want the dashboard, web-login providers (ChatGPT/Gemini/Flow web), HA/MCP tools | You only need the OpenAI-compatible API endpoints on a small VPS/board |

Run the Lite variant with:
```bash
docker compose -f docker-compose.lite.yml up -d
```
> ⚠️ noVNC (`6080`) is published for LAN captcha logins — set **`VNC_PASSWORD`**. Never expose `6080` to the open internet. Bind `127.0.0.1:6080` only if you use SSH tunnel. Keep `10600`/`3001` on LAN if Home Assistant runs on another host (`10600` = Wyoming multi vi/en).

**Step 1: Initialize directory**
Create a directory to store the configuration and data for the application:
```bash
mkdir -p /opt/chatgpt2api
cd /opt/chatgpt2api
```

**Step 2: Create docker-compose.yml file**
Use the `nano` editor to create the file:
```bash
nano docker-compose.yml
```
Paste the following code into the file:
```yaml
services:
  # All-in-one: API gateway + VN MCP Hub + Captcha Solver in one container
  c2a:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: c2a
    restart: unless-stopped
    ports:
      - "3030:80"      # API + web dashboard
      - "6080:6080"    # noVNC (set VNC_PASSWORD; LAN only, not WAN)
      - "3001:3001"    # zalo-server (HA/integration on LAN)
      - "10600:10600"  # Wyoming multi — vi/en TTS+STT (HA often on another host)
    volumes:
      # Single data dir: accounts, config, KB + chroma, browser profiles
      - ./c2a-data:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=your_secure_password   # CHANGE THIS PASSWORD
      - CAPTCHA_SOLVER_API_KEY=your_secure_password # CHANGE THIS PASSWORD
      - VNC_PASSWORD=your_vnc_password               # REQUIRED when using :6080
      - STORAGE_BACKEND=json
```
> Note: MCP Hub (8005) and Captcha API (8010) run only inside the container, so they don't need to be published.
> Homelab: do **not** bind `10600`/`3001` to `127.0.0.1` if Home Assistant is on a different machine.

Save the file by pressing `Ctrl + X`, then press `Y` and `Enter`.

**Step 3: Start the system**
Run the following command to download the image and start the containers:
```bash
docker compose up -d
```
Once complete, you can access the admin dashboard at `http://[SERVER_IP]:3030`.

### Method 2: Installation via Portainer

If you use Portainer to manage Docker:
1. Log into Portainer, select your environment (Local/Primary).
2. Go to the **Stacks** section in the left menu -> Click **Add stack**.
3. Name the stack `chatgpt-ai-system`.
4. In the Web editor section, paste the `docker-compose.yml` code from above.
5. Make sure to edit `CHATGPT2API_AUTH_KEY` to your own secure password.
6. Scroll to the bottom and click **Deploy the stack**. Wait 1-2 minutes for the system to download and launch.

---

## 🎛️ Deep Dive into ChatGPT2API Dashboard

> **👉 SEE DETAILS:** For ChatGPT Login methods (Access Token/Refresh Token) and in-depth Tab configurations, check out: **[📖 ChatGPT2API User Guide](README_ChatGPT2API.md)**

After installation, access the admin page at `http://[SERVER_IP]:3030` and log in with your password (Auth Key). The left-hand interface consists of main tabs. Here's how to master each one:

### 1. Overview Tab
- **Purpose**: Central dashboard monitoring system health in real-time.
- **Features**:
  - View active Requests, Success Rate.
  - Statistical chart of Tokens saved thanks to the Optimizer algorithm.
  - Quick tracking of "Active" or "Error" accounts.

### 2. Account Pool Tab
- **Purpose**: Manage free and paid (Plus/Pro) ChatGPT Web accounts.
- **How to safely get an Access Token**:
  1. Open an Incognito browser window, log in to [chatgpt.com](https://chatgpt.com).
  2. Paste `https://chatgpt.com/api/auth/session` into the address bar.
  3. Copy the very long string after `"accessToken":`. (Note: Close the window, DO NOT LOG OUT).
- **How to use this Tab**:
  - Click **Import Access Token**.
  - Paste your tokens (one token per line). Click Confirm.
  - The system automatically classifies it as Free or Plus. You can toggle each account. If it turns red, the Token has expired; delete and re-import.

### 3. Providers Tab
- **Purpose**: Use when you don't want to rely entirely on ChatGPT and want to use Gemini, DeepSeek, Groq.
- **How to use**:
  - Select the provider (e.g., **Gemini AI Studio**).
  - Paste the API Key obtained from Google into the blank field.
  - Click **Save**. The system is now ready to use third-party Models with the corresponding prefix (like `gemini_free/auto`).

### 4. Combos Tab (Smart Routing & Fallback - Most Important)
- **Purpose**: Create a smart processing flow so the AI never "freezes" if one source fails.
- **How to configure "Immortality"**:
  1. Click **Create Combo**. Give it a memorable name: `AI Agent`.
  2. In the Fallback Chain section, add in order from best to backup:
     - Line 1: `cx/auto` (Codex OAuth - best if you have it).
     - Line 2: `chatgpt/auto` (Regular ChatGPT account).
     - Line 3: `gemini_free/auto` (Google Gemini API backup 1).
     - Line 4: `oc/auto` (OpenCode - Final backup requiring no token).
  3. **Mechanism**: When you call the `AI Agent` model, the system tries `cx/auto`. If it hits a 429 error or network drop, it instantly (under 1 second) switches to `chatgpt/auto`, ensuring a response is always returned to the Smart Speaker.

### 5. Models Tab
- **Purpose**: Show/Hide available models so applications like n8n, OpenWebUI can scan them.
- **How to use**: You can enable (green check) or disable any model you don't want to appear in the `/v1/models` API. If using Codex, ensure you select the exact Prefix name (like `cx/gpt-4o`).

### 6. MCP Servers & Studio Tab (AI Expansion Tools)
- **Purpose**: Attach "Hands and feet", "Eyes and nose" to the AI (Google Search, weather, news, RAG) and manage all MCP/RAG settings.
- **How to use**:
  1. The MCP Hub already runs internally — just click **Install/Enable** the Presets (Weather, Stocks, Law…).
  2. All former `:8005/studio` settings now live in this tab's sub-tabs: **Knowledge Base, RAG Settings, R2 Storage, External MCP, Ingest**.
  3. When activated, the AI Agent automatically calls the tools whenever a user asks.

### 7. Backup / System Tab
- **Purpose**: Backup configurations and accounts in case of server migration.
- **How to use**: 
  - **Export**: Exports a JSON file of all API Keys, Access Tokens.
  - **Import 9router Backup**: Supports importing backup files from the old specialized 9router system directly.

---

## 🧠 Deep Dive into Studio (inside the MCP Tab)

> **👉 SEE DETAILS:** For instructions on teaching the AI (RAG) and configuring search engines, check out: **[📖 VN MCP Hub Configuration Guide](README_VN_MCP_HUB.md)**

Studio is now integrated into the dashboard's **MCP tab** (sub-tabs: Knowledge Base, RAG Settings, R2 Storage, External MCP, Ingest) — there is no separate `:8005/studio` page anymore.

### 1. Knowledge Base Tab (Local Memory - RAG)
- **Concept**: RAG (Retrieval-Augmented Generation) is the knowledge repository you teach the AI.
- **How to use**:
  - Pre-built repositories are available: Electricity/Water, Medical First Aid, Law.
  - You can click **Create New KB**, paste content (copy & paste) from company documents or family guides (as text or Markdown) into the content box. The Hub will automatically chunk and insert it into Chroma DB. The AI will later prioritize searching this repository before Googling.

### 2. Multi-Search Tab
- **Purpose**: Select international Search Engines for the AI to scan real-time data.
- **How to use**: Enable/disable sources: DuckDuckGo (Best default), Brave Search (Requires API Key), Wikipedia. If local RAG has no answer, the Hub will silently call Search.

### 3. Cloud Storage Tab
- **Purpose**: If the server hard drive fails, you lose the effort of teaching the AI. This tab uses Cloudflare R2 (or AWS S3) for backup.
- **Configuration**: Enter Endpoint URL, Access Key, Secret Key of the R2 bucket. Enable Auto Sync at 2 AM.

---

## 🏠 Detailed Integration Guide (Home Assistant, n8n, WebUI)

### 1. Integration into Home Assistant (As a Virtual Assistant)

1. In Home Assistant, go to **Settings** -> **Devices & Services** -> **Add Integration**.
2. Search for **OpenAI Conversation**.
3. Fill in the configuration:
   - **API Key**: `your_secure_password` (The CHATGPT2API_AUTH_KEY variable).
   - **Base URL**: `http://[SERVER_IP_CHATGPT2API]:3030/v1`
4. Click **Submit**. 
5. Click the **Configure** button on the newly added Integration, select the model as `AI Agent` (The Combo Name you created in the Combos Tab).

#### 🔊 Voice Optimization (TTS) for Smart Speakers
Open **Settings** -> **Voice Assistants** -> Select your assistant. In the **Instructions** section, paste the following so the AI answers most naturally:

> *"You are a smart home virtual assistant. Please answer extremely concisely, naturally, and like human spoken language so the TTS system can read smoothly. Absolutely DO NOT use formatting characters (like asterisks *, hashes #, bullet points -). Do not use lists, minimize parentheses. Answer straight to the point of the question. IMPORTANT: Even when retrieving data from Web Search or MCP, absolutely do not use list formats."*

### 2. Integration with Open WebUI
1. Open Admin Panel -> **Settings** -> **Connections** -> **OpenAI API**.
2. Turn on the activation switch.
3. **URL**: `http://[SERVER_IP_CHATGPT2API]:3030/v1`
4. **Key**: `your_secure_password`
5. Click the Refresh icon to load the Model list.

### 3. Integration with n8n
1. Drag the **OpenAI Chat Model** node.
2. In the **Credential** section, create a new OpenAI API.
3. Fill in the Base URL (under Override): `http://[SERVER_IP_CHATGPT2API]:3030/v1`
4. Fill in the API Key.

---

## 🛠️ API Endpoints & Model Prefix List

### Model Prefix
| Prefix | Provider | Note |
| :--- | :--- | :--- |
| `cx/` | Codex OAuth | For ChatGPT Pro/Plus, automatically gets new tokens. |
| `chatgpt/` | ChatGPT Web | For Free accounts. |
| `oc/` | OpenCode | Free secondary source, no login required. |
| `gemini_free/` | Gemini AI Studio | Requires Google API Key (Free). |
| `custom:...` | Custom Provider | Any API supporting the OpenAI standard. |

---

## 🚨 Troubleshooting

| Condition | Cause & Solution |
| :--- | :--- |
| **Container keeps crashing (Crash loop)** | View logs with: `docker logs chatgpt2api`. Usually due to incorrect environment variable syntax. |
| **Assistant answers with `#`, `*` making it hard to hear** | Recheck the System Prompt in Home Assistant. Make sure you added the instruction not to use formatting. |
| **Error 400 "Model not supported"** | You are using a non-existent model. Go to Combos/Models Tab to check if the model has the correct Prefix format (e.g., `chatgpt/auto`). |
| **ChatGPT account keeps Expiring** | Because you clicked Log Out in the browser when getting the Token. Solution: Get a new Token from an Incognito tab and close the window, DO NOT Log Out. |
| **MCP Tools not responding or empty** | The MCP Hub runs inside the container. Test from the host: `docker exec c2a curl -s http://127.0.0.1:8005/health`. |
| **Out of disk** | Due to old docker logs or cache (especially Chroma DB). Run command: `docker system prune -af` |

---

## 🔄 Updating to a New Version

When there is an update from the developer, you do not need to delete data. Just run:

```bash
cd /opt/chatgpt2api
docker compose pull
docker compose up -d
```
The system will automatically update the image; all your account configurations or RAGs are kept 100% intact.
