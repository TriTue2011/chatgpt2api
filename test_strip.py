import re

CITATION_RE = re.compile(r'【?[0-9†]*\s*citeturn[^\s】]*\s*】?', re.IGNORECASE)

def test_filtered():
    chunks = [
        "Dưới đây là ",
        "giá dầu thế giới theo các loại chính (spot/benchmark) gần đây — các số liệu này thể hiện giá dầu ",
        "thô trên thị trường quốc tế tính theo USD mỗi thùng ",
        "(USD/barrel): ",
        "citeturn",
        "2search0",
        "turn2search10\n\n",
        " Giá dầu thô chủ chốt"
    ]
    
    buffer = ""
    out = ""
    for delta in chunks:
        buffer += delta
        buffer = CITATION_RE.sub("", buffer)
        buffer = re.sub(r'[^\s]*citeturn[^\s]*', '', buffer, flags=re.IGNORECASE)
        if len(buffer) > 50:
            out += buffer[:-30]
            buffer = buffer[-30:]
            
    if buffer:
        buffer = CITATION_RE.sub("", buffer)
        buffer = re.sub(r'[^\s]*citeturn[^\s]*', '', buffer, flags=re.IGNORECASE)
        out += buffer
        
    with open("test_out.txt", "w", encoding="utf-8") as f:
        f.write(out)

test_filtered()
