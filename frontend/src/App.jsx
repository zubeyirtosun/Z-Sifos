import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import Sidebar from './components/Sidebar';
import ModulePanel from './components/ModulePanel';
import ChatArea from './components/ChatArea';
import NewAgentModal from './components/NewAgentModal';
import EvaluationDashboard from './components/EvaluationDashboard';
import ConversationHistory from './components/ConversationHistory';
import AuthModal from './components/AuthModal';
import { useAuth } from './context/AuthContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function App() {
  const [agents, setAgents] = useState([]);
  const [activeAgentId, setActiveAgentId] = useState(null);
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'metrics'
  const [messages, setMessages] = useState({});
  const [isTyping, setIsTyping] = useState(false);

  // Debug: log messages when they change
  useEffect(() => {
    console.log('[App] Messages state updated:', { activeAgentId, messageCount: messages[activeAgentId]?.length || 0, messages });
  }, [messages, activeAgentId]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [providers, setProviders] = useState([]);
  const [providerModels, setProviderModels] = useState([]);
  const [ollamaStatus, setOllamaStatus] = useState(null);
  const [isCheckingOllama, setIsCheckingOllama] = useState(false);
  const [downloadingAgents, setDownloadingAgents] = useState({});
  const { token, loading } = useAuth();

  const fetchProviderModels = useCallback(async (providerName) => {
    try {
      const resp = await axios.get(`${API_URL}/providers/${providerName}/models`);
      setProviderModels(resp.data.models || []);
    } catch (e) {
      console.error("Provider models fetch failed", e);
      setProviderModels([]);
    }
  }, []);

  const fetchProviders = useCallback(async () => {
    try {
      const resp = await axios.get(`${API_URL}/providers/`);
      setProviders(resp.data);
      if (resp.data.length > 0) {
        fetchProviderModels(resp.data[0].name);
      }
    } catch (e) {
      console.error("Provider fetch failed", e);
    }
  }, [fetchProviderModels]);

  const startModelPull = async (agent) => {
    try {
      const response = await fetch(`${API_URL}/models/pull`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ model_name: agent.model_name, provider: agent.provider })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const lines = decoder.decode(value).split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            setDownloadingAgents(prev => ({
              ...prev,
              [agent.id]: { percentage: data.percentage, status: data.status }
            }));

            if (data.status === 'success') {
              await axios.put(`${API_URL}/agents/${agent.id}`, {
                ...agent,
                status: 'ready'
              });
              setDownloadingAgents(prev => {
                const next = { ...prev };
                delete next[agent.id];
                return next;
              });
              fetchAgents();
            }
          }
        }
      }
    } catch (e) {
      console.error("Pull failed:", e);
    }
  };

  const fetchAgents = useCallback(async () => {
    try {
      const resp = await axios.get(`${API_URL}/agents/`);
      setAgents(resp.data);
    } catch (e) {
      console.error("Agent fetch failed", e);
    }
  }, []);

  // Downloading takibi için ayrı bir effect
  useEffect(() => {
    agents.forEach(agent => {
      if (agent.status === 'downloading' && !downloadingAgents[agent.id]) {
        startModelPull(agent);
      }
    });
  }, [agents, downloadingAgents]);

  const checkOllamaStatus = useCallback(async () => {
    setIsCheckingOllama(true);
    try {
      const resp = await axios.get(`${API_URL}/ollama/status`);
      setOllamaStatus(resp.data);
    } catch (e) {
      console.error("Ollama status check failed", e);
      setOllamaStatus({ installed: false, running: false, error: "Backend bağlantı hatası" });
    } finally {
      setIsCheckingOllama(false);
    }
  }, []);

  useEffect(() => {
    if (token && !loading) {
      // Small delay to ensure axios headers from AuthContext are ready
      const timer = setTimeout(() => {
        fetchProviders();
        fetchAgents();
        checkOllamaStatus();
      }, 100);
      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, loading]);

  const handleCreateAgent = () => {
    setIsModalOpen(true);
  };

  const handleCreateAgentSubmit = async (agentData) => {
    try {
      await axios.post(`${API_URL}/agents/`, agentData);
      setIsModalOpen(false);
      fetchAgents();
    } catch (e) {
      const errorText = e.response?.data?.detail || e.message || "Network Error";
      alert("Ajan oluşturulamadı: " + errorText + ". Backend çalışıyor mu? http://localhost:8000 adresini kontrol edin.");
    }
  };

  const handleSelectAgent = async (agentId) => {
    if (!agentId) return;
    setActiveAgentId(agentId);
    checkOllamaStatus();
    
    // Load conversation history for the selected agent
    try {
      const resp = await axios.get(`${API_URL}/agents/${agentId}/conversations`);
      const history = resp.data.map(msg => ({
        role: msg.role,
        text: msg.message,
        isStreaming: false,
        timestamp: msg.created_at
      }));
      setMessages(prev => ({ ...prev, [agentId]: history }));
    } catch (e) {
      console.error("Failed to load conversation history:", e);
    }
  };
  
  const activeAgent = agents && agents.length > 0 ? agents.find(a => a.id === activeAgentId) : null;
  const activeMessages = (activeAgentId && messages && messages[activeAgentId]) ? messages[activeAgentId] : [];

  const handleUpdateAgent = async (updatedAgent) => {
    try {
      const resp = await axios.put(`${API_URL}/agents/${updatedAgent.id}`, updatedAgent);
      setAgents(agents.map(a => a.id === updatedAgent.id ? resp.data : a));
    } catch {
      alert('Güncellenemedi');
    }
  };

  const handleClearChat = (agentId) => {
    setMessages((prev) => ({ ...prev, [agentId]: [] }));
  };

  const handleDeleteAgent = async (agentId) => {
    try {
      await axios.delete(`${API_URL}/agents/${agentId}`);
      fetchAgents();
      if (activeAgentId === agentId) {
        setActiveAgentId(null);
        setMessages({});
      }
    } catch (error) {
      alert(`Ajan silinemedi: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleSendMessage = async (message) => {
    console.log('[App] handleSendMessage called with:', message);
    if (!activeAgentId) return;
    
    // Backward compatibility: handle both string and object messages
    const isStreamingFormat = typeof message === 'object' && message.role;
    const messageText = isStreamingFormat ? message.text : message;
    const messageRole = isStreamingFormat ? message.role : 'user';
    const isStreaming = isStreamingFormat ? message.isStreaming : false;
    const isUpdate = isStreamingFormat ? message.update : false;
    
    // Ollama status check removed to prevent false-positives
    // The backend will handle the connection error if the service is truly down.
    
    if (isUpdate) {
      setMessages((prevMessages) => {
        const currentMsgs = prevMessages[activeAgentId] || [];
        if (currentMsgs.length === 0 || currentMsgs[currentMsgs.length - 1].role !== 'ai') {
          return prevMessages; // Güncellenecek AI mesajı henüz state'e düşmemiş olabilir
        }

        const messages_list = [...currentMsgs];
        const lastMsg = messages_list[messages_list.length - 1];
        const updateData = typeof message === 'object' ? message : {};

        messages_list[messages_list.length - 1] = {
          ...lastMsg,
          ...updateData,
          text: updateData.text !== undefined ? (lastMsg.text || '') + updateData.text : lastMsg.text,
          thought: updateData.thought !== undefined ? (lastMsg.thought || '') + updateData.thought : lastMsg.thought,
          isStreaming: isStreaming
        };

        return { ...prevMessages, [activeAgentId]: messages_list };
      });

      if (!isStreaming) {
        setIsTyping(false);
      }
    } else {
      // Add new message (Functional Update)
      const newMessageObj = { 
        role: messageRole, 
        text: messageText, 
        isStreaming: isStreaming 
      };
      
      if (typeof message === 'object') {
        Object.assign(newMessageObj, message);
      }

      setMessages((prevMessages) => {
        const currentMsgs = prevMessages[activeAgentId] || [];
        return { 
          ...prevMessages, 
          [activeAgentId]: [...currentMsgs, newMessageObj] 
        };
      });

      if (messageRole === 'user') {
        setIsTyping(true);
      }
    }
  };

  // Auth gating: loading sırasında spinner, token yoksa AuthModal göster
  if (loading) {
    return (
      <div className="flex w-screen h-screen bg-gray-950 items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          <p className="text-gray-400 text-sm">Kimlik doğrulanıyor...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <AuthModal isOpen={!token} />
      <NewAgentModal
        open={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onCreate={handleCreateAgentSubmit}
        providers={providers}
        providerModels={providerModels}
        onFetchProviderModels={fetchProviderModels}
      />
      <div className="flex w-screen h-screen bg-gray-950 overflow-hidden font-sans text-gray-200">
        <Sidebar 
          agents={agents} 
          activeAgentId={activeAgentId} 
          onSelect={handleSelectAgent}
          onNew={handleCreateAgent}
          downloadingAgents={downloadingAgents}
          onDelete={handleDeleteAgent}
        />
        <ChatArea 
          agent={activeAgent} 
          messages={activeMessages}
          onSendMessage={handleSendMessage}
          isTyping={isTyping}
          isCheckingOllama={isCheckingOllama}
          ollamaStatus={ollamaStatus}
        />
        <div className="flex-1 md:flex-none md:w-96 bg-gray-900/60 border-l border-gray-800/80 flex flex-col overflow-hidden">
          {/* Tab Header */}
          <div className="flex border-b border-gray-800/50 bg-gray-900/80 sticky top-0 z-10">
            <button 
              onClick={() => setActiveTab('chat')}
              className={`flex-1 py-3 px-2 md:px-4 text-xs md:text-sm font-semibold transition-all duration-300 border-b-2 ${activeTab === 'chat' ? 'bg-blue-600/20 text-blue-300 border-blue-500' : 'text-gray-400 hover:text-gray-300 border-transparent'}`}
            >
              ⚙️ <span className="hidden md:inline ml-1">Ayarlar</span>
            </button>
            <button 
              onClick={() => setActiveTab('metrics')}
              className={`flex-1 py-3 px-2 md:px-4 text-xs md:text-sm font-semibold transition-all duration-300 border-b-2 ${activeTab === 'metrics' ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500' : 'text-gray-400 hover:text-gray-300 border-transparent'}`}
            >
              📊 <span className="hidden md:inline ml-1">Metrikler</span>
            </button>
            <button 
              onClick={() => setActiveTab('history')}
              className={`flex-1 py-3 px-2 md:px-4 text-xs md:text-sm font-semibold transition-all duration-300 border-b-2 ${activeTab === 'history' ? 'bg-purple-600/20 text-purple-300 border-purple-500' : 'text-gray-400 hover:text-gray-300 border-transparent'}`}
            >
              📜 <span className="hidden md:inline ml-1">Geçmiş</span>
            </button>
          </div>
          
          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto">
            {activeTab === 'chat' && (
              <ModulePanel 
                agent={activeAgent}
                onUpdate={handleUpdateAgent}
                onClearChat={handleClearChat}
              />
            )}
            {activeTab === 'metrics' && (
              <EvaluationDashboard agent={activeAgent} />
            )}
            {activeTab === 'history' && (
              <ConversationHistory agent={activeAgent} onSelectConversation={(conv) => {
                // Optional: Load conversation - could set messages state here
                console.log('Selected conversation:', conv);
              }} />
            )}
          </div>
        </div>
      </div>
    </>
  );
}

export default App;
