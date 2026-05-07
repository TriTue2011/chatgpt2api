import sys
from services.protocol.conversation import extract_and_remove_tool_calls

text = """ **Giá xăng dầu **ở Việt Nam hôm nay (06/05/2026) gần như *giữ nguyên* theo mức niêm yết mới nhất và chưa có điều chỉnh trong ngày: citeturn0search29

Giá tham khảo tại hệ thống Petrolimex (đơn vị: VNĐ/lít):
citeturn0search29  

- Xăng RON 95‑III: ~ 23.750 đ/lít (Vùng 1) — ~24.220 đ/lít (Vùng 2)  
- Diesel: ~ 28.170 đ – 29.430 đ/lít tùy loại  
- Dầu hỏa: ~ 31.980 đ – 32.610 đ/lít citeturn0search29

 Đây là giá bán lẻ hiện được niêm yết theo kỳ điều hành gần nhất (29/4/2026) và *đã bao gồm thuế VAT + thuế môi trường*. citeturn0search29
"""

cleaned, tools = extract_and_remove_tool_calls(text)

if "citeturn0search29" in cleaned:
    print("FAILED! IT LEAKED!")
else:
    print("SUCCESS! IT WAS STRIPPED!")
    
with open("test_strip_full_out.txt", "w", encoding="utf-8") as f:
    f.write(cleaned)
