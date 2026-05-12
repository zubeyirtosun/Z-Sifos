import React, { useState, useEffect, useCallback } from 'react';
import { Settings, Globe, Database, Cpu, HardDrive, Languages, FileText, Trash2, Upload, X, Loader2, Zap, FileJson, FileCode, FileSpreadsheet, File as FileIcon } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import ConversationHistory from './ConversationHistory';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const MODE_META = {
  STRICT:   { label: 'Küçük Model', color: 'amber',   desc: '≤2B — Hızlı & hafif mod' },
  STANDARD: { label: 'Standart',    color: 'blue',    desc: '2–8B — Dengeli ReAct' },
  ENHANCED: { label: 'Gelişmiş',    color: 'emerald', desc: '>8B — Tam ajan kapasitesi' },
};

function inferMode(agent) {
  // Override takes priority
  if (agent?.agent_mode_override) return agent.agent_mode_override;
  // Then try model_metadata
  if (!agent?.model_metadata) return null; // null = unknown (will show AUTO)
  try {
    const meta = JSON.parse(agent.model_metadata);
    const size = meta.size || '';
    const match = size.match(/([\d.]+)\s*([BM])/i);
    if (!match) return null;
    let params = parseFloat(match[1]);
    if (match[2].toUpperCase() === 'M') params /= 1000;
    if (params <= 2) return 'STRICT';
    if (params <= 8) return 'STANDARD';
    return 'ENHANCED';
  } catch {
    return null;
  }
}

function ToggleCard({ icon: Icon, label, desc, active, onToggle, colorOn, colorOff = 'gray' }) {
  const colors = {
    blue:    { bg: 'from-blue-500/10 to-blue-600/5',    border: 'border-blue-500/30',    glow: 'shadow-[0_0_20px_rgba(59,130,246,0.1)]',    iconBg: 'bg-blue-500/20 text-blue-400',   track: 'bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]',   text: 'text-blue-200' },
    purple:  { bg: 'from-purple-500/10 to-purple-600/5', border: 'border-purple-500/30',  glow: 'shadow-[0_0_20px_rgba(168,85,247,0.1)]',    iconBg: 'bg-purple-500/20 text-purple-400', track: 'bg-purple-500 shadow-[0_0_10px_rgba(168,85,247,0.5)]', text: 'text-purple-200' },
    emerald: { bg: 'from-emerald-500/10 to-emerald-600/5', border: 'border-emerald-500/30', glow: 'shadow-[0_0_20px_rgba(16,185,129,0.1)]', iconBg: 'bg-emerald-500/20 text-emerald-400', track: 'bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]', text: 'text-emerald-200' },
    violet:  { bg: 'from-violet-500/10 to-violet-600/5', border: 'border-violet-500/30',  glow: 'shadow-[0_0_20px_rgba(139,92,246,0.1)]',   iconBg: 'bg-violet-500/20 text-violet-400', track: 'bg-violet-500 shadow-[0_0_10px_rgba(139,92,246,0.5)]', text: 'text-violet-200' },
  };
  const c = colors[colorOn];
  return (
    <div
      onClick={onToggle}
      className={`cursor-pointer group flex items-center justify-between p-4 rounded-2xl border transition-all duration-500 ${
        active
          ? `bg-gradient-to-br ${c.bg} ${c.border} ${c.glow}`
          : 'bg-gray-900/40 border-gray-800/60 hover:bg-gray-800/60 hover:border-gray-700/50'
      }`}
    >
      <div className="flex items-center space-x-4">
        <div className={`p-2.5 rounded-xl transition-colors duration-500 ${active ? c.iconBg : 'bg-gray-800/80 text-gray-500 group-hover:bg-gray-700/80 group-hover:text-gray-400'}`}>
          <Icon className="w-4 h-4" />
        </div>
        <div className="flex flex-col">
          <span className={`font-semibold text-sm transition-colors duration-500 ${active ? c.text : 'text-gray-300'}`}>{label}</span>
          <span className="text-[10px] text-gray-500 mt-0.5">{desc}</span>
        </div>
      </div>
      <div className={`w-11 h-6 rounded-full relative transition-all duration-500 flex items-center px-1 ${active ? c.track : 'bg-gray-700'}`}>
        <div className={`w-4 h-4 rounded-full bg-white shadow-md transition-transform duration-500 ${active ? 'translate-x-5' : 'translate-x-0'}`} />
      </div>
    </div>
  );
}

