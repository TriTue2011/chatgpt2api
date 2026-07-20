import asyncio
import json
import time

from src.browser_pool import pool
from src.settings import settings
from utils.log import logger

async def sniff_flow():
    """Mở profile google-fx qua pool để anh thao tác trên noVNC và bóc payload."""
    print("Khởi động browser pool...")
    await pool.start()
    
    # Mở page với profile google-fx hiện có trên hệ thống
    async with pool.page(profile="google-fx", headless=False) as page:
        log_file = open("/data/flow_network_log.txt", "w", encoding="utf-8")
        
        def handle_request(request):
            if "aisandbox" in request.url or "flow" in request.url:
                try:
                    if request.post_data:
                        log_file.write(f"\n[REQUEST] {request.url}\n")
                        log_file.write(f"Payload: {request.post_data}\n")
                        log_file.flush()
                except:
                    pass

        def handle_response(response):
            if "aisandbox" in response.url or "flow" in response.url:
                try:
                    # Chạy ngầm việc đọc text để không block event loop
                    asyncio.create_task(save_response(response))
                except:
                    pass
                    
        async def save_response(response):
            try:
                text = await response.text()
                log_file.write(f"\n[RESPONSE] {response.url}\n")
                log_file.write(f"Body: {text}\n")
                log_file.flush()
            except:
                pass

        page.on("request", handle_request)
        page.on("response", handle_response)
        
        print("Đang mở trang Flow... Anh vui lòng truy cập vào noVNC (thường là http://localhost:6080) để thao tác nhé.")
        await page.goto("https://labs.google/fx/vi/tools/flow")
        
        # Giữ page mở trong 30 phút để anh thoải mái thao tác
        print("Đã gắn thiết bị nghe lén. Sẽ ghi log vào /data/flow_network_log.txt")
        await asyncio.sleep(1800)
        
        log_file.close()
        
    await pool.stop()

if __name__ == "__main__":
    asyncio.run(sniff_flow())
