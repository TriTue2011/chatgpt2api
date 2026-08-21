import { WebSocket } from 'ws';

const clients = new Set();

export function registerWebSocketClient(ws) {
  clients.add(ws);
  ws.on('close', () => clients.delete(ws));
  ws.on('error', () => clients.delete(ws));
}

export function broadcastMessage(message) {
  for (const client of clients) {
    if (client.readyState !== WebSocket.OPEN) continue;
    try {
      client.send(message);
    } catch (error) {
      console.warn(`[WebSocket] Gui client loi: ${error.message}`);
      try { client.terminate(); } catch { /* ignore */ }
      clients.delete(client);
    }
  }
}

export function getWebSocketClientCount() {
  return clients.size;
}

export function closeAllWebSocketClients() {
  for (const client of clients) {
    try { client.close(1001, 'Server shutting down'); } catch { /* ignore */ }
  }
  clients.clear();
}
