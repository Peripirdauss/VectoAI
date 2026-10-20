import React, { useState, useEffect, useRef } from 'react';
import { 
  Wand2, Download, RefreshCw, Image as ImageIcon, Settings, 
  ChevronDown, ChevronUp, AlertCircle, Check, Trash2, Archive, 
  StopCircle, Sparkles, Crop, RotateCw, Sliders, ZoomIn, X
} from 'lucide-react';
import JSZip from 'jszip';

interface GeneratedIcon {
  id: string;
  url: string;
  prompt: string;
  createdAt: number;
}

export const IconGenerator: React.FC = () => {
  const [promptsText, setPromptsText] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedImages, setGeneratedImages] = useState<GeneratedIcon[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [lightboxImage, setLightboxImage] = useState<GeneratedIcon | null>(null);

  // Batch Progress
  const [currentProgress, setCurrentProgress] = useState<{ current: number; total: number; currentPrompt: string } | null>(null);
  const stopRequested = useRef(false);

  // Settings
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('vecto_ai_icon_key') || '');
  const [baseUrl, setBaseUrl] = useState(() => localStorage.getItem('vecto_ai_icon_base') || 'http://localhost:20128/v1');
  const [model, setModel] = useState(() => localStorage.getItem('vecto_ai_icon_model') || 'ag/gemini-3.1-flash-image');
  const [size, setSize] = useState(() => localStorage.getItem('vecto_ai_icon_size') || '1024x1024');
  const [aspectRatio, setAspectRatio] = useState<string>('1:1');
  const [customW, setCustomW] = useState<number>(1024);
  const [customH, setCustomH] = useState<number>(1024);
  const [imagesPerPrompt, setImagesPerPrompt] = useState<number>(1);
  const [stylePreset, setStylePreset] = useState<string>('flat_vector');
  const [lightingPreset, setLightingPreset] = useState<string>('natural');
  const [removeBg, setRemoveBg] = useState<boolean>(false);
  const [antiAi, setAntiAi] = useState<boolean>(false);
  const [fakeMetadata, setFakeMetadata] = useState<boolean>(false);
  const [concurrency, setConcurrency] = useState<number>(() => Number(localStorage.getItem('vecto_ai_icon_concurrency')) || 3);

  useEffect(() => {
    localStorage.setItem('vecto_ai_icon_key', apiKey);
    localStorage.setItem('vecto_ai_icon_base', baseUrl);
    localStorage.setItem('vecto_ai_icon_model', model);
    localStorage.setItem('vecto_ai_icon_size', size);
    localStorage.setItem('vecto_ai_icon_concurrency', concurrency.toString());
  }, [apiKey, baseUrl, model, size, concurrency]);

  // Sync customW & customH when size string changes
  useEffect(() => {
    const parts = (size || '1024x1024').toLowerCase().split('x');
    const w = parseInt(parts[0], 10);
    const h = parseInt(parts[1], 10);
    if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0) {
      setCustomW(w);
      setCustomH(h);
      const ratioVal = w / h;
      if (Math.abs(ratioVal - 1) < 0.05) setAspectRatio('1:1');
      else if (Math.abs(ratioVal - 16 / 9) < 0.05) setAspectRatio('16:9');
      else if (Math.abs(ratioVal - 9 / 16) < 0.05) setAspectRatio('9:16');
      else if (Math.abs(ratioVal - 4 / 3) < 0.05) setAspectRatio('4:3');
      else if (Math.abs(ratioVal - 3 / 4) < 0.05) setAspectRatio('3:4');
      else if (Math.abs(ratioVal - 3 / 2) < 0.05) setAspectRatio('3:2');
      else if (Math.abs(ratioVal - 2 / 3) < 0.05) setAspectRatio('2:3');
      else setAspectRatio('custom');
    }
  }, [size]);

  const updateSize = (w: number, h: number, ratioKey?: string) => {
    const validW = Math.max(64, Math.min(8192, Math.round(w)));
    const validH = Math.max(64, Math.min(8192, Math.round(h)));
    setCustomW(validW);
    setCustomH(validH);
    setSize(`${validW}x${validH}`);
    if (ratioKey) setAspectRatio(ratioKey);
  };

  const handleRatioSelect = (ratioId: string, baseW: number, baseH: number) => {
    setAspectRatio(ratioId);
    updateSize(baseW, baseH, ratioId);
  };

  const handleSwapDimensions = () => {
    updateSize(customH, customW);
  };

  const handleScalePreset = (base: number) => {
    const ratio = customW / customH;
    let newW = base;
    let newH = Math.round(base / ratio);
    if (ratio < 1) {
      newH = base;
      newW = Math.round(base * ratio);
    }
    newW = Math.round(newW / 16) * 16;
    newH = Math.round(newH / 16) * 16;
    updateSize(newW, newH);
  };

  const RATIO_PRESETS = [
    { id: '1:1', label: '1:1', sub: 'Square', w: 1024, h: 1024, wireframe: 'w-4 h-4' },
    { id: '9:16', label: '9:16', sub: 'Story/Reel', w: 1080, h: 1920, wireframe: 'w-2.5 h-4.5' },
    { id: '16:9', label: '16:9', sub: 'Cinema', w: 1920, h: 1080, wireframe: 'w-4.5 h-2.5' },
    { id: '3:4', label: '3:4', sub: 'Portrait', w: 768, h: 1024, wireframe: 'w-3 h-4' },
    { id: '4:3', label: '4:3', sub: 'Landscape', w: 1024, h: 768, wireframe: 'w-4 h-3' },
    { id: '2:3', label: '2:3', sub: 'Photo Port', w: 832, h: 1248, wireframe: 'w-2.5 h-4' },
    { id: '3:2', label: '3:2', sub: 'Photo Land', w: 1248, h: 832, wireframe: 'w-4 h-2.5' },
    { id: 'custom', label: 'Bebas', sub: 'Custom', w: customW, h: customH, wireframe: 'w-3.5 h-3.5 border-dashed' },
  ];

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleResetDefaults = () => {
    setBaseUrl('http://localhost:20128/v1');
    setModel('ag/gemini-3.1-flash-image');
  };

  const getCleanPromptList = () => {
    return promptsText
      .split('\n')
      .map(p => p.trim())
      .filter(p => p.length > 0);
  };

  const loadSamplePrompts = () => {
    const samples = [
      "Cute astronaut cat floating in space holding a coffee mug",
      "Isometric finance cloud server with cyber gold coins",
      "Minimalist organic leaf coffee cup logo, sleek clean lines",
      "Cyberpunk neon robotic dog, geometric origami icon"
    ].join('\n');
    setPromptsText(samples);
  };

  const buildStyledPrompt = (rawPrompt: string) => {
    let basePrompt = rawPrompt;
    
    switch (stylePreset) {
      case 'flat_vector':
        basePrompt = `Vector illustration icon, flat design, clean lines, isolated on solid white background, vibrant colors, microstock vector asset: ${rawPrompt}`;
        break;
      case '3d_cute':
        basePrompt = `Cute 3D clay render icon, soft volumetric studio lighting, isolated on solid white background, smooth pastel colors, high resolution: ${rawPrompt}`;
        break;
      case 'line_art':
        basePrompt = `Minimalist modern line art icon, elegant thin outline, monochrome black on solid white background, SVG vector ready: ${rawPrompt}`;
        break;
      case 'gradient_app':
        basePrompt = `Modern gradient app icon, rounded squircle aesthetic, glossy vibrant duotone gradients, professional UI element: ${rawPrompt}`;
        break;
      case 'none':
      default:
        basePrompt = rawPrompt;
        break;
    }

    if (antiAi) {
      basePrompt += `, handcrafted texture, subtle organic brush strokes, authentic human artist technique, imperfect lines`;
    }

    if (lightingPreset === 'natural') {
      basePrompt += `, soft natural ambient lighting, non-dramatic shadows`;
    } else if (lightingPreset === 'warm_studio') {
      basePrompt += `, warm golden hour lighting, cozy subtle reflections`;
    } else if (lightingPreset === 'cinematic') {
      basePrompt += `, dramatic cinematic soft chiaroscuro lighting`;
    } else if (lightingPreset === 'flat') {
      basePrompt += `, even flat lighting, minimal shadows, clean`;
    }
    
    if (removeBg) {
      basePrompt += `, isolated subject on pure white background, crisp defined borders, no background elements`;
    }

    return basePrompt;
  };

  const generateSingleImage = async (promptItem: string) => {
    const styledPrompt = buildStyledPrompt(promptItem);
    const response = await fetch('/api/generate-icon', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        endpoint: baseUrl.trim(),
        api_key: apiKey,
        mode: 'auto',
        payload: {
          model: model,
          prompt: styledPrompt,
          n: 1,
          size: size,
          response_format: 'b64_json'
        },
        remove_background: removeBg,
        anti_ai: antiAi,
        fake_metadata: fakeMetadata
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      let msg = errText;
      try {
        const parsed = JSON.parse(errText);
        if (parsed.detail) {
          try {
            const inner = JSON.parse(parsed.detail);
            msg = inner.error?.message || inner.message || parsed.detail;
          } catch {
            msg = parsed.detail;
          }
        } else if (parsed.error?.message) {
          msg = parsed.error.message;
        }
      } catch (e) {}
      throw new Error(msg);
    }

    const data = await response.json();
    const item = data.data?.[0];
    let imgUrl: string | null = item?.url || null;
    
    if (!imgUrl && item?.b64_json) {
      // Auto-detect image format from base64 magic bytes
      const b64 = item.b64_json;
      let mime = 'image/png';
      if (b64.startsWith('/9j/')) mime = 'image/jpeg';
      else if (b64.startsWith('iVBOR')) mime = 'image/png';
      else if (b64.startsWith('UklGR')) mime = 'image/webp';
      else if (b64.startsWith('R0lGO')) mime = 'image/gif';
      imgUrl = `data:${mime};base64,${b64}`;
    }
    
    if (!imgUrl) {
      throw new Error("Respons API tidak memuat URL gambar atau Base64.");
    }

    return imgUrl;
  };

  const handleStartBatchGeneration = async () => {
    const promptList = getCleanPromptList();
    if (promptList.length === 0) {
      showToast('Masukkan minimal satu prompt!');
      return;
    }
    if (!apiKey.trim()) {
      setShowSettings(true);
      showToast('Harap masukkan API Key terlebih dahulu!');
      return;
    }

    setIsGenerating(true);
    setGlobalError(null);
    stopRequested.current = false;

    const tasks: { prompt: string; index: number }[] = [];
    promptList.forEach((p) => {
      for (let i = 0; i < imagesPerPrompt; i++) {
        tasks.push({ prompt: p, index: tasks.length + 1 });
      }
    });

    const totalOps = tasks.length;
    let completedOps = 0;
    let successCount = 0;
    let lastErrMsg = '';
    const workerCount = Math.max(1, Math.min(concurrency, tasks.length));

    showToast(`Memulai batch ${totalOps} gambar (${workerCount} worker paralel)...`);

    let nextTaskIdx = 0;

    const runWorker = async (workerId: number) => {
      while (nextTaskIdx < tasks.length && !stopRequested.current) {
        const task = tasks[nextTaskIdx++];
        if (!task) break;

        setCurrentProgress({
          current: completedOps + 1,
          total: totalOps,
          currentPrompt: `[Worker ${workerId}] (${task.index}/${totalOps}) ${task.prompt}`
        });

        try {
          const imgUrl = await generateSingleImage(task.prompt);
          if (stopRequested.current) break;

          const newIcon: GeneratedIcon = {
            id: `icon_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
            url: imgUrl,
            prompt: task.prompt,
            createdAt: Date.now()
          };
          setGeneratedImages(prev => [newIcon, ...prev]);
          successCount++;
        } catch (err: any) {
          console.error(`[Worker ${workerId}] Error on prompt "${task.prompt}":`, err);
          lastErrMsg = err.message || 'Error tidak diketahui';
          setGlobalError(`Gagal generate gambar: ${lastErrMsg}`);
        } finally {
          completedOps++;
          setCurrentProgress({
            current: completedOps,
            total: totalOps,
            currentPrompt: `Progres: ${completedOps}/${totalOps} gambar`
          });
        }
      }
    };

    const workers = Array.from({ length: workerCount }, (_, idx) => runWorker(idx + 1));
    await Promise.all(workers);

    setIsGenerating(false);
    setCurrentProgress(null);
    if (successCount === 0 && lastErrMsg) {
      showToast(`Gagal: ${lastErrMsg}`);
    } else {
      showToast(`Batch selesai! ${successCount} berhasil dibuat.`);
    }
  };

  const handleStop = () => {
    stopRequested.current = true;
  };

  const downloadImage = (url: string, promptName: string) => {
    try {
      const safeName = promptName.slice(0, 40).replace(/[^a-zA-Z0-9_-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') || 'icon';

      // Helper: detect format from base64 magic bytes
      const detectFormat = (b64: string): { mime: string; ext: string } => {
        if (b64.startsWith('/9j/')) return { mime: 'image/jpeg', ext: 'jpg' };
        if (b64.startsWith('iVBOR')) return { mime: 'image/png', ext: 'png' };
        if (b64.startsWith('UklGR')) return { mime: 'image/webp', ext: 'webp' };
        if (b64.startsWith('R0lGO')) return { mime: 'image/gif', ext: 'gif' };
        return { mime: 'image/jpeg', ext: 'jpg' };
      };

      // Helper: base64 string to Blob
      const b64toBlob = (b64: string, mime: string): Blob => {
        const binaryStr = atob(b64);
        const len = binaryStr.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = binaryStr.charCodeAt(i);
        return new Blob([bytes], { type: mime });
      };

      // Helper: trigger download from Blob
      const triggerDownload = (blob: Blob, filename: string) => {
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        // Delay cleanup so browser has time to process download
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(blobUrl);
        }, 500);
      };

      if (url.startsWith('data:image/')) {
        const b64Data = url.split(',')[1] || '';
        const { mime, ext } = detectFormat(b64Data);
        const blob = b64toBlob(b64Data, mime);
        triggerDownload(blob, `icon_${safeName}.${ext}`);
      } else {
        // Remote URL
        fetch(url)
          .then(r => r.blob())
          .then(blob => {
            const ext = blob.type.includes('jpeg') ? 'jpg' : (blob.type.split('/')[1] || 'jpg');
            triggerDownload(blob, `icon_${safeName}.${ext}`);
          });
      }
      showToast('Gambar berhasil diunduh!');
    } catch (e) {
      console.error('Download error:', e);
      showToast('Gagal mengunduh gambar.');
    }
  };

  const downloadAllAsZip = async () => {
    if (generatedImages.length === 0) return;
    showToast('Mempersiapkan ZIP arsip...');
    try {
      const zip = new JSZip();
      const folder = zip.folder("generated_icons");

      for (let i = 0; i < generatedImages.length; i++) {
        const item = generatedImages[i];
        const safeName = item.prompt.slice(0, 30).replace(/[^a-zA-Z0-9_-]/g, '_') || 'icon';
        
        if (item.url.startsWith('data:image/')) {
          const [header, base64Data] = item.url.split(',');
          const mimeMatch = header.match(/data:([^;]+)/);
          const mime = mimeMatch ? mimeMatch[1] : 'image/png';
          let ext = 'png';
          if (mime.includes('jpeg') || mime.includes('jpg')) ext = 'jpg';
          else if (mime.includes('webp')) ext = 'webp';
          else if (mime.includes('gif')) ext = 'gif';
          folder?.file(`${i + 1}_${safeName}.${ext}`, base64Data, { base64: true });
        } else {
          const resp = await fetch(item.url);
          const blob = await resp.blob();
          let ext = 'png';
          if (blob.type.includes('jpeg') || blob.type.includes('jpg')) ext = 'jpg';
          else if (blob.type.includes('webp')) ext = 'webp';
          folder?.file(`${i + 1}_${safeName}.${ext}`, blob);
        }
      }

      const content = await zip.generateAsync({ type: "blob" });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(content);
      a.download = `vecto_batch_icons_${Date.now()}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast('ZIP berhasil diunduh!');
    } catch (err: any) {
      console.error("ZIP Error:", err);
      showToast('Gagal membuat ZIP arsip.');
    }
  };

  const promptCount = getCleanPromptList().length;

  return (
    <div className="w-full flex flex-col gap-6 text-slate-200">
      {globalError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 flex items-start gap-2.5 text-xs text-red-200 animate-in fade-in slide-in-from-top-4">
          <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <strong className="block text-red-300 font-semibold mb-0.5">Generasi Gagal:</strong>
            <span className="font-mono">{globalError}</span>
            <div className="mt-1 text-red-400/80">Silakan periksa API Key, URL Endpoint, Model, atau Resolusi yang dipilih.</div>
          </div>
          <button onClick={() => setGlobalError(null)} className="text-red-400 hover:text-white p-1">✕</button>
        </div>
      )}
      
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-blue-950/40 via-indigo-950/20 to-slate-900 border border-blue-500/30 rounded-2xl p-6 shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="p-2 rounded-xl bg-blue-500/20 text-blue-400 border border-blue-500/30 font-bold text-lg">⚡</span>
            <h2 className="text-xl md:text-2xl font-bold text-white tracking-wide flex items-center gap-2">
              Batch AI Icon Generator
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">
                Multi-Prompt
              </span>
            </h2>
          </div>
          <p className="text-sm text-slate-400">
            Generate banyak ikon sekaligus dari daftar prompt teks menggunakan router AI lokal / 9router.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={() => setShowSettings(!showSettings)}
            className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-300 transition flex items-center gap-2 shadow-sm"
          >
            <Settings className="w-4 h-4 text-blue-400" />
            <span>Pengaturan API</span>
            {showSettings ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-lg space-y-4 animate-in fade-in duration-200">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">Provider</label>
              <div className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-xs text-emerald-400 font-semibold flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                9router (Local — Gemini Flash)
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">Base URL / Endpoint</label>
              <input 
                type="text" 
                value={baseUrl} 
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:20128/v1"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-mono text-[11px]"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">Model</label>
              <input 
                type="text" 
                value={model} 
                onChange={(e) => setModel(e.target.value)}
                placeholder="ag/gemini-3.1-flash-image"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-mono text-[11px]"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1.5">API Key</label>
              <input 
                type="password" 
                value={apiKey} 
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Bearer Token..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={handleResetDefaults}
              className="text-[11px] text-slate-500 hover:text-blue-400 px-2 py-1 rounded-md transition"
            >
              Reset ke default 9router
            </button>
          </div>
        </div>
      )}

      {/* Main Generator Area */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-sm space-y-4">
        
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <label className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <Wand2 className="w-4 h-4 text-blue-400" /> Daftar Prompt Batch (1 Baris = 1 Prompt)
            </label>
            <span className="px-2 py-0.5 rounded-md bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold">
              {promptCount} Prompt
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={loadSamplePrompts}
              type="button"
              className="text-xs text-slate-400 hover:text-blue-400 flex items-center gap-1.5 bg-slate-800/80 px-3 py-1.5 rounded-lg border border-slate-700/60 transition"
            >
              <Sparkles size={13} className="text-amber-400" /> Muat Contoh Prompt
            </button>
            {promptsText && (
              <button
                onClick={() => setPromptsText('')}
                type="button"
                className="text-xs text-slate-500 hover:text-red-400 px-2 py-1.5 rounded-lg transition"
              >
                Hapus
              </button>
            )}
          </div>
        </div>

        {/* Textarea */}
        <textarea 
          value={promptsText} 
          onChange={(e) => setPromptsText(e.target.value)}
          placeholder={`Tulis atau paste daftar prompt di sini, satu prompt per baris:\nCute baby panda reading a book\nCoffee machine cyber minimalist\nVector cloud storage logo`}
          rows={6}
          disabled={isGenerating}
          className="w-full bg-slate-950/70 border border-slate-700 rounded-xl p-4 text-sm text-white focus:outline-none focus:border-blue-500 resize-y shadow-inner font-mono leading-relaxed"
        />

        {/* Canvas & Dimensions Studio (Loveart.ai style) */}
        <div className="bg-slate-950/60 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-inner space-y-4 my-2">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                <Crop className="w-4 h-4" />
              </span>
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  Canvas & Resolusi
                  <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    {customW} × {customH} px
                  </span>
                </h3>
                <p className="text-[11px] text-slate-400">
                  Pilih rasio canvas visual atau atur lebar & tinggi secara kustom
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSwapDimensions}
                className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-300 hover:text-white transition flex items-center gap-1.5 shadow-sm"
                title="Tukar Lebar dan Tinggi (Rotate Canvas)"
              >
                <RotateCw className="w-3.5 h-3.5 text-blue-400" />
                <span>Balik (W ↔ H)</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-center">
            {/* Visual Canvas Box */}
            <div className="lg:col-span-4 flex flex-col items-center justify-center">
              <div 
                className="w-full h-44 rounded-xl bg-slate-900/90 border border-slate-800 relative flex items-center justify-center p-3 overflow-hidden shadow-inner"
                style={{
                  backgroundImage: `radial-gradient(circle, rgba(255, 255, 255, 0.07) 1px, transparent 1px)`,
                  backgroundSize: '12px 12px'
                }}
              >
                <div
                  className="relative rounded-lg border-2 border-blue-500/80 bg-gradient-to-br from-blue-500/15 via-indigo-500/10 to-slate-900/80 backdrop-blur-sm shadow-lg shadow-blue-500/10 flex flex-col items-center justify-center transition-all duration-300 ease-out overflow-hidden"
                  style={{
                    width: `${Math.min(100, Math.max(22, (customW / Math.max(customW, customH)) * 88))}%`,
                    height: `${Math.min(100, Math.max(22, (customH / Math.max(customW, customH)) * 88))}%`,
                    maxHeight: '136px',
                    maxWidth: '190px'
                  }}
                >
                  <div className="absolute inset-0 grid grid-cols-3 grid-rows-3 pointer-events-none opacity-20">
                    <div className="border-r border-b border-blue-400" />
                    <div className="border-r border-b border-blue-400" />
                    <div className="border-b border-blue-400" />
                    <div className="border-r border-b border-blue-400" />
                    <div className="border-r border-b border-blue-400" />
                    <div className="border-b border-blue-400" />
                    <div className="border-r border-blue-400" />
                    <div className="border-r border-blue-400" />
                    <div />
                  </div>
                  <div className="relative z-10 text-center px-1">
                    <span className="block text-[11px] font-bold text-white font-mono tracking-tight drop-shadow">
                      {customW} × {customH}
                    </span>
                    <span className="text-[9px] font-semibold text-blue-300 uppercase tracking-wider block">
                      {aspectRatio !== 'custom' ? aspectRatio : 'Custom'}
                    </span>
                  </div>
                  <div className="absolute top-0.5 left-0.5 w-1.5 h-1.5 border-t-2 border-l-2 border-blue-400" />
                  <div className="absolute top-0.5 right-0.5 w-1.5 h-1.5 border-t-2 border-r-2 border-blue-400" />
                  <div className="absolute bottom-0.5 left-0.5 w-1.5 h-1.5 border-b-2 border-l-2 border-blue-400" />
                  <div className="absolute bottom-0.5 right-0.5 w-1.5 h-1.5 border-b-2 border-r-2 border-blue-400" />
                </div>
              </div>
              <div className="flex items-center justify-between w-full mt-2 px-1 text-[11px] text-slate-400">
                <span>Rasio: <strong className="text-slate-200">{aspectRatio}</strong></span>
                <span>Orientasi: <strong className="text-slate-200">{customW === customH ? 'Square' : customW > customH ? 'Landscape' : 'Portrait'}</strong></span>
              </div>
            </div>

            {/* Presets and Sliders */}
            <div className="lg:col-span-8 space-y-3.5">
              <div>
                <label className="block text-[11px] font-semibold text-slate-400 mb-1.5">Preset Rasio Canvas</label>
                <div className="grid grid-cols-4 sm:grid-cols-8 gap-1.5">
                  {RATIO_PRESETS.map((preset) => {
                    const isSelected = aspectRatio === preset.id;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => {
                          if (preset.id === 'custom') setAspectRatio('custom');
                          else handleRatioSelect(preset.id, preset.w, preset.h);
                        }}
                        className={`flex flex-col items-center justify-center p-2 rounded-xl border text-center transition-all ${
                          isSelected
                            ? 'bg-blue-600/20 border-blue-500 text-white shadow-sm shadow-blue-500/20 ring-1 ring-blue-500/40'
                            : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-850 hover:border-slate-700'
                        }`}
                      >
                        <div className="h-6 flex items-center justify-center mb-1">
                          <div className={`rounded-sm border ${isSelected ? 'border-blue-400 bg-blue-500/30' : 'border-slate-600 bg-slate-800'} ${preset.wireframe}`} />
                        </div>
                        <span className="text-[11px] font-bold leading-none">{preset.label}</span>
                        <span className="text-[9px] text-slate-500 leading-tight mt-0.5 truncate w-full">{preset.sub}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-3 space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] font-medium text-slate-400">Lebar (Width)</span>
                      <span className="text-[11px] font-mono font-bold text-blue-400">{customW} px</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input type="range" min={256} max={4096} step={16} value={customW} onChange={(e) => updateSize(Number(e.target.value), customH, 'custom')} className="w-full accent-blue-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg" />
                      <input type="number" min={128} max={8192} value={customW} onChange={(e) => updateSize(Math.max(64, Number(e.target.value)), customH, 'custom')} className="w-20 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1 text-xs text-white font-mono text-center focus:outline-none focus:border-blue-500" />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] font-medium text-slate-400">Tinggi (Height)</span>
                      <span className="text-[11px] font-mono font-bold text-blue-400">{customH} px</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input type="range" min={256} max={4096} step={16} value={customH} onChange={(e) => updateSize(customW, Number(e.target.value), 'custom')} className="w-full accent-blue-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg" />
                      <input type="number" min={128} max={8192} value={customH} onChange={(e) => updateSize(customW, Math.max(64, Number(e.target.value)), 'custom')} className="w-20 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1 text-xs text-white font-mono text-center focus:outline-none focus:border-blue-500" />
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1 border-t border-slate-800/60 text-[11px]">
                  <span className="text-slate-400 flex items-center gap-1">
                    <Sliders className="w-3 h-3 text-slate-500" /> Skala Resolusi Cepat:
                  </span>
                  <div className="flex gap-1.5">
                    {[ { label: '512 px', size: 512 }, { label: '1024 px', size: 1024 }, { label: '2K (2048)', size: 2048 }, { label: '4K (4096)', size: 4096 } ].map(s => (
                      <button key={s.size} type="button" onClick={() => handleScalePreset(s.size)} className="px-2 py-0.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/80 font-mono text-[10px] transition">
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Options Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3 pt-2">
          <div>
            <label className="block text-xs font-semibold text-slate-400 mb-1.5">Preset Gaya Desain</label>
            <select
              value={stylePreset}
              onChange={(e) => setStylePreset(e.target.value)}
              disabled={isGenerating}
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2.5 text-xs text-white focus:outline-none focus:border-blue-500"
            >
              <option value="flat_vector">🎨 Flat Vector Icon (Microstock Style)</option>
              <option value="3d_cute">🧸 3D Cute Isometric / Clay</option>
              <option value="line_art">✒️ Minimalist Clean Line Art</option>
              <option value="gradient_app">📱 Modern Duotone Gradient App Icon</option>
              <option value="none">🚫 Polos (Gunakan Prompt Saja)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-400 mb-1.5">Variasi & Pencahayaan</label>
            <div className="flex gap-2">
              <select
                value={imagesPerPrompt}
                onChange={(e) => setImagesPerPrompt(Number(e.target.value))}
                disabled={isGenerating}
                className="w-1/3 bg-slate-800 border border-slate-700 rounded-xl px-2 py-2.5 text-xs text-white focus:outline-none focus:border-blue-500"
              >
                <option value={1}>1x</option>
                <option value={2}>2x</option>
                <option value={3}>3x</option>
                <option value={4}>4x</option>
              </select>
              <select
                value={lightingPreset}
                onChange={(e) => setLightingPreset(e.target.value)}
                disabled={isGenerating}
                className="w-2/3 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2.5 text-xs text-white focus:outline-none focus:border-blue-500"
              >
                <option value="natural">☀️ Natural Ambient</option>
                <option value="warm_studio">💡 Warm Studio</option>
                <option value="cinematic">🎬 Cinematic Dark</option>
                <option value="flat">☁️ Flat Minimal</option>
              </select>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs font-semibold text-slate-400">Worker Paralel</label>
              <span className="text-[10px] font-bold text-amber-400 font-mono">{concurrency} Worker</span>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {[1, 2, 3, 5].map((w) => (
                <button
                  key={w}
                  type="button"
                  disabled={isGenerating}
                  onClick={() => setConcurrency(w)}
                  className={`py-2 rounded-xl text-xs font-bold transition border ${
                    concurrency === w
                      ? 'bg-amber-500/20 border-amber-500 text-amber-300 shadow-sm shadow-amber-500/10'
                      : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-white hover:bg-slate-700'
                  }`}
                  title={`${w} Worker bersamaan (${w === 3 ? 'Default Rekomendasi - Cepat & Aman' : w === 1 ? 'Sekuensial 1-per-1' : 'Multi-Worker Cepat'})`}
                >
                  {w}{w === 3 ? '⚡' : ''}
                </button>
              ))}
            </div>
          </div>

          <div className="lg:col-span-2">
            <label className="block text-xs font-semibold text-slate-400 mb-1.5">Fitur Ekstra (Anti-AI & Post Processing)</label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <label className="flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 cursor-pointer hover:bg-slate-700/80 transition">
                <input
                  type="checkbox"
                  checked={removeBg}
                  onChange={(e) => setRemoveBg(e.target.checked)}
                  disabled={isGenerating}
                  className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-[11px] text-slate-200 leading-tight">Hapus<br/>Background</span>
              </label>
              <label className="flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 cursor-pointer hover:bg-slate-700/80 transition" title="Menambahkan noise dan memudarkan AI edge untuk mengelabui detektor heatmap">
                <input
                  type="checkbox"
                  checked={antiAi}
                  onChange={(e) => setAntiAi(e.target.checked)}
                  disabled={isGenerating}
                  className="rounded border-slate-600 bg-slate-700 text-purple-500 focus:ring-purple-500"
                />
                <span className="text-[11px] text-purple-200 leading-tight">Humanize<br/>(Anti-AI Detector)</span>
              </label>
              <label className="flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 cursor-pointer hover:bg-slate-700/80 transition" title="Menambahkan metadata Adobe Photoshop agar EXIF tidak terbaca AI">
                <input
                  type="checkbox"
                  checked={fakeMetadata}
                  onChange={(e) => setFakeMetadata(e.target.checked)}
                  disabled={isGenerating}
                  className="rounded border-slate-600 bg-slate-700 text-green-500 focus:ring-green-500"
                />
                <span className="text-[11px] text-green-200 leading-tight">Adobe EXIF<br/>Spoofing</span>
              </label>
            </div>
          </div>
        </div>

        <div className="pt-2">
          {!isGenerating ? (
            <button 
              onClick={handleStartBatchGeneration}
              disabled={promptCount === 0}
              className="w-full h-[48px] bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-bold rounded-xl transition shadow-lg shadow-indigo-600/25 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
            >
              <Wand2 className="w-5 h-5" />
              <span>Mulai Batch Generate ({promptCount * imagesPerPrompt} Gambar • {concurrency} Worker)</span>
            </button>
          ) : (
            <button 
              onClick={handleStop}
              className="w-full h-[48px] bg-red-600 hover:bg-red-500 text-white font-bold rounded-xl transition shadow-lg shadow-red-600/25 flex items-center justify-center gap-2 text-sm"
            >
              <StopCircle className="w-5 h-5" />
              <span>Hentikan Batch Generate</span>
            </button>
          )}
        </div>

        {/* Progress Bar Display */}
        {isGenerating && currentProgress && (
          <div className="bg-slate-950/80 border border-blue-500/30 rounded-xl p-4 space-y-2 animate-in fade-in">
            <div className="flex items-center justify-between text-xs">
              <span className="text-blue-400 font-bold flex items-center gap-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Sedang memproses {currentProgress.current} dari {currentProgress.total} gambar...
                <span className="text-[10px] font-mono font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {concurrency} Worker Aktif
                </span>
              </span>
              <span className="text-slate-400 font-mono">
                {Math.round((currentProgress.current / currentProgress.total) * 100)}%
              </span>
            </div>

            <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div 
                className="bg-gradient-to-r from-blue-500 to-indigo-500 h-full rounded-full transition-all duration-300"
                style={{ width: `${(currentProgress.current / currentProgress.total) * 100}%` }}
              />
            </div>

            <p className="text-[11px] text-slate-400 truncate">
              <span className="text-slate-500">Prompt aktif:</span> {currentProgress.currentPrompt}
            </p>
          </div>
        )}

      </div>

      {/* Results Gallery */}
      {generatedImages.length > 0 && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-800">
            <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
              <ImageIcon className="w-4 h-4 text-blue-400" /> 
              Galeri Hasil Generasi ({generatedImages.length} Ikon)
            </h3>

            <div className="flex items-center gap-2">
              <button 
                onClick={downloadAllAsZip}
                className="px-3.5 py-1.5 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-400 border border-indigo-500/30 text-xs font-semibold flex items-center gap-2 transition shadow-sm"
              >
                <Archive size={14} /> Unduh Semua (ZIP)
              </button>
              
              <button 
                onClick={() => setGeneratedImages([])}
                className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-slate-700 hover:border-red-500/30 text-xs font-semibold flex items-center gap-1.5 transition"
              >
                <Trash2 size={13} /> Kosongkan
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
            {generatedImages.map((img, i) => (
              <div key={img.id} className="bg-slate-900 rounded-2xl overflow-hidden border border-slate-800 hover:border-blue-500/50 transition-all group shadow-md flex flex-col">
                <div 
                  className="aspect-square bg-slate-950 relative overflow-hidden flex items-center justify-center p-2 cursor-pointer"
                  onClick={() => setLightboxImage(img)}
                >
                  <img 
                    src={img.url} 
                    alt={img.prompt} 
                    className="w-full h-full object-contain rounded-xl"
                  />
                  <div className="absolute inset-0 bg-slate-950/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3 p-4">
                    <button 
                      onClick={(e) => { e.stopPropagation(); setLightboxImage(img); }}
                      className="p-3 bg-white/10 hover:bg-white/20 backdrop-blur-sm text-white rounded-xl border border-white/20 transition shadow-lg"
                      title="Zoom / Preview"
                    >
                      <ZoomIn className="w-5 h-5" />
                    </button>
                    <button 
                      onClick={(e) => { e.stopPropagation(); downloadImage(img.url, img.prompt); }}
                      className="p-3 bg-blue-600/80 hover:bg-blue-500 backdrop-blur-sm text-white rounded-xl border border-blue-400/30 transition shadow-lg"
                      title="Download PNG"
                    >
                      <Download className="w-5 h-5" />
                    </button>
                  </div>
                </div>
                <div className="p-3 bg-slate-900/90 border-t border-slate-800/80 flex-grow flex flex-col justify-between">
                  <p className="text-xs text-slate-300 font-medium line-clamp-2" title={img.prompt}>
                    {img.prompt}
                  </p>
                  <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-800/50 text-[10px] text-slate-500">
                    <span>#{generatedImages.length - i}</span>
                    <span>{new Date(img.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lightbox / Zoom Modal */}
      {lightboxImage && (
        <div 
          className="fixed inset-0 z-[100] bg-black/90 backdrop-blur-md flex items-center justify-center p-4 sm:p-8 animate-in fade-in duration-200"
          onClick={() => setLightboxImage(null)}
        >
          {/* Top bar */}
          <div className="absolute top-0 left-0 right-0 flex items-center justify-between px-5 py-4 bg-gradient-to-b from-black/60 to-transparent z-10">
            <p className="text-sm text-white/80 font-medium truncate max-w-[60%]">
              {lightboxImage.prompt}
            </p>
            <div className="flex items-center gap-2">
              <button 
                onClick={(e) => { e.stopPropagation(); downloadImage(lightboxImage.url, lightboxImage.prompt); }}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold flex items-center gap-2 transition shadow-lg"
              >
                <Download className="w-4 h-4" /> Unduh PNG
              </button>
              <button 
                onClick={() => setLightboxImage(null)}
                className="p-2 bg-white/10 hover:bg-white/20 text-white rounded-xl transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Image */}
          <img 
            src={lightboxImage.url} 
            alt={lightboxImage.prompt} 
            className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />

          {/* Navigation hint */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-white/40 flex items-center gap-2">
            <span>Klik di luar gambar atau tekan × untuk menutup</span>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-800/95 backdrop-blur-md border border-slate-700 text-white px-4 py-2.5 rounded-xl shadow-2xl text-xs font-medium flex items-center gap-2 animate-in slide-in-from-bottom-5 duration-300">
          {toastMessage?.includes('Gagal') ? <AlertCircle className="w-4 h-4 text-red-400" /> : <Check className="w-4 h-4 text-emerald-400" />}
          <span>{toastMessage}</span>
        </div>
      )}

    </div>
  );
};

export default IconGenerator;