const getFileIcon = (filename) => {
  const ext = filename.split('.').pop().toLowerCase();
  switch (ext) {
    case 'pdf': return <FileText className="w-3.5 h-3.5 text-red-400 shrink-0" />;
    case 'docx':
    case 'doc': return <FileText className="w-3.5 h-3.5 text-blue-400 shrink-0" />;
    case 'txt':
    case 'md': return <FileText className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
    case 'csv': return <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-500 shrink-0" />;
    case 'json': return <FileJson className="w-3.5 h-3.5 text-yellow-400 shrink-0" />;
    case 'js':
    case 'py':
    case 'html': return <FileCode className="w-3.5 h-3.5 text-violet-400 shrink-0" />;
    default: return <FileIcon className="w-3.5 h-3.5 text-gray-400 shrink-0" />;
  }
};

export default function ModulePanel({ agent, onUpdate, onClearChat, onDocumentUploaded }) {
  const { token } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [stats, setStats] = useState(null);
  const [isDetectingMode, setIsDetectingMode] = useState(false);
  const [detectedMode, setDetectedMode]= useState(null); // from live Ollama query

  const fetchDocuments = useCallback(async () => {
    if (!agent) return;
    try {
      const resp = await fetch(`${API_URL}/agents/${agent.id}/documents`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await resp.json();
      setDocuments(data);
    } catch (e) {
      console.error('Doc fetch error:', e);
    }
  }, [agent?.id]);

  const fetchStats = useCallback(async () => {
    if (!agent) return;
    try {
      const resp = await fetch(`${API_URL}/agents/${agent.id}/stats`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await resp.json();
      setStats(data);
    } catch (e) {
      // non-critical
    }
  }, [agent?.id]);

  useEffect(() => {
    fetchDocuments();
    fetchStats();
  }, [fetchDocuments, fetchStats]);

  const handleFileUpload = async (file) => {
    if (!file || !agent) return;
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await fetch(`${API_URL}/agents/${agent.id}/documents`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        },
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert(err.detail || 'Yükleme başarısız');
        return;
      }
      const doc = await resp.json();
      setDocuments(prev => [...prev, doc]);
      fetchStats();
      if (onDocumentUploaded) onDocumentUploaded(doc);
    } catch (e) {
      alert('Dosya yüklenemedi: ' + e.message);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteDoc = async (docId) => {
    if (!window.confirm('Bu dosyayı silmek istiyor musunuz?')) return;
    try {
      await axios.delete(`${API_URL}/agents/${agent.id}/documents/${docId}`);
      setDocuments(prev => prev.filter(d => d.id !== docId));
      fetchStats();
    } catch (e) {
      console.error('Delete error:', e);
      alert('Dosya silinemedi. Lütfen tekrar deneyin.');
    }
  };

  // Auto-detect mode from Ollama when agent changes and no metadata/override
  useEffect(() => {
    if (!agent) return;
    if (agent.agent_mode_override || agent.model_metadata) {
      setDetectedMode(null);
      return;
    }
    setIsDetectingMode(true);
    fetch(`${API_URL}/models/info?model_name=${encodeURIComponent(agent.model_name)}&provider=${agent.provider}`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
      .then(r => r.json())
      .then(data => {
        if (data.size && data.size !== 'Unknown') {
          const match = data.size.match(/([\d.]+)\s*([BM])/i);
          if (match) {
            let p = parseFloat(match[1]);
            if (match[2].toUpperCase() === 'M') p /= 1000;
            const m = p <= 2 ? 'STRICT' : p <= 8 ? 'STANDARD' : 'ENHANCED';
            setDetectedMode(m);
            // Also persist to model_metadata so future loads are instant
            if (!agent.model_metadata) {
              onUpdate({ ...agent, model_metadata: JSON.stringify(data) });
            }
          }
        }
      })
      .catch(() => {})
      .finally(() => setIsDetectingMode(false));
  }, [agent?.id, agent?.model_name]);

  const handleModeChange = (newMode) => {
    // null clears override (back to AUTO)
    onUpdate({ ...agent, agent_mode_override: newMode });
  };

  const handleClearChat = async () => {
    if (!window.confirm('Tüm konuşma geçmişini silmek istediğinize emin misiniz?')) return;
    try {
      await fetch(`${API_URL}/agents/${agent.id}/conversations`, { 
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (onClearChat) onClearChat(agent.id);
      fetchStats();
    } catch (e) {
      alert('Temizlenemedi');
    }
  };

  if (!agent) {
    return (
      <div className="w-[300px] bg-gray-950/90 backdrop-blur-xl border-l border-gray-800/80 flex flex-col items-center justify-center text-gray-600 shadow-[-4px_0_24px_rgba(0,0,0,0.2)] z-30">
        <Settings className="w-16 h-16 mb-6 opacity-20" />
        <p className="text-sm font-medium tracking-wide">Ajan Seçilmedi</p>
      </div>
    );
  }

  const autoMode = inferMode(agent);
  // activeMode = what is actually running (override > detected > metadata)
  const activeMode = agent.agent_mode_override || autoMode || detectedMode || 'STANDARD';
  const modeMeta = MODE_META[activeMode];
  const modeColors = {
    STRICT:   'text-amber-400 border-amber-500/30 bg-amber-500/10',
    STANDARD: 'text-blue-400 border-blue-500/30 bg-blue-500/10',
    ENHANCED: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
  };

  return (
    <div className="w-[300px] bg-gray-950/90 backdrop-blur-xl border-l border-gray-800/80 flex flex-col h-full text-sm shadow-[-4px_0_24px_rgba(0,0,0,0.2)] z-30 relative overflow-hidden">
      <div className="absolute top-0 right-0 w-48 h-48 bg-blue-500/10 rounded-full blur-3xl -mr-24 -mt-24 pointer-events-none" />

      {/* Header */}
      <div className="p-5 border-b border-gray-800/60 sticky top-0 bg-gray-950/80 backdrop-blur-md z-10 flex items-center space-x-3">
        <div className="p-2 bg-gray-800/50 rounded-lg shadow-inner border border-gray-700/50">
          <Settings className="w-4 h-4 text-gray-300" />
        </div>
        <h3 className="font-semibold text-gray-100 tracking-wide">Konfigürasyon</h3>
      </div>

      <div className="p-4 space-y-6 flex-1 overflow-y-auto relative">

        {/* Identity card */}
        <div className="space-y-3">
          <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest pl-1">Kimlik</h4>
          <div className="bg-gray-900/50 rounded-2xl p-4 border border-gray-800/80 shadow-lg relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-blue-500/5 pointer-events-none" />
            <div className="flex items-center space-x-3 mb-3 border-b border-gray-800/50 pb-3">
              <div className="w-8 h-8 rounded-full bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20">
                <Cpu className="w-4 h-4 text-emerald-400" />
              </div>
              <span className="text-gray-200 font-semibold truncate">{agent.name}</span>
            </div>
            <div className="flex items-center space-x-2 text-xs text-gray-400 mb-3">
              <HardDrive className="w-3.5 h-3.5 text-gray-500 shrink-0" />
              <span className="text-gray-300 font-mono truncate">{agent.model_name}</span>
              <span className="opacity-60">({agent.provider})</span>
            </div>
            {/* Mode selector */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Zeka Modu</span>
                {isDetectingMode && <Loader2 className="w-3 h-3 text-gray-500 animate-spin" />}
                {agent.agent_mode_override && (
                  <button
                    onClick={() => handleModeChange(null)}
                    className="text-[9px] text-gray-500 hover:text-red-400 transition-colors flex items-center gap-1"
                    title="Otomatiğe döndür"
                  >
                    <X className="w-2.5 h-2.5" />  Sıfırla
                  </button>
                )}
              </div>
              <div className="grid grid-cols-4 gap-1">
                {/* AUTO button */}
                <button
                  onClick={() => handleModeChange(null)}
                  className={`flex flex-col items-center justify-center py-2 px-1 rounded-xl border text-center transition-all ${
                    !agent.agent_mode_override
                      ? 'bg-gray-700/80 border-gray-500 text-white'
                      : 'bg-gray-900/40 border-gray-800 text-gray-500 hover:border-gray-600 hover:text-gray-400'
                  }`}
                >
                  <Zap className="w-3 h-3 mb-0.5" />
                  <span className="text-[9px] font-bold">AUTO</span>
                  {!agent.agent_mode_override && (
                    <span className="text-[7px] opacity-60 mt-0.5">{activeMode[0]}{activeMode.slice(1).toLowerCase().slice(0,2)}</span>
                  )}
                </button>
                {/* Mode buttons */}
                {['STRICT', 'STANDARD', 'ENHANCED'].map((m) => {
                  const isActive = agent.agent_mode_override === m;
                  const btnColors = {
                    STRICT:   isActive ? 'bg-amber-500/20 border-amber-500/60 text-amber-300' : 'bg-gray-900/40 border-gray-800 text-gray-500 hover:border-amber-700/50 hover:text-amber-500/70',
                    STANDARD: isActive ? 'bg-blue-500/20 border-blue-500/60 text-blue-300'   : 'bg-gray-900/40 border-gray-800 text-gray-500 hover:border-blue-700/50 hover:text-blue-500/70',
                    ENHANCED: isActive ? 'bg-emerald-500/20 border-emerald-500/60 text-emerald-300' : 'bg-gray-900/40 border-gray-800 text-gray-500 hover:border-emerald-700/50 hover:text-emerald-500/70',
                  }[m];
                  const labels = { STRICT: 'STR', STANDARD: 'STD', ENHANCED: 'ENH' };
                  const icons  = { STRICT: '🐢', STANDARD: '⚡', ENHANCED: '🚀' };
                  return (
                    <button
                      key={m}
                      onClick={() => handleModeChange(m)}
                      className={`flex flex-col items-center justify-center py-2 px-1 rounded-xl border text-center transition-all ${btnColors}`}
                    >
                      <span className="text-[11px] mb-0.5">{icons[m]}</span>
                      <span className="text-[9px] font-bold">{labels[m]}</span>
                    </button>
                  );
                })}
              </div>
              {/* Active mode description */}
              <div className={`text-[10px] px-2 py-1 rounded-lg ${modeColors[activeMode]}`}>
                <span className="font-semibold">{modeMeta.label}:</span> {modeMeta.desc}
                {!agent.agent_mode_override && <span className="opacity-60 ml-1">(otomatik)</span>}
              </div>
            </div>
            {/* Stats */}
            {stats && (
              <div className="flex gap-3 mt-3">
                <div className="flex-1 text-center bg-gray-800/50 rounded-xl p-2">
                  <div className="text-base font-bold text-gray-200">{stats.message_count}</div>
                  <div className="text-[9px] text-gray-500 uppercase tracking-wider">Mesaj</div>
                </div>
                <div className="flex-1 text-center bg-gray-800/50 rounded-xl p-2">
                  <div className="text-base font-bold text-gray-200">{stats.document_count}</div>
                  <div className="text-[9px] text-gray-500 uppercase tracking-wider">Dosya</div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Plugins */}
        <div className="space-y-3">
          <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest pl-1">Eklentiler</h4>
          <ToggleCard icon={Globe}     label="Canlı İnternet"  desc="Online arama yeteneği"    active={agent.internet_enabled}   onToggle={() => onUpdate({ ...agent, internet_enabled: !agent.internet_enabled })}   colorOn="blue" />
          <ToggleCard icon={Database}  label="Hafıza (DB)"     desc="Bağlam hatırası"           active={agent.memory_enabled}     onToggle={() => onUpdate({ ...agent, memory_enabled: !agent.memory_enabled })}         colorOn="purple" />
          <ToggleCard icon={Languages} label="Çeviri Ajanı"    desc="Çoklu dil algılama"        active={agent.translator_enabled} onToggle={() => onUpdate({ ...agent, translator_enabled: !agent.translator_enabled })} colorOn="emerald" />
          <ToggleCard icon={FileText}  label="Dosya Bilgisi"   desc="RAG — Belge sorgulama"     active={agent.document_enabled}   onToggle={() => onUpdate({ ...agent, document_enabled: !agent.document_enabled })}   colorOn="violet" />
          <ToggleCard icon={Zap}       label="MCP Araçları"    desc="Dış protokol (Search vb.)"  active={agent.mcp_enabled}        onToggle={() => onUpdate({ ...agent, mcp_enabled: !agent.mcp_enabled })}        colorOn="blue" />
        </div>

        {/* RAG Documents section */}
        <AnimatePresence>
          {agent.document_enabled && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-3 overflow-hidden"
            >
              <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest pl-1">Belgeler</h4>

              {/* Upload zone */}
              <label
                className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border-2 border-dashed cursor-pointer transition-all ${
                  isDragging
                    ? 'border-violet-400 bg-violet-500/10'
                    : 'border-gray-700 hover:border-violet-500/50 hover:bg-violet-500/5'
                }`}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setIsDragging(false);
                  const f = e.dataTransfer.files[0];
                  if (f) handleFileUpload(f);
                }}
              >
                <input
                  type="file"
                  className="hidden"
                  accept=".txt,.md,.pdf,.docx,.rst,.csv"
                  onChange={(e) => { if (e.target.files[0]) handleFileUpload(e.target.files[0]); }}
                  disabled={isUploading}
                />
                {isUploading ? (
                  <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
                ) : (
                  <Upload className="w-5 h-5 text-gray-500" />
                )}
                <span className="text-[11px] text-gray-500">
                  {isUploading ? 'Yükleniyor & İndeksleniyor...' : 'Dosya yükle (PDF, TXT, DOCX)'}
                </span>
              </label>

              {/* Document list */}
              {documents.length > 0 && (
                <div className="space-y-2">
                  {documents.map((doc) => (
                    <motion.div
                      key={doc.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex items-center justify-between bg-gray-900/80 border border-gray-800/60 rounded-2xl px-4 py-3 hover:bg-gray-800/60 transition-all group"
                    >
                      <div className="flex items-center space-x-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-gray-950 flex items-center justify-center border border-gray-800 group-hover:border-violet-500/30 transition-colors">
                          {getFileIcon(doc.original_name)}
                        </div>
                        <div className="min-w-0">
                          <div className="text-[12px] text-gray-200 truncate font-semibold">{doc.original_name}</div>
                          <div className="text-[10px] text-gray-500 font-mono">
                            {doc.chunk_count} parça · {(doc.file_size / 1024).toFixed(1)} KB
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteDoc(doc.id);
                        }}
                        className="p-1.5 rounded-lg hover:bg-red-500/10 text-gray-500 hover:text-red-400 transition-all shrink-0 ml-2 group-hover:opacity-100 opacity-60"
                        title="Dosyayı Sil"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </motion.div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Danger zone */}
        <div className="space-y-3">
          <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest pl-1">Yönetim</h4>
          <button
            onClick={handleClearChat}
            className="w-full flex items-center justify-center space-x-2 p-3 rounded-2xl border border-red-900/50 bg-red-500/5 text-red-400 hover:bg-red-500/15 hover:border-red-500/40 transition-all text-xs font-semibold"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Sohbet Geçmişini Temizle</span>
          </button>
        </div>
      </div>
    </div>
  );
}
