import re
from typing import Iterator
from services.protocol.conversation import CITATION_RE

def filter_streamed_text(text_iterator: Iterator[str]) -> Iterator[str]:
    """
    A sliding window stream filter to safely strip ChatGPT citations (citeturn...).
    It buffers a small amount of text to prevent cutting the citation marker in half.
    """
    buffer = ""
    for chunk in text_iterator:
        buffer += chunk
        
        # Apply stripping to the buffer
        buffer = CITATION_RE.sub("", buffer)
        buffer = re.sub(r'[^\s]*citeturn[^\s]*', '', buffer, flags=re.IGNORECASE)
        
        # Yield everything except the last 30 characters (which might be a partial 'citeturn')
        if len(buffer) > 50:
            yield_text = buffer[:-30]
            buffer = buffer[-30:]
            yield yield_text
            
    if buffer:
        buffer = CITATION_RE.sub("", buffer)
        buffer = re.sub(r'[^\s]*citeturn[^\s]*', '', buffer, flags=re.IGNORECASE)
        yield buffer
