import React, { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, AlertCircle, Zap, Search, Eye, Clock } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function EvaluationDashboard({ agent }) {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!agent?.id) return;
    
    const fetchMetrics = async () => {
      try {
        const response = await axios.get(`${API_URL}/agents/${agent.id}/metrics`);
        setMetrics(response.data);
      } catch (error) {
        console.error('Failed to fetch metrics:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchMetrics();
    // Refresh metrics every 10 seconds
    const interval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(interval);
  }, [agent?.id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-gray-400">
        <div className="animate-spin">⏳</div> Metrikler yükleniyor...
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="flex items-center justify-center p-8 text-gray-400">
        Henüz veri yok
      </div>
    );
  }

  const MetricCard = ({ icon: Icon, label, value, unit = '', trend = null, color = 'emerald' }) => (
    <div className={`bg-gray-800/40 border border-gray-700/50 rounded-xl p-4 backdrop-blur-sm`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-widest text-gray-400">{label}</span>
        <Icon className={`w-4 h-4 text-${color}-400`} />
      </div>
      <div className="text-2xl font-bold text-white">
        {typeof value === 'number' && value % 1 !== 0 
          ? value.toFixed(2) 
          : value}{unit}
      </div>
      {trend && (
        <div className={`text-xs mt-1 ${trend > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
          {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}%
        </div>
      )}
    </div>
  );

  const confidenceColor = metrics.avg_confidence > 0.7 ? 'emerald' : 
                          metrics.avg_confidence > 0.4 ? 'yellow' : 'red';

  const hallucinationRate = metrics.total_responses > 0 
    ? (metrics.hallucination_count / metrics.total_responses * 100).toFixed(1)
    : 0;

  const toolUsageRate = metrics.total_responses > 0
    ? ((metrics.tool_search_count + metrics.tool_scrape_count) / metrics.total_responses * 100).toFixed(1)
    : 0;

  const ragHitRatePercent = (metrics.rag_hit_rate * 100).toFixed(1);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center space-x-2 Text-gray-300 mb-6">
        <BarChart3 className="w-5 h-5 text-blue-400" />
        <h3 className="text-lg font-semibold">İstatistikler & Metrikler</h3>
      </div>

      {/* Primary Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard 
          icon={Zap} 
          label="Güvenilirlik" 
          value={metrics.avg_confidence} 
          unit="" 
          color={confidenceColor}
        />
        <MetricCard 
          icon={AlertCircle} 
          label="Halüsinasyon Oranı" 
          value={hallucinationRate} 
          unit="%" 
          color="red"
        />
        <MetricCard 
          icon={Search} 
          label="Araç Kullanımı" 
          value={toolUsageRate} 
          unit="%" 
          color="blue"
        />
        <MetricCard 
          icon={Clock} 
          label="Ort. Yanıt Sür." 
          value={metrics.avg_response_latency_ms} 
          unit="ms" 
          color="purple"
        />
      </div>

      {/* Tool Usage Details */}
      <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-4 backdrop-blur-sm">
        <h4 className="text-sm font-semibold text-gray-300 mb-3">Araç Kullanımı</h4>
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-400">🔍 Arama (search)</span>
            <span className="text-white font-semibold">{metrics.tool_search_count} kez</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-400">📖 Tarama (scrape)</span>
            <span className="text-white font-semibold">{metrics.tool_scrape_count} kez</span>
          </div>
        </div>
      </div>

      {/* Reliability Metrics */}
      <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-4 backdrop-blur-sm">
        <h4 className="text-sm font-semibold text-gray-300 mb-3">Güvenilirlik Analizi</h4>
        <div className="space-y-3">
          <div>
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-400">Ortalama Güvenilirlik Skoru</span>
              <span className="text-white font-semibold">{(metrics.avg_confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all ${
                  metrics.avg_confidence > 0.7 ? 'bg-emerald-500' :
                  metrics.avg_confidence > 0.4 ? 'bg-yellow-500' : 'bg-red-500'
                }`}
                style={{ width: `${metrics.avg_confidence * 100}%` }}
              />
            </div>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Halüsinasyon Bayrakları</span>
            <span className={`font-semibold ${metrics.hallucination_count > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              {metrics.hallucination_count}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Belirsiz Cevaplar</span>
            <span className="text-yellow-400 font-semibold">{metrics.uncertain_count}</span>
          </div>
        </div>
      </div>

      {/* RAG Metrics */}
      {metrics.rag_retrieval_count > 0 && (
        <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-4 backdrop-blur-sm">
          <h4 className="text-sm font-semibold text-gray-300 mb-3">📚 RAG Performansı</h4>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Toplam Retrieval</span>
              <span className="text-white font-semibold">{metrics.rag_retrieval_count}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Hit Rate (İlgili)</span>
              <span className="text-emerald-400 font-semibold">{ragHitRatePercent}%</span>
            </div>
          </div>
        </div>
      )}

      {/* RAG Re-ranking Metrics (ML Enhancement) */}
      {metrics.rag_reranking_count > 0 && (
        <div className="bg-indigo-900/20 border border-indigo-700/30 rounded-xl p-4 backdrop-blur-sm">
          <h4 className="text-sm font-semibold text-indigo-300 mb-3">🚀 RAG ML Re-ranking Performansı</h4>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Re-ranking Uygulaması</span>
              <span className="text-indigo-300 font-semibold">{metrics.rag_reranking_count} kez</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Ort. Skor İyileştirmesi</span>
              <span className="text-emerald-400 font-semibold">+{metrics.rag_reranking_avg_improvement?.toFixed(3)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Ort. Konum Hareketi</span>
              <span className="text-blue-400 font-semibold">{metrics.rag_reranking_position_avg?.toFixed(1)} pozisyon ↑</span>
            </div>
            <div className="mt-3 p-2 bg-indigo-900/40 rounded text-xs text-indigo-200 border border-indigo-700/20">
              ML cross-encoder modeli kullanılarak RAG sonuçları yeniden sıralanıyor. 
              Ortalama {metrics.rag_reranking_avg_improvement?.toFixed(3)} skor iyileştirmesi sağlanıyor.
            </div>
          </div>
        </div>
      )}

      {/* Response Statistics */}
      <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-4 backdrop-blur-sm">
        <h4 className="text-sm font-semibold text-gray-300 mb-3">Yanıt İstatistikleri</h4>
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Toplam Yanıt</span>
            <span className="text-white font-semibold">{metrics.total_responses}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Ort. Yanıt Süresi</span>
            <span className="text-blue-400 font-semibold">{metrics.avg_response_latency_ms.toFixed(0)}ms</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Bağlam Kaybı Olayları</span>
            <span className={`font-semibold ${metrics.context_loss_events > 0 ? 'text-orange-400' : 'text-emerald-400'}`}>
              {metrics.context_loss_events}
            </span>
          </div>
        </div>
      </div>

      {/* Tips */}
      <div className="bg-blue-900/20 border border-blue-700/30 rounded-xl p-4 text-xs text-blue-300">
        <p className="font-semibold mb-1">💡 İpuçları:</p>
        <ul className="space-y-1 list-disc list-inside">
          <li>Güvenilirlik %70+ olmalıdır (yeşil). Kırmızı ise internet araması açın.</li>
          <li>Halüsinasyon oranı düşük tutun - şüpheli cevapları işaretle.</li>
          <li>RAG hit rate %60+ olmalıdır - belge kalitesini kontrol edin.</li>
        </ul>
      </div>
    </div>
  );
}
