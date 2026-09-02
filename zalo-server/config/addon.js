// config/addon.js
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Default data directory path
let dataDirectory = process.env.DATA_DIRECTORY || '/config/zalo_bot';

// Từ khóa "trả lời cả tin của chính chủ": bot chạy trên CHÍNH tài khoản người
// dùng thì tin chủ tự gõ bị Zalo đánh isSelf. Add-on gắn cờ `self_reply=true`
// cho tin isSelf CÓ chứa từ khóa này, để downstream (gateway/automation) biết
// đây là lệnh của chủ chứ không phải câu bot tự sinh. Rỗng = không gắn (mặc
// định), giữ nguyên hành vi cũ. Nguồn: env (docker compose) hoặc options.json (HA).
let selfReplyKeyword = process.env.SELF_REPLY_KEYWORD || '';

// Function to load Home Assistant options if available
export function loadHomeAssistantOptions() {
  try {
    // Check if we're running in Home Assistant
    const optionsPath = '/data/options.json';
    if (fs.existsSync(optionsPath)) {
      const options = JSON.parse(fs.readFileSync(optionsPath, 'utf8'));
      if (options.data_directory) {
        dataDirectory = options.data_directory;
        console.log(`Loaded data directory from Home Assistant options: ${dataDirectory}`);
      }
      if (typeof options.self_reply_keyword === 'string') {
        selfReplyKeyword = options.self_reply_keyword.trim();
        if (selfReplyKeyword) console.log('Loaded self_reply_keyword from Home Assistant options');
      }
    }
  } catch (error) {
    console.error('Error loading Home Assistant options:', error);
  }
  
  // Create data directory if it doesn't exist
  if (!fs.existsSync(dataDirectory)) {
    try {
      fs.mkdirSync(dataDirectory, { recursive: true });
      console.log(`Created data directory: ${dataDirectory}`);
    } catch (error) {
      console.error(`Error creating data directory: ${error.message}`);
    }
  }
  
  return dataDirectory;
}

// Get the absolute data directory path
export function getDataDirectory() {
  return dataDirectory;
}

// Từ khóa "trả lời cả tin của chính chủ" (rỗng = tính năng tắt).
export function getSelfReplyKeyword() {
  return selfReplyKeyword;
}

// Get the path to a file within the data directory
export function getDataFilePath(filename) {
  return path.join(dataDirectory, filename);
}
