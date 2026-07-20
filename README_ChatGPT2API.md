[🇺🇸 English](README_ChatGPT2API.md) | [🇻🇳 Tiếng Việt](README_ChatGPT2API.vi.md)

**[🔙 Back to Main README](README.md)**

# 📖 ChatGPT2API User & Configuration Guide

This document provides detailed instructions on how to add ChatGPT accounts to the system and master each Tab on the Docker **ChatGPT2API** Dashboard.

---

## 🔑 PART 1: ChatGPT Login & Account Import Methods

ChatGPT2API supports multiple ways to acquire and load accounts. Choose the method that best suits your needs.

### Method 1: Import via Access Token (Easiest - Recommended for Free accs)
Mainly used for Free ChatGPT accounts (or Plus if you cannot extract the Refresh Token). This token usually stays alive for 10-30 days depending on OpenAI's policies.

1. Open an Incognito/Private window in your browser to prevent interfering with your current session.
2. Log in normally at [https://chatgpt.com](https://chatgpt.com).
3. Once logged in, open a new tab and go to: `https://chatgpt.com/api/auth/session`
4. The screen will display a block of code. Highlight and copy the VERY LONG string of characters located right after `"accessToken": "..."` (Copy only the text inside the quotes, starting with `eyJ...`).
5. Go to ChatGPT2API Dashboard -> **Account Pool** Tab -> **Import Access Token**. Paste the copied code (you can paste multiple lines for multiple accounts).
6. **⚠️ MOST IMPORTANT NOTE**: After getting the Token, **DO NOT CLICK LOG OUT** in the browser. Simply close the incognito window completely. If you click Log Out, the Token will die instantly!

### Method 2: Import via Refresh Token (For Plus/Pro/Codex)
Used when you utilize OAuth features (Codex) to get a Refresh Token. Refresh Tokens have the advantage of being "Immortal"; the system automatically uses them to refresh your Access Token whenever it expires.

1. Obtain a Refresh Token string (via community token extraction tools).
2. Go to ChatGPT2API Dashboard -> **Account Pool** Tab -> Select **Import via Credentials** (or paste it into the Token box; the system auto-detects Refresh Token structures).
3. **Note**: Refresh Tokens keep your accounts in an Active state without manual refreshing. Ideal for building highly reliable Fallback Chains (Combos).

### Method 3: Automated Login via Captcha Solver (Google Login)
The system includes a `captcha-solver` module that automatically logs in via Google accounts to bypass Cloudflare.

1. Open the Captcha Solver VNC interface at port `http://[SERVER_IP]:6080`.
2. You will see an emulated browser. The system will control the mouse and keyboard to solve challenges automatically.
3. The module pushes the resulting `accessToken` directly into the ChatGPT2API internal database via the internal Docker network.

---

## 🎛️ PART 2: Detailed Tab Configuration (ChatGPT2API)

After accessing `http://[SERVER_IP]:3000` and entering your Auth Key, you will enter the Admin Dashboard.

### 1. Overview Tab
- No configuration needed here. It's a monitoring dashboard.
- Displays the number of Tokens saved by the RTK Optimizer algorithm, active requests, and success rates. Use this to monitor system bottlenecks (Status 429).

### 2. Account Pool Tab
- The headquarters for managing your fleet of accounts.
- You can **toggle** accounts on and off using the switches.
- The system periodically checks token Health. If an indicator turns Red (Error/Disabled), delete it and re-import a fresh Token (Method 1).

### 3. Providers Tab
- Adds power beyond ChatGPT.
- Out-of-the-box support for `gemini_free` (Free Gemini API Studio), `deepseek`, `groq`.
- **How to configure**:
  - Select a Provider from the dropdown.
  - Enter the Base URL (if custom) or the respective API Key.
  - Click Save. You can now use that provider's models (e.g., `gemini_free/auto`).

### 4. Combos Tab (Smart Routing & Fallback - MOST IMPORTANT)
This tab makes your system "Immortal" by grouping accounts into a single squad.
- Click **Create Combo**. Give it a name (e.g., `AI Agent`).
- **Fallback Chain**: This is the priority order. If #1 fails, it instantly falls back to #2.
  - Line 1 (Premium): Enter `cx/auto` (Draws from Plus/Pro accounts using Refresh Tokens).
  - Line 2 (Standard): Enter `chatgpt/auto` (Draws from the pool of Free Accounts loaded via Access Token).
  - Line 3 (Defense): Enter `gemini_free/auto` (Draws from the Providers tab).
  - Line 4 (Emergency): Enter `oc/auto` (OpenCode API requiring no token).
- Save. When integrating into Home Assistant, just set the model name to `AI Agent`, and the backend handles the routing behind the scenes.

### 5. Models Tab (Visibility Management)
- Apps like Open WebUI and n8n have a "Fetch Models List" feature. This tab allows you to hide unnecessary models to keep the list clean.
- Check the box next to the models you want to use (e.g., `chatgpt/auto`, `AI Agent`).

### 6. MCP Servers Tab (AI Expansions)
- AI cannot know today's weather or news without MCP.
- **How to configure**:
  - The MCP Hub already runs internally inside the container — no URL needed.
  - The screen lists Presets like "Web Search", "News", "Weather". Enable the tools you want.
  - Note: The more tools you enable, the longer the AI takes to think (3-4 basic tools recommended). All RAG/KB/R2 settings live in the MCP tab's sub-tabs.

### 7. Backup / System Tab
- Where you Export all your Tokens and configurations to a JSON file before migrating servers.
- Keep this Backup file extremely secure as it contains all your active Tokens.
