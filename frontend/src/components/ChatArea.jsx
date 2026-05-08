import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2, Copy, Check, Square, Paperclip, Mic, X, Image as ImageIcon, ThumbsUp, ThumbsDown } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { atomDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const CodeBlock = ({ node, inline, className, children, ...props }) => {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || '');
  const codeText = String(children).replace(/\n$/, '');

  const copyToClipboard = () => {
    navigator.clipboard.writeText(codeText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!inline && match) {
    return (
      <div className="relative group rounded-xl overflow-hidden my-3 border border-gray-700/60 shadow-xl">
        <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700/60 font-sans">
          <span className="text-[0.7rem] uppercase tracking-wider font-semibold text-gray-400 select-none">{match[1]}</span>
          <button
            onClick={copyToClipboard}
            className="text-gray-400 hover:text-white transition-colors p-1"
            title="Kodu Kopyala"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        </div>
        <SyntaxHighlighter
          {...props}
          style={atomDark}
          language={match[1]}
          PreTag="div"
          customStyle={{ margin: 0, padding: '1rem', background: 'rgba(17, 24, 39, 0.7)' }}
        >
          {codeText}
        </SyntaxHighlighter>
      </div>
    );
  }
  return (
    <code {...props} className={`${className} bg-gray-900/60 border border-gray-700/50 text-emerald-300 px-1.5 py-0.5 rounded shadow-sm text-[0.85em] font-mono`}>
      {children}
    </code>
  );
};

const ThoughtBlock = ({ thought, currentTool, isStreaming }) => {
  const [isExpanded, setIsExpanded] = useState(true);

  if (!thought && !currentTool) return null;

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-gray-800/40 bg-white/[0.02] backdrop-blur-md transition-all">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center justify-between px-4 py-2 hover:bg-white/[0.02] transition-colors group"
      >
        <div className="flex items-center space-x-2">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-blue-500/10 border border-blue-500/20">
             <Bot className={`w-3 h-3 text-blue-400 ${isStreaming ? 'animate-pulse' : ''}`} />
          </div>
          <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-gray-500 group-hover:text-blue-400 transition-colors">
            {isStreaming ? (currentTool ? 'Arama Yapılıyor...' : 'Düşünülüyor...') : 'Düşünme Adımları'}
          </span>
        </div>
        <motion.div
          animate={{ rotate: isExpanded ? 0 : -90 }}
          className="text-gray-600 group-hover:text-gray-400 transition-colors"
        >
          <X className="w-3 h-3 rotate-45" />
        </motion.div>
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="px-4 pb-4"
          >
            <div className="border-t border-gray-800/40 pt-3">
              {thought && (
                <div className="text-[13px] text-gray-400 italic font-serif leading-relaxed line-clamp-10 mb-2">
                  {thought}
                </div>
              )}
              {currentTool && (
                <div className="flex items-center space-x-2 text-emerald-400 font-medium">
                  <div className="flex items-center space-x-2 px-2 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-[11px] uppercase tracking-wider">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>{currentTool === 'search' ? 'İnternet Taranıyor' : 'Sayfa Okunuyor'}...</span>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default function ChatArea({ agent, messages, onSendMessage, isTyping, isCheckingOllama, ollamaStatus, onDocumentUploaded }) {
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const bottomRef = useRef(null);
  const abortControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const [selectedImages, setSelectedImages] = useState([]);
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const [planningMode, setPlanningMode] = useState(false);

  // Reset input when agent changes
  useEffect(() => {
    setInput('');
    setIsStreaming(false);
  }, [agent?.id]);

  useEffect(() => {
    console.log('[ChatArea] Received messages:', { count: messages?.length, messages });
  }, [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping, isStreaming]);

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    onSendMessage({ role: 'ai', isStreaming: false, update: true });
  };

  const handleFileUpload = async (file) => {
    if (!file || !agent) return;
    setIsUploadingFile(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await fetch(`${API_URL}/agents/${agent.id}/documents`, {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json();
        onSendMessage({ text: `❌ Dosya yüklenemedi: ${err.detail}`, role: 'ai', isStreaming: false });
        return;
      }
      const doc = await resp.json();
      onSendMessage({ text: `✅ **${doc.original_name}** başarıyla yüklendi (${doc.chunk_count} parça indekslendi).`, role: 'ai', isStreaming: false });
      if (onDocumentUploaded) onDocumentUploaded();
    } catch (e) {
      onSendMessage({ text: `❌ Yükleme hatası: ${e.message}`, role: 'ai', isStreaming: false });
    } finally {
      setIsUploadingFile(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleImageChange = (e) => {
    const files = Array.from(e.target.files);
    files.forEach(file => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64 = reader.result.split(',')[1];
        setSelectedImages(prev => [...prev, { file, base64, preview: URL.createObjectURL(file) }]);
      };
      reader.readAsDataURL(file);
    });
    e.target.value = '';
  };

  const removeImage = (index) => {
    setSelectedImages(prev => prev.filter((_, i) => i !== index));
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        const formData = new FormData();
        formData.append('file', audioBlob, 'record.wav');

        try {
          const resp = await axios.post(`${API_URL}/audio/transcribe`, formData, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
          });
          if (resp.data.text) {
            setInput(prev => (prev + ' ' + resp.data.text).strip());
          }
        } catch (e) {
          console.error("STT Error:", e);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (e) {
      console.error("Mic Access Error:", e);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
    }
  };

  if (!agent) {
    const showStatusError = ollamaStatus && ollamaStatus.running === false;

    return (
      <div className="flex-1 bg-gray-950 flex flex-col items-center justify-center text-gray-500 relative">
        {(isCheckingOllama || showStatusError) && (
          <div className="absolute inset-0 bg-gray-950/80 backdrop-blur-md flex items-center justify-center z-50 p-6">
            <motion.div 
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="bg-gray-900 border border-gray-800 rounded-3xl p-8 max-w-sm text-center shadow-2xl relative overflow-hidden"
            >
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-red-500 to-orange-500"></div>
              {isCheckingOllama ? (
                <>
                  <Loader2 className="w-10 h-10 animate-spin text-blue-500 mx-auto mb-4" />
                  <h3 className="text-xl font-medium text-white mb-2">Sistem Bağlantısı</h3>
                  <p className="text-sm text-gray-400">Ollama servisi kontrol ediliyor...</p>
                </>
              ) : (
                <>
                  <div className="w-14 h-14 bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-4 border border-red-500/20">
                    <Bot className="w-6 h-6 text-red-500" />
                  </div>
                  <h3 className="text-xl font-semibold text-white mb-2">Ollama Bağlantısı Yok</h3>
                  <p className="text-sm text-gray-400 mb-6 leading-relaxed">
                    {ollamaStatus?.error || "Ollama servisine şu anda erişilemiyor."}
                  </p>
                  <div className="text-xs text-gray-400 bg-gray-950 p-4 rounded-2xl font-mono border border-gray-800/50">
                    {ollamaStatus?.installed ? 
                      "Lütfen 'ollama serve' komutunun çalıştığından emin olun." :
                      "Ollama kurulu görünmüyor (ollama.com)"
                    }
                  </div>
                </>
              )}
            </motion.div>
          </div>
        )}

        <Bot className="w-20 h-20 mb-6 opacity-10 text-blue-400" />
        <h2 className="text-2xl font-bold text-gray-100 uppercase tracking-widest">Z-Sifos</h2>
        <p className="text-sm mt-3 max-w-sm text-center opacity-60 leading-relaxed px-6">
          Z-Sifos platformuna hoş geldiniz. Sohbet etmeye başlamak için bir ajan seçin.
        </p>
      </div>
    );
  }

  const handleSend = (e) => {
    e.preventDefault();
    console.log('[handleSend] Called - input:', input, 'isTyping:', isTyping, 'isStreaming:', isStreaming);
    if (!input.trim() || isTyping || isStreaming) {
      console.log('[handleSend] Blocked - returning early');
      return;
    }
    
    const userMessage = input.trim();
    console.log('[handleSend] Sending message:', userMessage, 'to agent:', agent.id);
    onSendMessage({ text: userMessage, role: 'user' });
    setInput('');
    connectStreamingChat(userMessage, agent.id);
  };

  const connectStreamingChat = async (message, agentId, options = {}) => {
    const { isApproval = false } = options;
    setIsStreaming(true);
    abortControllerRef.current = new AbortController();
    
    if (!isApproval) {
      onSendMessage({ text: '', role: 'ai', isStreaming: true });
    }
    
    try {
      const apiUrl = `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/agents/${agentId}/chat/stream`;
      
      const startTime = performance.now();
      
      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({ 
          message: message, 
          images: selectedImages.map(img => img.base64),
          planning_mode: planningMode || isApproval,
          plan_approved: isApproval
        }),
        signal: abortControllerRef.current.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (trimmedLine.startsWith('data: ')) {
            try {
              const data = JSON.parse(trimmedLine.slice(6));
              
              if (data.type === 'token') {
                onSendMessage({ text: data.content, role: 'ai', isStreaming: true, update: true });
              } else if (data.type === 'thought') {
                onSendMessage({ role: 'ai', thought: data.content, isStreaming: true, update: true });
              } else if (data.type === 'tool_start') {
                onSendMessage({ role: 'ai', currentTool: data.tool, isStreaming: true, update: true });
              } else if (data.type === 'plan') {
                onSendMessage({ role: 'ai', plan: data.content, isStreaming: true, update: true });
              } else if (data.type === 'status' && data.content === 'complete') {
                const endTime = performance.now();
                const duration = ((endTime - startTime) / 1000).toFixed(1);
                setIsStreaming(false);
                onSendMessage({ role: 'ai', isStreaming: false, currentTool: null, responseTime: duration, update: true });
              } else if (data.type === 'error') {
                setIsStreaming(false);
                onSendMessage({ text: `\n\n[Hata: ${data.content}]`, role: 'ai', isStreaming: false, currentTool: null, update: true });
              }
            } catch (err) {
              console.warn('[SSE] Parse error:', err);
            }
          }
        }
      }
      
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('Stream aborted by user');
      } else {
        console.error('Streaming error:', error);
        setIsStreaming(false);
        // Fallback or error display
        onSendMessage({ text: 'Bağlantı hatası.', role: 'ai', isStreaming: false, update: true });
      }
    } finally {
      abortControllerRef.current = null;
    }
  };

  const handleApprovePlan = async (msg) => {
    // Find the last user message to repeat it with approval
    const lastUserMessage = messages.filter(m => m.role === 'user').slice(-1)[0];
    if (lastUserMessage) {
      // Add a placeholder message for the AI response that will follow the plan
      onSendMessage({ text: '', role: 'ai', isStreaming: true });
      connectStreamingChat(lastUserMessage.text, agent.id, { isApproval: true });
    }
  };

  return (
    <div className="flex-1 bg-gray-950 flex flex-col h-full overflow-hidden relative">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/10 rounded-full blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-emerald-600/5 rounded-full blur-[100px] pointer-events-none"></div>

      <div className="h-[72px] border-b border-gray-800/80 flex items-center px-8 bg-gray-950/60 backdrop-blur-xl z-20 shadow-xl relative">
        <div className="flex items-center space-x-3">
          <div className={`w-2.5 h-2.5 rounded-full ${agent.status === 'downloading' ? 'bg-blue-400 animate-pulse' : 'bg-emerald-400 shadow-emerald-400/50 shadow'}`}></div>
          <h2 className="text-gray-100 font-semibold tracking-wide text-lg">{agent.name}</h2>
          <span className="px-2 py-0.5 rounded-full bg-gray-800/60 border border-gray-700/50 text-[10px] text-emerald-400 uppercase tracking-widest ml-2">
            {agent.status === 'downloading' ? 'Hazırlanıyor' : 'Hazır'}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-8 z-10 scroll-smooth relative">
        {agent.status === 'downloading' && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-gray-950/70 backdrop-blur-sm">
            <div className="w-16 h-16 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mb-4" />
            <h3 className="text-xl font-bold text-white">Model Hazırlanıyor</h3>
          </div>
        )}

        {messages && messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400 space-y-6">
             <div className="w-20 h-20 rounded-full bg-gray-900/50 flex items-center justify-center border border-gray-800 shadow-2xl">
                <Bot className="w-10 h-10 text-emerald-400/50" />
             </div>
             <p className="text-sm text-center leading-relaxed">
               <strong className="text-gray-200">"{agent.name}"</strong> ile sohbete başlayın.
             </p>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {messages && messages.map((msg, idx) => (
              <motion.div 
                key={idx} 
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className={`flex w-full md:max-w-[85%] space-x-4 ${msg.role === 'user' ? 'ml-auto flex-row-reverse space-x-reverse' : 'mr-auto'}`}>
                  {/* User Image Previews in Chat bubble */}
                  {msg.role === 'user' && msg.images && msg.images.length > 0 && (
                    <div className="flex flex-col gap-2 mb-2">
                      {msg.images.map((img, i) => (
                        <div key={i} className="w-48 h-48 rounded-2xl overflow-hidden border border-gray-700/50 shadow-xl">
                          <img src={`data:image/jpeg;base64,${img}`} className="w-full h-full object-cover" alt="User upload" />
                        </div>
                      ))}
                    </div>
                  )}
                  <div className={`w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 shadow-lg ${
                    msg.role === 'user' ? 'bg-blue-600' : 'bg-gray-800 text-emerald-400'
                  }`}>
                    {msg.role === 'user' ? <User className="w-5 h-5 text-white" /> : <Bot className="w-5 h-5" />}
                  </div>
                  <div className="flex flex-col space-y-2 flex-1 min-w-0">
                    <div className={`px-6 py-4 rounded-3xl text-[15px] leading-relaxed shadow-xl ${
                      msg.role === 'user' 
                        ? 'bg-blue-600 text-white rounded-tr-sm' 
                        : 'bg-gray-900/80 text-gray-200 border border-gray-700/50 rounded-tl-sm markdown-prose backdrop-blur-sm shadow-2xl'
                    }`}>
                      {msg.role === 'ai' && (
                        <ThoughtBlock 
                          thought={msg.thought} 
                          currentTool={msg.currentTool} 
                          isStreaming={msg.isStreaming} 
                        />
                      )}
                      {msg.role === 'user' ? msg.text : (
                        msg.text ? <ReactMarkdown components={{ code: CodeBlock }}>{msg.text}</ReactMarkdown> : (!msg.plan && <div className="py-2"><Loader2 className="w-5 h-5 animate-spin opacity-20" /></div>)
                      )}

                      {msg.role === 'ai' && msg.plan && (
                        <div className="mt-4 p-4 rounded-2xl bg-blue-500/10 border border-blue-500/20">
                           <div className="prose prose-invert prose-sm max-w-none">
                              <ReactMarkdown components={{ code: CodeBlock }}>{msg.plan}</ReactMarkdown>
                           </div>
                           {!msg.isStreaming && (
                             <button
                               type="button"
                               onClick={() => handleApprovePlan(msg)}
                               className="mt-4 w-full py-2 bg-emerald-500 text-white rounded-xl font-bold hover:bg-emerald-600 transition-all flex items-center justify-center space-x-2 shadow-lg shadow-emerald-500/20 active:scale-[0.98]"
                             >
                               <Check className="w-5 h-5" />
                               <span>Planı Onayla ve Başlat</span>
                             </button>
                           )}
                        </div>
                      )}
                      {msg.role === 'ai' && msg.confidence !== undefined && (
                        <div className="mt-4 pt-3 border-t border-gray-700/30 text-xs space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-gray-500">Güvenilirlik:</span>
                            <div className="flex items-center space-x-2">
                              <div className="w-20 h-2 bg-gray-800 rounded-full overflow-hidden">
                                <div 
                                  className={`h-full rounded-full transition-all ${msg.confidence > 0.7 ? 'bg-emerald-500' : msg.confidence > 0.4 ? 'bg-yellow-500' : 'bg-red-500'}`}
                                  style={{ width: `${msg.confidence * 100}%` }}
                                />
                              </div>
                              <span className="text-gray-400">{Math.round(msg.confidence * 100)}%</span>
                            </div>
                          </div>
                          {msg.sources && msg.sources.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              <span className="text-gray-500">Kaynaklar:</span>
                              {msg.sources.map((src, sidx) => (
                                <span key={sidx} className="bg-gray-800/60 text-gray-300 px-2 py-0.5 rounded-md">{src}</span>
                              ))}
                            </div>
                          )}
                          {msg.flags && msg.flags.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {msg.flags.map((flag, fidx) => (
                                <span key={fidx} className="bg-yellow-500/20 text-yellow-300 px-2 py-0.5 rounded-md border border-yellow-500/30">⚠️ {flag}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                    {msg.role === 'ai' && (
                      <div className="flex items-center space-x-4 px-2 mt-1">
                        {msg.responseTime && (
                          <span className="text-[10px] text-gray-500 font-mono">
                            {msg.responseTime}s
                          </span>
                        )}
                        <div className="flex items-center space-x-2">
                          <button 
                            className="p-1 rounded-md hover:bg-emerald-500/10 text-gray-600 hover:text-emerald-400 transition-colors"
                            title="Yararlı"
                          >
                            <ThumbsUp className="w-3 h-3" />
                          </button>
                          <button 
                            className="p-1 rounded-md hover:bg-red-500/10 text-gray-600 hover:text-red-400 transition-colors"
                            title="Yararsız"
                          >
                            <ThumbsDown className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
        <div ref={bottomRef} className="h-4" />
      </div>

      <div className="p-4 md:p-6 bg-gradient-to-t from-gray-950 via-gray-950/90 to-transparent z-20 pt-10">
        {/* Image Previews */}
        <AnimatePresence>
          {selectedImages.length > 0 && (
            <div className="max-w-4xl mx-auto flex flex-wrap gap-3 mb-4 px-2">
              {selectedImages.map((img, idx) => (
                <motion.div 
                  key={idx}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="relative group w-20 h-20 rounded-2xl overflow-hidden border border-gray-700 shadow-2xl"
                >
                  <img src={img.preview} className="w-full h-full object-cover" alt="Preview" />
                  <button 
                    onClick={() => removeImage(idx)}
                    className="absolute top-1 right-1 bg-red-500 rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="w-2.5 h-2.5 text-white" />
                  </button>
                </motion.div>
              ))}
            </div>
          )}
        </AnimatePresence>

        <form onSubmit={handleSend} className={`max-w-4xl mx-auto relative group ${agent.status === 'downloading' ? 'opacity-30 pointer-events-none' : ''}`}>
          <div className="relative flex items-center bg-white/[0.03] backdrop-blur-2xl border border-white/10 rounded-[2.2rem] shadow-xl p-2.5 hover:bg-white/5 transition-all group/input">
            {/* File upload — hidden input + paperclip trigger */}
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".txt,.md,.pdf,.docx,.rst,.csv"
              onChange={(e) => { if (e.target.files[0]) handleFileUpload(e.target.files[0]); }}
            />
            {agent.document_enabled && (
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploadingFile || agent.status === 'downloading'}
                title="Dosya Yükle (PDF, TXT, DOCX)"
                className="w-10 h-10 rounded-full flex items-center justify-center text-gray-400 hover:text-violet-400 hover:bg-violet-500/10 transition-all ml-1 shrink-0 disabled:opacity-30"
              >
                {isUploadingFile
                  ? <Loader2 className="w-4 h-4 animate-spin" />
                  : <Paperclip className="w-4 h-4" />}
              </button>
            )}

            {/* Vision Upload Trigger */}
            <input 
              type="file" 
              multiple 
              accept="image/*" 
              ref={imageInputRef} 
              className="hidden" 
              onChange={handleImageChange}
            />
            <button
              type="button"
              onClick={() => imageInputRef.current?.click()}
              className="w-10 h-10 rounded-full flex items-center justify-center text-gray-400 hover:text-blue-400 hover:bg-blue-400/10 transition-all ml-1 shrink-0"
              title="Resim Ekle/Analiz Et"
            >
              <ImageIcon className="w-4 h-4" />
            </button>
            <input
              className="flex-1 relative bg-transparent px-5 py-3.5 text-gray-100 focus:outline-none text-[15px] placeholder-gray-500"
              placeholder={isRecording ? 'Dinleniyor...' : (agent.status === 'downloading' ? 'Bekleyin...' : 'Bir mesaj gönderin...')}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isTyping || isStreaming || agent.status === 'downloading'}
              autoComplete="off"
            />
            
            <div className="flex items-center gap-1.5 mr-1 text-gray-400">
              {/* Voice Input Trigger */}
              <button
                type="button"
                onMouseDown={startRecording}
                onMouseUp={stopRecording}
                onMouseLeave={stopRecording}
                className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
                  isRecording ? 'text-red-500 bg-red-500/10 animate-pulse' : 'hover:text-red-400 hover:bg-red-400/10'
                }`}
                title="Sesli Komut (Basılı Tut)"
              >
                <Mic className="w-4.5 h-4.5" />
              </button>

              {isStreaming ? (
                <button 
                  type="button" 
                  onClick={handleStop}
                  className="relative w-12 h-12 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center transition-all border border-red-500/40 hover:bg-red-500/30 shadow-lg"
                >
                  <Square className="w-5 h-5 fill-red-400/20" />
                </button>
              ) : (
                <button 
                  type="submit" 
                  disabled={(!input.trim() && selectedImages.length === 0) || isTyping || agent.status === 'downloading'}
                  className="relative w-12 h-12 rounded-full bg-gradient-to-br from-emerald-500/30 to-blue-500/20 text-emerald-400 flex items-center justify-center transition-all disabled:opacity-30 border border-emerald-500/40"
                >
                  {isTyping ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5 ml-0.5" />}
                </button>
              )}
            </div>
          </div>
        </form>
        
        {/* Planning Mode Toggle */}
        <div className="max-w-4xl mx-auto mt-3 flex items-center justify-center px-4">
           <label className="flex items-center space-x-3 cursor-pointer group">
              <span className={`text-[11px] uppercase tracking-widest font-bold transition-colors ${planningMode ? 'text-emerald-400' : 'text-gray-500'}`}>
                Planlama Modu
              </span>
              <div 
                onClick={() => setPlanningMode(!planningMode)}
                className={`relative w-10 h-5 rounded-full transition-all duration-300 border ${
                  planningMode ? 'bg-emerald-500/20 border-emerald-500/50' : 'bg-gray-800 border-gray-700'
                }`}
              >
                <div className={`absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full transition-all duration-300 ${
                  planningMode ? 'left-5.5 bg-emerald-400 shadow-lg shadow-emerald-500/50' : 'left-1 bg-gray-600'
                }`}></div>
              </div>
              <span className="text-[9px] text-gray-600 italic group-hover:text-gray-400 transition-colors">
                (Ajan işlem yapmadan önce plan sunar)
              </span>
           </label>
        </div>
      </div>
    </div>
  );
}
