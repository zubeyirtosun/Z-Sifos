import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion'; // eslint-disable-line no-unused-vars

const STORAGE_PROVIDERS = [
  {
    value: 'ollama',
    label: 'Ollama',
    description:
      'Ollama provider, yerel Ollama kurulumu veya remote Ollama modelleri için uygundur. Model adı olarak Ollama model ismini girin.',
    examples: ['tinyllama', 'llama2', 'llama3'],
  },
  {
    value: 'llamacpp',
    label: 'Hugging Face / LlamaCpp',
    description:
      'Hugging Face GGUF modelleri için LlamaCpp provider kullanılır. Model adı alanına yereldeki .gguf dosya yolu veya model adı girilebilir.',
    examples: ['/models/vicuna-gguf.q4_0.bin', 'alpaca-native-gguf.q4_0.bin', 'llama-2-7b.gguf'],
  },
];

export default function NewAgentModal({ open, onClose, onCreate, providers = [], providerModels = [] }) {
  const [name, setName] = useState('Yeni Ajan');
  const [provider, setProvider] = useState('ollama');
  const [modelName, setModelName] = useState('tinyllama');
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [internetEnabled, setInternetEnabled] = useState(false);
  const [translatorEnabled, setTranslatorEnabled] = useState(false);
  const [documentEnabled, setDocumentEnabled] = useState(false);
  const [mcpEnabled, setMcpEnabled] = useState(false);
  const [activeTab, setActiveTab] = useState('local'); // 'local' or 'library'
  const [libraryModels, setLibraryModels] = useState([]);
  const [modelInfo, setModelInfo] = useState(null);
  const [isLoadingLibrary, setIsLoadingLibrary] = useState(false);

  // Provider değişince modelleri ve kütüphaneyi çek
  useEffect(() => {
    if (open) {
      fetchLibraryModels(provider);
    }
  }, [open, provider]);

  // Model seçilince teknik detayları çek
  useEffect(() => {
    if (open && modelName) {
      fetchModelInfo(modelName, provider);
    }
  }, [open, modelName, provider]);

  const fetchLibraryModels = async (p) => {
    setIsLoadingLibrary(true);
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/providers/${p}/models?local=false`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      const data = await resp.json();
      setLibraryModels(data.models || []);
    } catch (e) {
      console.error("Library fetch error:", e);
    } finally {
      setIsLoadingLibrary(false);
    }
  };

  const fetchModelInfo = async (m, p) => {
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/models/info?model_name=${m}&provider=${p}`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      const data = await resp.json();
      setModelInfo(data);
    } catch (e) {
      setModelInfo(null);
    }
  };

  const currentProvider = useMemo(() => {
    return (
      providers.find((item) => item.name === provider) ||
      providers.find((item) => item.value === provider) ||
      STORAGE_PROVIDERS.find((item) => item.value === provider) ||
      STORAGE_PROVIDERS[0]
    );
  }, [provider, providers]);

  const selectedExamples = currentProvider.examples || STORAGE_PROVIDERS.find((item) => item.value === provider)?.examples || [];

  const handleSubmit = (event) => {
    event.preventDefault();
    onCreate({
      name,
      provider,
      model_name: modelName,
      memory_enabled: memoryEnabled,
      internet_enabled: internetEnabled,
      translator_enabled: translatorEnabled,
      document_enabled: documentEnabled,
      mcp_enabled: mcpEnabled,
      model_metadata: modelInfo ? JSON.stringify(modelInfo) : null,
      status: providerModels.includes(modelName) ? 'ready' : 'downloading'
    });
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4 bg-gray-950/80 backdrop-blur-md font-sans">
          <motion.div 
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="w-full max-w-4xl rounded-[2.5rem] border border-gray-800/80 bg-gray-900/95 shadow-2xl p-10 relative overflow-hidden flex flex-col max-h-[90vh]"
          >
            <div className="flex items-center justify-between mb-8">
              <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-500">Yeni Ajan Arşitip'i</h2>
              <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
            </div>

            <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto space-y-8 pr-2 custom-scrollbar">
              <div className="grid lg:grid-cols-2 gap-10">
                {/* Sol Kolon: Temel Bilgiler */}
                <div className="space-y-6">
                  <div className="space-y-2">
                    <label className="text-sm font-semibold text-gray-400 ml-1">Ajan Adı</label>
                    <input value={name} onChange={e => setName(e.target.value)} className="w-full h-14 rounded-2xl bg-gray-800/50 border border-gray-700 px-6 focus:ring-2 focus:ring-blue-500 outline-none transition-all" />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-semibold text-gray-400 ml-1">Motor (Provider)</label>
                    <select value={provider} onChange={e => setProvider(e.target.value)} className="w-full h-14 rounded-2xl bg-gray-800/50 border border-gray-700 px-6 focus:ring-2 focus:ring-blue-500 outline-none transition-all appearance-none cursor-pointer">
                      {providers.map(p => <option key={p.name} value={p.name}>{p.label}</option>)}
                    </select>
                  </div>

                  {/* Model Detay Kartı */}
                  {modelInfo && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="p-6 rounded-3xl bg-blue-500/5 border border-blue-500/20 space-y-4">
                      <div className="flex justify-between items-center text-sm">
                        <span className="text-blue-400 font-bold">MODEL BİLGİSİ</span>
                        <span className="bg-blue-500/20 px-3 py-1 rounded-full text-[10px] text-blue-300 uppercase tracking-widest">{modelInfo.format || 'GGUF'}</span>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                          <div className="text-[10px] text-gray-500 uppercase tracking-wider">Boyut</div>
                          <div className="text-lg font-mono text-gray-200">{modelInfo.size}</div>
                        </div>
                        <div className="space-y-1">
                          <div className="text-[10px] text-gray-500 uppercase tracking-wider">Bağlam (Context)</div>
                          <div className="text-lg font-mono text-gray-200">{modelInfo.context}</div>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  <div className="space-y-4">
                    <label className="text-sm font-semibold text-gray-400">Yetenekler</label>
                    {[
                      { id: 'mem', label: 'Kalıcı Hafıza',    desc: 'Diyalogları veritabanına kaydet',    active: memoryEnabled,     setter: setMemoryEnabled,     color: 'purple' },
                      { id: 'web', label: 'İnternet Arama',   desc: 'Anlık web araştırması yapabilir',   active: internetEnabled,    setter: setInternetEnabled,   color: 'blue' },
                      { id: 'tr',  label: 'Çeviri Desteği',   desc: 'Diller arası otomatik köprü',       active: translatorEnabled,  setter: setTranslatorEnabled, color: 'emerald' },
                      { id: 'doc', label: 'Dosya Bilgisi',    desc: 'RAG — PDF/TXT/DOCX sorgulama',     active: documentEnabled,    setter: setDocumentEnabled,   color: 'violet' },
                      { id: 'mcp', label: 'MCP Entegrasyonu', desc: 'Dış araçlar (Search vb.) desteği',  active: mcpEnabled,         setter: setMcpEnabled,        color: 'blue' },
                    ].map(item => (
                      <div key={item.id} className="flex justify-between items-center bg-gray-800/30 p-4 rounded-2xl border border-gray-700/50">
                        <div>
                          <div className="text-sm font-bold text-gray-200">{item.label}</div>
                          <div className="text-[11px] text-gray-500">{item.desc}</div>
                        </div>
                        <button type="button" onClick={() => item.setter(!item.active)} className={`w-12 h-7 rounded-full transition-all flex items-center px-1 ${item.active ? `bg-${item.color}-500` : 'bg-gray-700'}`}>
                          <div className={`w-5 h-5 bg-white rounded-full transition-all ${item.active ? 'translate-x-5' : 'translate-x-0'}`} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Sağ Kolon: Model Discovery */}
                <div className="flex flex-col space-y-4">
                  <div className="flex bg-gray-800/50 p-1.5 rounded-2xl border border-gray-700 mb-2">
                    <button type="button" onClick={() => setActiveTab('local')} className={`flex-1 py-2 rounded-xl text-xs font-bold transition-all ${activeTab === 'local' ? 'bg-gray-700 text-white shadow-lg' : 'text-gray-500'}`}>YÜKLÜ MODELLER</button>
                    <button type="button" onClick={() => setActiveTab('library')} className={`flex-1 py-2 rounded-xl text-xs font-bold transition-all ${activeTab === 'library' ? 'bg-gray-700 text-white shadow-lg' : 'text-gray-500'}`}>KÜTÜPHANE</button>
                  </div>

                  <div className="flex-1 min-h-[400px] border border-gray-700/50 rounded-3xl p-4 space-y-2 overflow-y-auto bg-black/20">
                    <input 
                      placeholder="Model ara veya isim yaz..." 
                      value={modelName} 
                      onChange={e => setModelName(e.target.value)}
                      className="w-full bg-gray-800/80 border border-gray-700 rounded-xl px-4 py-2.5 text-sm mb-4 focus:border-blue-500 outline-none"
                    />

                    {activeTab === 'local' ? (
                      <div className="grid gap-2">
                        {providerModels && providerModels.length > 0 ? providerModels.map(m => (
                          <button key={m} type="button" onClick={() => setModelName(m)} className={`text-left p-3 rounded-xl border transition-all text-xs font-mono truncate ${modelName === m ? 'bg-blue-500/10 border-blue-500 text-blue-400' : 'bg-gray-800/40 border-transparent text-gray-400 hover:border-gray-600'}`}>{m}</button>
                        )) : (
                          <div className="text-center text-gray-600 py-10 text-xs">Yüklü model bulunamadı.</div>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {isLoadingLibrary ? (
                          <div className="text-center text-gray-500 py-10 animate-pulse text-sm">Modeller taranıyor...</div>
                        ) : libraryModels && libraryModels.length > 0 ? libraryModels.map((lm, idx) => (
                          <button key={lm.name || idx} type="button" onClick={() => setModelName(lm.name)} className={`w-full text-left p-4 rounded-2xl border transition-all group ${modelName === lm.name ? 'bg-emerald-500/10 border-emerald-500' : 'bg-gray-800/40 border-transparent hover:border-gray-700'}`}>
                            <div className="flex justify-between items-start">
                              <span className={`text-[13px] font-bold truncate ${modelName === lm.name ? 'text-emerald-400' : 'text-gray-300'}`}>{lm.name || 'Unknown'}</span>
                              <span className="text-[10px] bg-gray-700 px-2 py-0.5 rounded-md text-gray-400">{lm.size || 'N/A'}</span>
                            </div>
                            <div className="text-[10px] text-gray-500 mt-1 line-clamp-1 group-hover:line-clamp-none transition-all italic">{lm.description || 'Description not available'}</div>
                          </button>
                        )) : (
                          <div className="text-center text-gray-600 py-10 text-xs">Kütüphane modellerine şu an erişilemiyor.</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex gap-4 justify-end pt-6 border-t border-gray-800">
                <button type="button" onClick={onClose} className="px-8 py-3.5 rounded-2xl text-gray-400 font-bold hover:bg-gray-800">VAZGEÇ</button>
                <button type="submit" className="px-10 py-3.5 rounded-2xl bg-gradient-to-r from-blue-600 to-emerald-500 text-white font-bold shadow-xl hover:scale-105 active:scale-95 transition-all">
                  {providerModels.includes(modelName) ? 'AJANI BAŞLAT' : 'AJANI OLUŞTUR VE İNDİR'}
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
