import React, { useState, useRef, useEffect } from 'react';
import { 
  Upload, Copy, Check, Trash2, FileSpreadsheet, Sparkles, 
  RefreshCw, AlertCircle, Settings, ChevronDown, ChevronUp 
} from 'lucide-react';

interface MetadataItem {
  id: string;
  file: File;
  previewUrl: string;
  status: 'pending' | 'processing' | 'done' | 'error';
  metadata: {
    title: string;
    description: string;
    keywords: string;
  };
  errorMessage?: string;
}

const DEFAULT_PROMPT = `You are an expert stock image contributor. Look closely at the uploaded image and write natural, highly accurate metadata in English. Do not be robotic or formulaic. Focus on what is ACTUALLY in the image.

1. Title
- Write a natural, descriptive title that perfectly captures exactly what is happening or shown in the image.
- Write it as a human would naturally search for this specific image.
- Vary your sentence structure based on the image (e.g., an icon set is described very differently than a landscape, a pattern, or a portrait).
- Make it flow naturally. Minimum 7 words. No copyright or trademark words.

2. Description
- Write 1-2 natural sentences explaining the visual content, style, color, and mood of the image.
- Describe exactly what you see.
- Minimum 15 words. No copyright or trademark words.

3. Keywords (Max 45 words)
- Provide highly relevant keywords based EXACTLY on the image content. Do not hallucinate concepts that aren't there.
- Start with the most literal and important subject of the image.
- Mix literal visual elements (objects, colors, actions) and natural conceptual meanings.
- Separate with commas.
- Rules: Singular form only. No special characters (- , . + = /). No diacritics. 
- FORBIDDEN WORDS: "photo", "vector", "video", "illustration", "image", "background".
- Do not spam keywords. Every word must add value to the specific image.

Return ONLY pure JSON in this format without code block, markdown, or extra text:
{
  "title": "...",
  "description": "...",
  "keywords": "..."
}`;

