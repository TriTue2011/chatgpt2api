import { useState, useEffect, useRef } from 'react';
import { Send, Mic, MicOff, Settings } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('openai_api_key') || '');
  const [isSetup, setIsSetup] = useState(!!localStorage.getItem('openai_api_key'));
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [isSleeping, setIsSleeping] = useState(false);
  const [isTalking, setIsTalking] = useState(false);
  
  const [jawOffset, setJawOffset] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);
  const animationFrameRef = useRef<number>();
  
  // Sleep timer
  const lastInteractionTime = useRef<number>(Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      if (Date.now() - lastInteractionTime.current > 5 * 60 * 1000) {
        setIsSleeping(true);
      }
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const resetTimer = () => {
    lastInteractionTime.current = Date.now();
    if (isSleeping) setIsSleeping(false);
  };

  const handleSetup = (e: React.FormEvent) => {
    e.preventDefault();
    if (apiKey) {
      localStorage.setItem('openai_api_key', apiKey);
      setIsSetup(true);
    }
  };

  // Lip sync animation loop
  const updateLipSync = () => {
    if (!analyserRef.current || !dataArrayRef.current) return;
    
    analyserRef.current.getByteFrequencyData(dataArrayRef.current);
    
    // Calculate average volume
    let sum = 0;
    for (let i = 0; i < dataArrayRef.current.length; i++) {
      sum += dataArrayRef.current[i];
    }
    const average = sum / dataArrayRef.current.length;
    
    // Map volume to jaw movement (0 to 15px down)
    const movement = Math.min(15, (average / 100) * 15);
    setJawOffset(movement);

    if (isTalking) {
      animationFrameRef.current = requestAnimationFrame(updateLipSync);
    }
  };

  useEffect(() => {
    if (isTalking) {
      updateLipSync();
    } else {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      setJawOffset(0);
    }
  }, [isTalking]);

  const initAudio = () => {
    if (!audioContextRef.current && audioRef.current) {
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      audioContextRef.current = new AudioContextClass();
      analyserRef.current = audioContextRef.current.createAnalyser();
      
      const source = audioContextRef.current.createMediaElementSource(audioRef.current);
      source.connect(analyserRef.current);
      analyserRef.current.connect(audioContextRef.current.destination);
      
      analyserRef.current.fftSize = 256;
      const bufferLength = analyserRef.current.frequencyBinCount;
      dataArrayRef.current = new Uint8Array(bufferLength);
    }
    if (audioContextRef.current?.state === 'suspended') {
      audioContextRef.current.resume();
    }
  };

  const speak = async (text: string) => {
    try {
      setIsTalking(true);
      initAudio();
      
      const res = await fetch('https://api.openai.com/v1/audio/speech', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: 'tts-1',
          input: text,
          voice: 'nova',
        }),
      });

      if (!res.ok) throw new Error('TTS failed');
      
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      if (audioRef.current) {
        audioRef.current.src = url;
        audioRef.current.play();
        audioRef.current.onended = () => {
          setIsTalking(false);
          URL.revokeObjectURL(url);
        };
      }
    } catch (e) {
      console.error(e);
      setIsTalking(false);
    }
  };

  const sendMessage = async (text: string, triggerVoiceResponse: boolean = false) => {
    if (!text.trim()) return;
    
    resetTimer();
    const newMessages: Message[] = [...messages, { role: 'user', content: text }];
    setMessages(newMessages);
    setInput('');

    try {
      const res = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: 'gpt-3.5-turbo',
          messages: [
            { role: 'system', content: 'You are a helpful, friendly AI assistant. Keep responses concise.' },
            ...newMessages
          ],
        }),
      });

      if (!res.ok) throw new Error('Chat API failed');
      
      const data = await res.json();
      const botResponse = data.choices[0].message.content;
      
      setMessages([...newMessages, { role: 'assistant', content: botResponse }]);

      if (triggerVoiceResponse) {
        speak(botResponse);
      }
    } catch (e) {
      console.error(e);
      setMessages([...newMessages, { role: 'assistant', content: 'Oops! Something went wrong.' }]);
    }
  };

  const toggleRecording = () => {
    resetTimer();
    const SpeechRecognition = window.SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Your browser doesn't support speech recognition.");
      return;
    }

    if (isRecording) {
      setIsRecording(false);
      // We assume it stops automatically or we rely on onend event
      return;
    }

    setIsRecording(true);
    const recognition = new SpeechRecognition();
    recognition.lang = 'vi-VN'; // Assuming Vietnamese, or auto
    recognition.interimResults = false;
    
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInput(transcript);
      sendMessage(transcript, true); // True means respond with voice!
      setIsRecording(false);
    };

    recognition.onerror = () => {
      setIsRecording(false);
    };
    
    recognition.onend = () => {
      setIsRecording(false);
    };

    recognition.start();
  };

  if (!isSetup) {
    return (
      <div className="setup-screen glass">
        <h1>AI Avatar Setup</h1>
        <p>Enter your OpenAI API key to get started.</p>
        <form onSubmit={handleSetup}>
          <input 
            type="password" 
            className="text-input" 
            placeholder="sk-..." 
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            required
          />
          <button type="submit">Start</button>
        </form>
      </div>
    );
  }

  return (
    <>
      {/* Hidden audio element for TTS */}
      <audio ref={audioRef} style={{ display: 'none' }} crossOrigin="anonymous" />
      
      <div className="avatar-container" onClick={resetTimer}>
        <img 
          src="/avatar.jpg" 
          alt="Avatar Base" 
          className={`avatar-image ${isSleeping ? 'sleeping' : ''}`}
        />
        {/* Jaw overlay for lip sync simulation */}
        <img 
          src="/avatar.jpg" 
          alt="Avatar Jaw" 
          className={`avatar-jaw ${isSleeping ? 'sleeping' : ''}`}
          style={{ transform: `translateY(${jawOffset}px)` }}
        />
        {isSleeping && (
          <div className="zzz">Zzz</div>
        )}
      </div>

      <div className="chat-container glass" onClick={resetTimer}>
        <div className="messages">
          {messages.map((m, i) => (
            <div key={i} className={`message ${m.role}`}>
              {m.content}
            </div>
          ))}
          {messages.length === 0 && (
            <div className="message bot" style={{ opacity: 0.7 }}>
              Hello! I'm here. Send a message or tap the mic to speak to me. If you use voice, I'll reply with voice!
            </div>
          )}
        </div>
        
        <div className="input-area">
          <input
            type="text"
            className="text-input"
            placeholder="Type a message..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                sendMessage(input, false);
              }
            }}
          />
          <button 
            className={`icon-btn ${isRecording ? 'recording' : ''}`}
            onClick={toggleRecording}
          >
            {isRecording ? <MicOff size={20} /> : <Mic size={20} />}
          </button>
          <button 
            className="icon-btn"
            style={{ background: 'rgba(255,255,255,0.2)' }}
            onClick={() => sendMessage(input, false)}
          >
            <Send size={20} />
          </button>
        </div>
      </div>
    </>
  );
}
