import React from 'react';
import { Bot, Plus, Cpu, Trash2, LogOut, User } from 'lucide-react';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';

export default function Sidebar({ agents, activeAgentId, onSelect, onNew, downloadingAgents, onDelete }) {
  const { user, logout } = useAuth();
  
  return (
    <div className="w-[280px] bg-gray-950/80 backdrop-blur-xl border-r border-gray-800/80 flex flex-col h-full select-none shadow-[4px_0_24px_rgba(0,0,0,0.2)] z-30">
      <div className="p-6 border-b border-gray-800/60 flex items-center justify-between relative overflow-hidden">
        <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-3xl -mr-16 -mt-16 pointer-events-none"></div>
        <div className="flex items-center space-x-3 z-10">
           <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-blue-500 p-0.5 shadow-lg shadow-emerald-500/20">
             <div className="w-full h-full bg-gray-900 rounded-[10px] flex items-center justify-center">
               <Bot className="w-5 h-5 text-emerald-400" />
             </div>
           </div>
           <h2 className="text-xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-gray-100 to-gray-400 uppercase tracking-widest">
             Z-Sifos
           </h2>
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-3 relative">
            {agents && agents.map((agent) => {
              if (!agent) return null;
              const isDownloading = downloadingAgents && downloadingAgents[agent.id];
              return (
                <button
                  key={agent.id}
                  onClick={() => onSelect(agent.id)}
                  className={`w-full group relative flex items-center p-4 rounded-2xl transition-all duration-300 ${
                    activeAgentId === agent.id 
                    ? 'bg-gradient-to-r from-blue-600/20 to-emerald-500/10 border border-blue-500/30' 
                    : 'hover:bg-gray-800/40 border border-transparent'
                  }`}
                >
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center font-bold text-lg ${
                    activeAgentId === agent.id ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20' : 'bg-gray-800 text-gray-400'
                  }`}>
                    {agent.name ? agent.name.charAt(0).toUpperCase() : '?'}
                  </div>
                  <div className="ml-4 text-left flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={`block font-semibold truncate ${activeAgentId === agent.id ? 'text-white' : 'text-gray-300'}`}>
                        {agent.name}
                      </span>
                      <div className="flex items-center space-x-2">
                        {agent.status === 'downloading' && (
                          <span className="flex h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (onDelete && window.confirm(`"${agent.name}" ajanını silmek istiyor musunuz?`)) {
                              onDelete(agent.id);
                            }
                          }}
                          className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-600/20 hover:text-red-400 text-gray-500 rounded-lg transition-all"
                          title="Ajan Sil"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                    <span className="block text-[11px] text-gray-500 truncate font-mono">{agent.model_name}</span>
                    
                    {/* Progress Bar for downloading agents */}
                    {isDownloading && downloadingAgents[agent.id] && (
                      <div className="mt-2 space-y-1">
                        <div className="flex justify-between text-[9px] text-blue-400 font-bold uppercase tracking-tighter">
                          <span>{downloadingAgents[agent.id].status || 'İndiriliyor'}</span>
                          <span>%{downloadingAgents[agent.id].percentage || 0}</span>
                        </div>
                        <div className="w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                          <motion.div 
                            initial={{ width: 0 }}
                            animate={{ width: `${downloadingAgents[agent.id].percentage || 0}%` }}
                            className="h-full bg-blue-500"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
      </div>

      <div className="p-6 border-t border-gray-800/60 bg-gray-950/50 space-y-4">
        {/* User Profile Section */}
        {user && (
          <div className="flex items-center justify-between p-3 bg-gray-900/50 rounded-2xl border border-gray-800/50">
            <div className="flex items-center space-x-3 overflow-hidden">
               <div className="w-8 h-8 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center shrink-0">
                  <User className="w-4 h-4 text-blue-400" />
               </div>
               <span className="text-xs font-semibold text-gray-300 truncate">{user.username}</span>
            </div>
            <button 
              onClick={logout}
              className="p-2 text-gray-500 hover:text-red-400 hover:bg-red-400/10 rounded-xl transition-all"
              title="Çıkış Yap"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}

        <button 
          onClick={onNew}
          className="w-full flex items-center justify-center space-x-2 py-3.5 bg-gradient-to-r from-gray-800 to-gray-900 hover:from-gray-700 hover:to-gray-800 text-gray-200 rounded-2xl transition-all duration-300 text-sm font-semibold border border-gray-700 shadow-xl group hover:shadow-[0_0_20px_rgba(255,255,255,0.05)] hover:border-gray-600"
        >
          <div className="bg-gray-700/50 rounded-full p-1 group-hover:bg-emerald-500/20 group-hover:text-emerald-400 transition-colors">
            <Plus className="w-4 h-4" />
          </div>
          <span>Yeni Ajan Oluştur</span>
        </button>
      </div>
    </div>
  );
}
