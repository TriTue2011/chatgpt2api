[🇺🇸 English](README_VN_MCP_HUB.md) | [🇻🇳 Tiếng Việt](README_VN_MCP_HUB.vi.md)

**[🔙 Back to Main README](README.md)**

# 📖 VN MCP Hub User & Configuration Guide

This document provides detailed instructions on how to configure the **VN MCP Hub** Docker container to expand the AI's capabilities (Search, RAG, Tools).

---

## 🎛️ Detailed Tab Configuration in VN MCP Hub Studio

After installing, open the dashboard at `http://[SERVER_IP]:3030` → go to the **MCP tab** (Studio is integrated there; the separate `:8005/studio` page is gone) to start adding features for your AI.

### 1. Knowledge Base Tab (Local Memory - RAG)
- **Purpose**: RAG (Retrieval-Augmented Generation) is the knowledge repository you teach the AI. Instead of the AI searching the web, it reads the documents you provide to answer directly.
- **How to use**:
  - The interface provides sample repositories like: Electricity/Water, Medical First Aid, Law.
  - Click the **Create New KB** button.
  - Paste content (copy & paste) from company documents, workflows, or household guidelines (as text or Markdown) into the content box.
  - Name the knowledge base.
  - Click Save. The Hub will automatically chunk the text and insert it into Chroma DB (Vector Database). The AI will prioritize searching this repository first.
  - **Note**: Use Markdown format with Heading tags (`#`, `##`) so the Hub can accurately chunk the text by sections.

### 2. Multi-Search Tab (Search Configuration)
- **Purpose**: Select and configure international Search Engines so the AI can scan real-time data on the internet.
- **How to use**: 
  - Open the Multi-Search tab to see the list of search engines.
  - Toggle sources using the switches: 
    - **DuckDuckGo**: Best default, unlimited, and requires no API Key.
    - **Brave Search**: Requires an API Key from the Brave developer site. Excellent for news.
    - **Wikipedia**: Great for definitions and history.
  - When the AI is asked for information that the local RAG doesn't have, the Hub silently executes a Search.
  - **Important Note**: Do not enable too many sources (over 5) at once, as it will increase the AI's response latency.

### 3. Cloud Storage Tab (Cloud Sync)
- **Purpose**: If your server hard drive fails or you migrate to a new VPS, you could lose the effort spent teaching the AI in the Knowledge Base Tab. This tab uses Cloudflare R2 (or AWS S3) to automatically back up the entire Chroma DB to the cloud.
- **How to configure**: 
  - Enter the Endpoint URL (Example: `https://<account_id>.r2.cloudflarestorage.com`).
  - Enter the Access Key and Secret Key for your R2/S3 bucket.
  - Enter the Bucket Name.
  - Enable Auto Sync. The system will automatically take a snapshot and upload it to the Cloud at 2 AM every day.
  - You can also click **Force Sync Now** to synchronize immediately.