export const VecteezyMetadataGenerator: React.FC = () => {
  const [imagesData, setImagesData] = useState<MetadataItem[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processedCount, setProcessedCount] = useState(0);
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [customPrompt, setCustomPrompt] = useState(DEFAULT_PROMPT);
  const [showSettings, setShowSettings] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // API Config State
  const [provider, setProvider] = useState<'9router' | 'openrouter' | 'gemini' | 'custom'>('9router');
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('vecto_ai_meta_key') || '');
  const [baseUrl, setBaseUrl] = useState(() => localStorage.getItem('vecto_ai_meta_base') || 'https://api.9router.com/v1');
  const [model, setModel] = useState(() => localStorage.getItem('vecto_ai_meta_model') || 'gpt-4o-mini');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  // Save settings to LocalStorage
  useEffect(() => {
    localStorage.setItem('vecto_ai_meta_key', apiKey);
    localStorage.setItem('vecto_ai_meta_base', baseUrl);
    localStorage.setItem('vecto_ai_meta_model', model);
  }, [apiKey, baseUrl, model]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleProviderChange = (newProvider: '9router' | 'openrouter' | 'gemini' | 'custom') => {
    setProvider(newProvider);
    if (newProvider === '9router') {
      setBaseUrl('https://api.9router.com/v1');
      setModel('gpt-4o-mini');
    } else if (newProvider === 'openrouter') {
      setBaseUrl('https://openrouter.ai/api/v1');
      setModel('google/gemini-flash-1.5');
    } else if (newProvider === 'gemini') {
      setBaseUrl('https://generativelanguage.googleapis.com/v1beta');
      setModel('gemini-1.5-flash');
    }
  };

  const copyPrompt = () => {
    navigator.clipboard.writeText(customPrompt).then(() => {
      setCopiedPrompt(true);
      showToast("Prompt berhasil disalin!");
      setTimeout(() => setCopiedPrompt(false), 2000);
    });
  };

  const handleFiles = (files: FileList | File[]) => {
    const validFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
    if (validFiles.length === 0) return;

    const newItems: MetadataItem[] = validFiles.map(file => ({
      id: 'img_' + Date.now() + '_' + Math.random().toString(36).substring(2, 7),
      file,
      previewUrl: URL.createObjectURL(file),
      status: 'pending',
      metadata: { title: '', description: '', keywords: '' }
    }));

    setImagesData(prev => [...prev, ...newItems]);
    showToast(`${newItems.length} gambar berhasil ditambahkan.`);
  };

  const removeImage = (id: string) => {
    setImagesData(prev => {
      const item = prev.find(i => i.id === id);
      if (item) URL.revokeObjectURL(item.previewUrl);
      return prev.filter(i => i.id !== id);
    });
  };

  const clearAllImages = () => {
    imagesData.forEach(img => URL.revokeObjectURL(img.previewUrl));
    setImagesData([]);
    setShowConfirmModal(false);
    showToast("Semua gambar telah dibersihkan.");
  };

  const updateMetadataField = (id: string, field: 'title' | 'description' | 'keywords', val: string) => {
    setImagesData(prev => prev.map(img => 
      img.id === id ? { ...img, metadata: { ...img.metadata, [field]: val } } : img
    ));
  };

  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const res = reader.result as string;
        resolve(res.split(',')[1]);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  const parseJsonFromResponse = (text: string) => {
    try {
      // 1. Direct parse
      return JSON.parse(text);
    } catch {
      // 2. Clean markdown code blocks like ```json ... ```
      const cleaned = text.replace(/```(?:json)?/gi, '').replace(/```/g, '').trim();
      try {
        return JSON.parse(cleaned);
      } catch {
        // 3. Extract JSON object substring
        const start = cleaned.indexOf('{');
        const end = cleaned.lastIndexOf('}');
        if (start !== -1 && end !== -1 && end > start) {
          return JSON.parse(cleaned.substring(start, end + 1));
        }
        throw new Error("Gagal mengekstrak format JSON dari respons AI");
      }
    }
  };

  const call9RouterOrOpenAI = async (base64Data: string, mimeType: string) => {
    const endpoint = baseUrl.endsWith('/') ? `${baseUrl}chat/completions` : `${baseUrl}/chat/completions`;
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
        'HTTP-Referer': window.location.origin,
        'X-Title': 'VectoAI Metadata Generator'
      },
      body: JSON.stringify({
        model: model,
        messages: [
          {
            role: 'user',
            content: [
              { type: 'text', text: customPrompt },
              {
                type: 'image_url',
                image_url: {
                  url: `data:${mimeType};base64,${base64Data}`
                }
              }
            ]
          }
        ],
        temperature: 0.2
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`API Error (${response.status}): ${errText.substring(0, 150)}`);
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content || '';
    return parseJsonFromResponse(content);
  };

  const callGeminiDirect = async (base64Data: string, mimeType: string) => {
    const url = `${baseUrl}/models/${model}:generateContent?key=${apiKey}`;
    const payload = {
      contents: [
        {
          role: 'user',
          parts: [
            { text: customPrompt },
            {
              inlineData: {
                mimeType: mimeType,
                data: base64Data
              }
            }
          ]
        }
      ],
      generationConfig: {
        responseMimeType: 'application/json'
      }
    };

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Gemini Error (${response.status}): ${errText.substring(0, 150)}`);
    }

    const result = await response.json();
    const partText = result.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!partText) throw new Error("Respons kosong dari Gemini");
    return parseJsonFromResponse(partText);
  };

  const processAllImages = async () => {
    if (isProcessing) return;
    if (!apiKey.trim()) {
      setShowSettings(true);
      showToast("Harap masukkan API Key terlebih dahulu di menu Pengaturan API!");
      return;
    }

    const pending = imagesData.filter(img => img.status === 'pending' || img.status === 'error');
    if (pending.length === 0) {
      showToast("Tidak ada gambar yang perlu diproses.");
      return;
    }

    setIsProcessing(true);
    setProcessedCount(0);

    for (let i = 0; i < pending.length; i++) {
      const item = pending[i];

      setImagesData(prev => prev.map(img => 
        img.id === item.id ? { ...img, status: 'processing', errorMessage: undefined } : img
      ));

      try {
        const base64Data = await fileToBase64(item.file);
        const mimeType = item.file.type || 'image/jpeg';

        let parsed: any;
        if (provider === 'gemini') {
          parsed = await callGeminiDirect(base64Data, mimeType);
        } else {
          parsed = await call9RouterOrOpenAI(base64Data, mimeType);
        }

        setImagesData(prev => prev.map(img => 
          img.id === item.id ? {
            ...img,
            status: 'done',
            metadata: {
              title: parsed.title || '',
              description: parsed.description || '',
              keywords: parsed.keywords || ''
            }
          } : img
        ));
      } catch (err: any) {
        console.error("AI Error:", err);
        setImagesData(prev => prev.map(img => 
          img.id === item.id ? {
            ...img,
            status: 'error',
            errorMessage: err.message || 'Gagal memproses gambar'
          } : img
        ));
      }

      setProcessedCount(i + 1);
    }

    setIsProcessing(false);
    showToast("Semua proses AI selesai!");
  };

  const exportToCSV = () => {
    if (imagesData.length === 0) {
      showToast("Tidak ada data gambar untuk diekspor.");
      return;
    }

    const headers = ["Filename", "Title", "Description", "Keywords"];
    const escapeCsv = (str: string) => `"${(str || '').replace(/"/g, '""')}"`;

    const rows = imagesData.map(img => [
      escapeCsv(img.file.name),
      escapeCsv(img.metadata.title),
      escapeCsv(img.metadata.description),
      escapeCsv(img.metadata.keywords)
    ].join(","));

    const csvContent = "\uFEFF" + [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `vecteezy_metadata_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast("File CSV Vecteezy berhasil diunduh!");
  };

  return (
    <div className="w-full flex flex-col gap-6 text-slate-200">
      
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-orange-950/40 via-amber-950/20 to-slate-900 border border-orange-500/30 rounded-2xl p-6 shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="p-2 rounded-xl bg-orange-500/20 text-orange-400 border border-orange-500/30 font-bold text-lg">⚡</span>
            <h2 className="text-xl md:text-2xl font-bold text-white tracking-wide">
              Vecteezy Batch Metadata Generator
            </h2>
          </div>
          <p className="text-sm text-slate-400">
            Unggah gambar massal, hasilkan metadata AI teroptimasi standar Vecteezy (9router / OpenRouter / Gemini), dan ekspor CSV.
          </p>
        </div>

        <button 
          onClick={() => setShowSettings(!showSettings)}
          className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-300 transition flex items-center gap-2 shadow-sm"
        >
          <Settings className="w-4 h-4 text-orange-400" />
          <span>Pengaturan API (9router)</span>
          {showSettings ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-lg space-y-4 animate-in fade-in duration-200">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Settings className="w-4 h-4 text-orange-400" />
              Konfigurasi API AI (9router / Multi-Provider)
            </h3>
            <span className="text-[11px] text-slate-400">Tersimpan otomatis di browser</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">Provider AI</label>
              <select 
                value={provider} 
                onChange={(e) => handleProviderChange(e.target.value as any)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-orange-500"
              >
                <option value="9router">9router (Default)</option>
                <option value="openrouter">OpenRouter.ai</option>
                <option value="gemini">Google Gemini Direct</option>
                <option value="custom">Custom OpenAI Compatible</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">API Base URL</label>
              <input 
                type="text" 
                value={baseUrl} 
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.9router.com/v1"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-orange-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">Model AI</label>
              <input 
                type="text" 
                value={model} 
                onChange={(e) => setModel(e.target.value)}
                placeholder="gpt-4o-mini / gemini-1.5-flash"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-orange-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">API Key</label>
              <input 
                type="password" 
                value={apiKey} 
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Masukkan API Key 9router..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-orange-500"
              />
            </div>
          </div>
        </div>
      )}

      {/* System Prompt Display & Copy */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
        <div className="flex justify-between items-center">
          <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-orange-400" />
            System Prompt AI Vecteezy (Auto-Strict Rules)
          </h3>
          <button 
            onClick={copyPrompt}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 border border-slate-700"
          >
            {copiedPrompt ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
            {copiedPrompt ? "Disalin!" : "Salin Prompt"}
          </button>
        </div>
        <textarea 
          value={customPrompt} 
          onChange={(e) => setCustomPrompt(e.target.value)}
          rows={4}
          className="w-full bg-slate-950/70 border border-slate-800 rounded-xl p-3 text-xs text-slate-400 font-mono leading-relaxed focus:outline-none focus:border-orange-500/50 resize-y"
        />
      </div>

      {/* Drag & Drop Area */}
      <div 
        ref={dropZoneRef}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('border-orange-500', 'bg-orange-950/10'); }}
        onDragLeave={(e) => { e.currentTarget.classList.remove('border-orange-500', 'bg-orange-950/10'); }}
        onDrop={(e) => {
          e.preventDefault();
          e.currentTarget.classList.remove('border-orange-500', 'bg-orange-950/10');
          handleFiles(e.dataTransfer.files);
        }}
        className="border-2 border-dashed border-slate-800 hover:border-orange-500/60 bg-slate-900/60 hover:bg-orange-950/5 rounded-2xl p-8 flex flex-col items-center justify-center cursor-pointer transition-all duration-200 group"
      >
        <input 
          type="file" 
          ref={fileInputRef} 
          onChange={(e) => e.target.files && handleFiles(e.target.files)} 
          multiple 
          accept="image/jpeg,image/png,image/webp" 
          className="hidden" 
        />
        <div className="w-14 h-14 rounded-2xl bg-orange-500/10 border border-orange-500/20 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
          <Upload className="w-7 h-7 text-orange-400" />
        </div>
        <p className="text-sm font-semibold text-slate-200 mb-1">
          Klik atau seret gambar ke sini untuk Batch Metadata
        </p>
        <p className="text-xs text-slate-400">
          Mendukung format JPG, PNG, dan WebP (Bisa pilih banyak file sekaligus)
        </p>
      </div>

      {/* Sticky Action Bar */}
      {imagesData.length > 0 && (
        <div className="sticky top-4 z-20 bg-slate-900/95 backdrop-blur-md border border-orange-500/30 p-4 rounded-2xl shadow-2xl flex flex-wrap justify-between items-center gap-4">
          <div className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <span>Total Berkas:</span>
            <span className="px-2.5 py-0.5 rounded-full bg-orange-500/20 text-orange-400 border border-orange-500/30 font-bold">
              {imagesData.length}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button 
              onClick={() => setShowConfirmModal(true)}
              disabled={isProcessing}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl transition flex items-center gap-2 border border-slate-700 disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5 text-red-400" />
              Hapus Semua
            </button>

            <button 
              onClick={processAllImages}
              disabled={isProcessing}
              className="px-5 py-2 bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500 hover:to-amber-500 text-white text-xs font-bold rounded-xl transition shadow-lg shadow-orange-600/20 flex items-center gap-2 disabled:opacity-50"
            >
              {isProcessing ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Memproses ({processedCount}/{imagesData.length})...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  <span>Hasilkan Metadata AI</span>
                </>
              )}
            </button>

            <button 
              onClick={exportToCSV}
              disabled={isProcessing}
              className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl transition shadow-lg shadow-emerald-600/20 flex items-center gap-2 disabled:opacity-50"
            >
              <FileSpreadsheet className="w-4 h-4" />
              <span>Ekspor CSV Vecteezy</span>
            </button>
          </div>
        </div>
      )}

      {/* Cards List */}
      <div className="flex flex-col gap-4">
        {imagesData.map((img) => (
          <div 
            key={img.id}
            className="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl p-5 shadow-md flex flex-col md:flex-row gap-5 transition"
          >
            {/* Thumbnail and Status */}
            <div className="flex flex-col items-center md:w-56 shrink-0 gap-3">
              <div className="w-full aspect-square rounded-xl overflow-hidden bg-slate-950 border border-slate-800 relative group">
                <img 
                  src={img.previewUrl} 
                  alt={img.file.name} 
                  className="w-full h-full object-cover" 
                />
                <button 
                  onClick={() => removeImage(img.id)}
                  className="absolute top-2 right-2 bg-red-600/80 hover:bg-red-600 text-white p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition shadow"
                  title="Hapus gambar"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              <div className="w-full text-center">
                <p className="text-xs font-medium text-slate-300 truncate px-2" title={img.file.name}>
                  {img.file.name}
                </p>
                <div className="mt-2 flex justify-center">
                  {img.status === 'pending' && (
                    <span className="px-2.5 py-1 bg-slate-800 text-slate-400 rounded-md text-[11px] font-medium border border-slate-700">
                      Menunggu
                    </span>
                  )}
                  {img.status === 'processing' && (
                    <span className="px-2.5 py-1 bg-blue-950/60 text-blue-400 rounded-md text-[11px] font-medium border border-blue-500/30 flex items-center gap-1.5">
                      <RefreshCw className="w-3 h-3 animate-spin" />
                      Menganalisis...
                    </span>
                  )}
                  {img.status === 'done' && (
                    <span className="px-2.5 py-1 bg-emerald-950/60 text-emerald-400 rounded-md text-[11px] font-medium border border-emerald-500/30 flex items-center gap-1">
                      <Check className="w-3.5 h-3.5" />
                      Selesai
                    </span>
                  )}
                  {img.status === 'error' && (
                    <span className="px-2.5 py-1 bg-red-950/60 text-red-400 rounded-md text-[11px] font-medium border border-red-500/30 flex items-center gap-1" title={img.errorMessage}>
                      <AlertCircle className="w-3.5 h-3.5" />
                      Gagal
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Editable Fields */}
            <div className="flex-grow flex flex-col gap-3 w-full">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">
                  Title (Judul)
                </label>
                <input 
                  type="text" 
                  value={img.metadata.title}
                  onChange={(e) => updateMetadataField(img.id, 'title', e.target.value)}
                  placeholder="Ketik manual atau klik Hasilkan Metadata AI..."
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-orange-500/70 rounded-xl text-sm text-slate-100 focus:outline-none transition"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">
                  Description (Deskripsi)
                </label>
                <textarea 
                  rows={2}
                  value={img.metadata.description}
                  onChange={(e) => updateMetadataField(img.id, 'description', e.target.value)}
                  placeholder="Ketik manual atau klik Hasilkan Metadata AI..."
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-orange-500/70 rounded-xl text-sm text-slate-100 focus:outline-none transition resize-y"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">
                  Keywords (Kata Kunci - Pisahkan Koma)
                </label>
                <textarea 
                  rows={2}
                  value={img.metadata.keywords}
                  onChange={(e) => updateMetadataField(img.id, 'keywords', e.target.value)}
                  placeholder="word1, word2, word3..."
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 focus:border-orange-500/70 rounded-xl text-sm text-slate-100 focus:outline-none transition resize-y"
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Confirm Delete Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-2xl max-w-sm w-full space-y-4 animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-base font-bold text-white">Hapus Semua Gambar?</h3>
            <p className="text-xs text-slate-400">
              Tindakan ini akan menghapus semua gambar dan metadata yang telah dihasilkan dari daftar.
            </p>
            <div className="flex justify-end gap-3 pt-2">
              <button 
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-xl transition"
              >
                Batal
              </button>
              <button 
                onClick={clearAllImages}
                className="px-4 py-2 text-xs font-medium text-white bg-red-600 hover:bg-red-500 rounded-xl transition shadow"
              >
                Ya, Hapus
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-800/95 backdrop-blur-md border border-slate-700 text-white px-4 py-2.5 rounded-xl shadow-2xl text-xs font-medium flex items-center gap-2 animate-in slide-in-from-bottom-5 duration-300">
          <Sparkles className="w-4 h-4 text-orange-400" />
          <span>{toastMessage}</span>
        </div>
      )}

    </div>
  );
};
export default VecteezyMetadataGenerator;
