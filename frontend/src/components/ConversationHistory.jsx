import React, { useState, useEffect } from 'react';
import { MessageCircle, Trash2, Plus, Calendar, User, Bot } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function ConversationHistory({ agent, onSelectConversation }) {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!agent?.id) return;
    fetchConversations();
  }, [agent?.id]);

  const fetchConversations = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_URL}/agents/${agent.id}/conversations`);
      setConversations(response.data);
    } catch (error) {
      console.error('Failed to fetch conversations:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Tüm sohbet geçmişini silmek istiyor musunuz?')) return;
    
    try {
      await axios.delete(`${API_URL}/agents/${agent.id}/conversations`);
      setConversations([]);
    } catch (error) {
      console.error('Failed to clear conversations:', error);
    }
  };

  // Group messages into conversations (by separating user-ai pairs)
  const groupedConversations = [];
  let currentConv = [];
  
  conversations.forEach((msg) => {
    currentConv.push(msg);
    // Start new conversation after AI response
    if (msg.role === 'ai') {
      groupedConversations.push([...currentConv]);
      currentConv = [];
    }
  });

  const formatDate = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleDateString('tr-TR', { 
      month: 'short', 
      day: 'numeric', 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  const getPreview = (conv) => {
    if (!conv.length) return '';
    const userMsg = conv.find(m => m.role === 'user');
    return userMsg?.message?.substring(0, 40) + '...' || 'Boş sohbet';
  };

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300 flex items-center space-x-2">
          <MessageCircle className="w-4 h-4" />
          <span>Sohbet Geçmişi</span>
        </h3>
        <button
          onClick={fetchConversations}
          className="text-xs px-2 py-1 bg-blue-600/20 text-blue-300 rounded-md hover:bg-blue-600/30 transition"
          title="Yenile"
        >
          🔄
        </button>
      </div>

      {loading ? (
        <div className="text-xs text-gray-400 py-4 text-center">Yükleniyor...</div>
      ) : groupedConversations.length === 0 ? (
        <div className="text-xs text-gray-500 py-8 text-center">
          <MessageCircle className="w-8 h-8 opacity-20 mx-auto mb-2" />
          Henüz sohbet yok
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto thin-scrollbar">
          {groupedConversations.map((conv, idx) => {
            const userMsg = conv.find(m => m.role === 'user');
            const aiMsg = conv.find(m => m.role === 'ai');
            const createdAt = userMsg?.created_at || aiMsg?.created_at;

            return (
              <button
                key={idx}
                onClick={() => onSelectConversation && onSelectConversation(conv)}
                className="w-full text-left p-3 bg-gray-800/40 hover:bg-gray-800/70 border border-gray-700/30 rounded-lg transition-all group"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center space-x-2 text-xs">
                    <User className="w-3 h-3 text-blue-400" />
                    <span className="font-mono text-gray-400">#{idx + 1}</span>
                  </div>
                  <span className="text-xs text-gray-500 flex items-center space-x-1">
                    <Calendar className="w-3 h-3" />
                    <span>{formatDate(createdAt)}</span>
                  </span>
                </div>
                <p className="text-xs text-gray-300 line-clamp-2">
                  {getPreview(conv)}
                </p>
                {conv.length > 0 && (
                  <div className="text-xs text-gray-500 mt-2 flex items-center space-x-2">
                    <Bot className="w-3 h-3 text-emerald-400" />
                    <span className="line-clamp-1">
                      {aiMsg?.message?.substring(0, 50)}...
                    </span>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      {conversations.length > 0 && (
        <button
          onClick={handleClearAll}
          className="w-full mt-4 py-2 px-3 text-xs bg-red-600/20 text-red-300 hover:bg-red-600/30 border border-red-500/30 rounded-lg transition flex items-center justify-center space-x-2"
        >
          <Trash2 className="w-3 h-3" />
          <span>Tümünü Sil</span>
        </button>
      )}

      <style>{`
        .thin-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .thin-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .thin-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(107, 114, 128, 0.5);
          border-radius: 2px;
        }
        .thin-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(107, 114, 128, 0.8);
        }
      `}</style>
    </div>
  );
}
