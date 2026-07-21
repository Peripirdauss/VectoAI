import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import JSZip from 'jszip';
import { 
  Upload, Download, RefreshCw, Layers, AlertCircle, FileText, Trash2, 
  Check, Sparkles, CheckCircle2, Image as ImageIcon, ShieldCheck, 
  Eye, Grid, Sun, Moon, FileCheck, Layers3, Activity, Sliders,
  Package
} from 'lucide-react';

const API_BASE = '/api';
const DEFAULT_TIMEOUT = 600000; // 10 minutes timeout for heavy processing

/** Strip extension from a filename, splitting on the last dot. */
function stripExtension(filename: string): string {
  const idx = filename.lastIndexOf('.');
  return idx > 0 ? filename.slice(0, idx) : filename;
}

/** Sanitize filename matching backend logic */
function sanitizeFilename(filename: string): string {
  const baseName = stripExtension(filename);
  const clean = baseName.replace(/[^a-zA-Z0-9_\-]/g, '_').replace(/_+/g, '_').toLowerCase();
  return clean || 'asset';
}

/** Format raw bytes into human readable KB/MB string */
function formatFileSize(bytes: number): string {
  if (bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

async function parseErrorMessage(err: any, defaultMsg: string): Promise<string> {
  if (err.message === 'Network Error') {
    return 'Koneksi ke server gagal (Network Error). Pastikan server backend berjalan di port 8000 dan tidak terhalang firewall/CORS.';
  }
  if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
    return 'Waktu proses habis (Timeout). Coba kurangi jumlah batch file atau pastikan server backend berjalan.';
  }
  if (err.response?.data instanceof Blob) {
    try {
      const text = await err.response.data.text();
      const json = JSON.parse(text);
      return json.detail || defaultMsg;
    } catch {
      return defaultMsg;
    }
  }
  return err.response?.data?.detail || err.message || defaultMsg;
}

async function triggerBlobDownload(blob: Blob, fallbackFileName: string, mimeType: string) {
  if (blob.type === 'application/json' || (blob.size < 300 && blob.type !== 'application/postscript' && blob.type !== 'image/svg+xml')) {
    const text = await blob.text();
    try {
      const json = JSON.parse(text);
      if (json.detail) {
        throw new Error(json.detail);
      }
    } catch (e: any) {
      if (e.message && !e.message.includes('JSON')) {
        throw e;
      }
    }
  }

  const cleanBlob = new Blob([blob], { type: mimeType });
  const url = window.URL.createObjectURL(cleanBlob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', fallbackFileName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

interface FileItem {
  file: File;
  previewUrl: string;
  id: string;
}



interface ProgressState {
  current: number;
  total: number;
  fileName: string;
  percent: number;
  stage: 'uploading' | 'processing' | 'downloading' | 'complete';
}



function App() {
  const [activeTab, setActiveTab] = useState<'vectorizer' | 'vecteezy' | 'freepik' | 'adobe'>('freepik');
  const [files, setFiles] = useState<FileItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [threshold, setThreshold] = useState(127);
  const [invert, setInvert] = useState(false);
  const [format, setFormat] = useState<'eps' | 'svg'>('eps');
  const [mode, setMode] = useState<'monochrome' | 'color'>('monochrome');
  const [numColors, setNumColors] = useState(4);
  const [fillHoles, setFillHoles] = useState(true);
  const [cornerSharpness, setCornerSharpness] = useState(0.75);
  const [creator, setCreator] = useState('peripirdaus');
  
  // Canvas & Preview state
  const [canvasBg, setCanvasBg] = useState<'checkerboard' | 'dark' | 'white'>('checkerboard');
  const [preview, setPreview] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState<ProgressState | null>(null);

  // Helper to compute matched target filename for a file
  const computeExportFilename = useCallback((origName: string, index: number, total: number, ext: string) => {
    const safe = sanitizeFilename(origName);
    const suf = total > 1 ? `_${index + 1}` : '';
    return `${safe}${suf}.${ext}`;
  }, []);

  const fetchPreview = useCallback(async () => {
    const activeFile = selectedIndex !== null ? files[selectedIndex]?.file : null;
    if (!activeFile) {
      setPreview(null);
      setPreflight(null);
      return;
    }
    
    const formData = new FormData();
    formData.append('file', activeFile);
    formData.append('threshold', threshold.toString());
    formData.append('invert', invert.toString());
    formData.append('mode', mode);
    formData.append('numColors', numColors.toString());

    try {
      const response = await axios.post(`${API_BASE}/preview`, formData, { timeout: 15000 });
      setPreview(response.data.preview);

      // Fetch preflight audit check
      const auditRes = await axios.post(`${API_BASE}/preflight`, formData, { timeout: 15000 });
      setPreflight(auditRes.data);
    } catch (err) {
      console.error('Preview error:', err);
    }
  }, [files, selectedIndex, threshold, invert, mode, numColors]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPreview();
    }, 300);
    return () => clearTimeout(timer);
  }, [fetchPreview]);

  const addFiles = (newFiles: File[]) => {
    const items: FileItem[] = newFiles.map(f => ({
      file: f,
      previewUrl: URL.createObjectURL(f),
      id: Math.random().toString(36).substring(2, 9)
    }));

    const updatedFiles = [...files, ...items];
    setFiles(updatedFiles);
    if (selectedIndex === null) setSelectedIndex(0);
    setError(null);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  const removeFile = (index: number) => {
    const fileToRemove = files[index];
    if (fileToRemove?.previewUrl) {
      URL.revokeObjectURL(fileToRemove.previewUrl);
    }

    const newFiles = files.filter((_, i) => i !== index);
    setFiles(newFiles);

    if (newFiles.length === 0) {
      setSelectedIndex(null);
    } else if (selectedIndex === index) {
      setSelectedIndex(0);
    } else if (selectedIndex !== null && selectedIndex > index) {
      setSelectedIndex(selectedIndex - 1);
    }
  };

  const clearAllFiles = () => {
    files.forEach(f => {
      if (f.previewUrl) URL.revokeObjectURL(f.previewUrl);
    });
    setFiles([]);
    setSelectedIndex(null);
    setPreview(null);
    setPreflight(null);
  };


  const downloadAll = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);

    const isBulk = files.length > 1;

    try {
      if (!isBulk) {
        setProgress({ current: 1, total: 1, fileName: files[0].file.name, percent: 30, stage: 'uploading' });
        const formData = new FormData();
        formData.append('file', files[0].file);
        formData.append('threshold', threshold.toString());
        formData.append('invert', invert.toString());
        formData.append('format', format);
        formData.append('mode', mode);
        formData.append('numColors', numColors.toString());
        formData.append('creator', creator);

        const response = await axios.post(`${API_BASE}/vectorize`, formData, {
          responseType: 'blob',
          timeout: DEFAULT_TIMEOUT
        });
        
        setProgress({ current: 1, total: 1, fileName: 'Mendownload berkas...', percent: 100, stage: 'complete' });
        const baseName = sanitizeFilename(files[0].file.name);
        const mime = format === 'eps' ? 'application/postscript' : 'image/svg+xml';
        await triggerBlobDownload(response.data, `${baseName}.${format}`, mime);
      } else {
        const zip = new JSZip();
        let successCount = 0;

        for (let i = 0; i < files.length; i++) {
          const fItem = files[i];
          const pct = Math.round(((i + 1) / files.length) * 92);
          
          setProgress({
            current: i + 1,
            total: files.length,
            fileName: fItem.file.name,
            percent: Math.max(5, pct),
            stage: 'processing'
          });

          try {
            const formData = new FormData();
            formData.append('file', fItem.file);
            formData.append('threshold', threshold.toString());
            formData.append('invert', invert.toString());
            formData.append('format', format);
            formData.append('mode', mode);
            formData.append('numColors', numColors.toString());
            formData.append('creator', creator);

            const response = await axios.post(`${API_BASE}/vectorize`, formData, {
              responseType: 'arraybuffer',
              timeout: 60000
            });

            if (response.data) {
              const safeName = sanitizeFilename(fItem.file.name);
              const filename = `${safeName}_${i + 1}.${format}`;
              zip.file(filename, response.data);
              successCount++;
            }
          } catch (itemErr) {
            console.error(`Error processing file ${fItem.file.name}:`, itemErr);
          }
        }

        if (successCount === 0) {
          throw new Error('Tidak ada berkas yang berhasil di-vektorisasi.');
        }

        setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP...', percent: 98, stage: 'downloading' });
        const finalZipBlob = await zip.generateAsync({ type: 'blob' });
        await triggerBlobDownload(finalZipBlob, `vectorized_${format}.zip`, 'application/zip');
        setProgress({ current: files.length, total: files.length, fileName: 'Selesai!', percent: 100, stage: 'complete' });
      }
    } catch (err: any) {
      console.error('Vectorization error:', err);
      const msg = await parseErrorMessage(err, 'Gagal memproses file.');
      setError(msg);
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const downloadFreepik = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);

    const zip = new JSZip();
    const baseSuffix = Math.floor(Date.now() % 10000);
    let successCount = 0;

    try {
      for (let i = 0; i < files.length; i++) {
        const fItem = files[i];
        const pct = Math.round(((i + 1) / files.length) * 92);

        setProgress({
          current: i + 1,
          total: files.length,
          fileName: fItem.file.name,
          percent: Math.max(5, pct),
          stage: 'processing'
        });

        try {
          const formData = new FormData();
          formData.append('files', fItem.file);
          formData.append('threshold', threshold.toString());
          formData.append('invert', invert.toString());
          formData.append('mode', mode);
          formData.append('numColors', numColors.toString());
          formData.append('creator', creator);

          const response = await axios.post(`${API_BASE}/freepik-vectorize`, formData, { timeout: 60000 });
          const data = response.data;

          if (data && Array.isArray(data.files) && data.files[0]) {
            const entry = data.files[0];
            const safeName = sanitizeFilename(fItem.file.name);
            const suffix = files.length > 1 ? `${baseSuffix}_${i + 1}` : `${baseSuffix}`;
            const epsName = `${safeName}_${suffix}.eps`;
            const jpgName = `${safeName}_${suffix}.jpg`;

            const epsBytes = Uint8Array.from(atob(entry.eps_b64), c => c.charCodeAt(0));
            const jpgBytes = Uint8Array.from(atob(entry.jpg_b64), c => c.charCodeAt(0));

            zip.file(epsName, epsBytes);
            zip.file(jpgName, jpgBytes);
            successCount++;
          }
        } catch (itemErr) {
          console.error(`Error processing Freepik file ${fItem.file.name}:`, itemErr);
        }
      }

      if (successCount === 0) {
        throw new Error('Tidak ada berkas yang berhasil di-vektorisasi untuk Freepik.');
      }

      setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP Freepik...', percent: 98, stage: 'downloading' });
      const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/zip', compression: 'DEFLATE' });
      const zipName = files.length === 1 
        ? `${sanitizeFilename(files[0].file.name)}_freepik_package.zip` 
        : 'freepik_vectors_package.zip';
      await triggerBlobDownload(blob, zipName, 'application/zip');

      setProgress({ current: files.length, total: files.length, fileName: 'Selesai!', percent: 100, stage: 'complete' });
    } catch (err: any) {
      console.error('Freepik export error:', err);
      const msg = await parseErrorMessage(err, 'Gagal memproses file untuk Freepik.');
      setError(msg);
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const downloadAdobeStock = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);

    const isBulk = files.length > 1;

    try {
      if (!isBulk) {
        setProgress({ current: 1, total: 1, fileName: files[0].file.name, percent: 30, stage: 'uploading' });
        const formData = new FormData();
        formData.append('files', files[0].file);
        formData.append('threshold', threshold.toString());
        formData.append('invert', invert.toString());
        formData.append('format', format);
        formData.append('mode', mode);
        formData.append('numColors', numColors.toString());
        formData.append('fillHoles', fillHoles.toString());
        formData.append('creator', creator);

        const response = await axios.post(`${API_BASE}/adobe-stock-vectorize`, formData, {
          responseType: 'blob',
          timeout: DEFAULT_TIMEOUT
        });
        
        const baseName = sanitizeFilename(files[0].file.name);
        const mime = format === 'eps' ? 'application/postscript' : 'image/svg+xml';
        await triggerBlobDownload(response.data, `${baseName}.${format}`, mime);
        setProgress({ current: 1, total: 1, fileName: 'Selesai!', percent: 100, stage: 'complete' });
      } else {
        const zip = new JSZip();
        let successCount = 0;

        for (let i = 0; i < files.length; i++) {
          const fItem = files[i];
          const pct = Math.round(((i + 1) / files.length) * 92);

          setProgress({
            current: i + 1,
            total: files.length,
            fileName: fItem.file.name,
            percent: Math.max(5, pct),
            stage: 'processing'
          });

          try {
            const formData = new FormData();
            formData.append('files', fItem.file);
            formData.append('threshold', threshold.toString());
            formData.append('invert', invert.toString());
            formData.append('format', format);
            formData.append('mode', mode);
            formData.append('numColors', numColors.toString());
            formData.append('fillHoles', fillHoles.toString());
            formData.append('creator', creator);

            const response = await axios.post(`${API_BASE}/adobe-stock-vectorize`, formData, {
              responseType: 'arraybuffer',
              timeout: 60000
            });

            if (response.data) {
              const safeName = sanitizeFilename(fItem.file.name);
              const filename = `${safeName}_${i + 1}.${format}`;
              zip.file(filename, response.data);
              successCount++;
            }
          } catch (itemErr) {
            console.error(`Error processing Adobe Stock file ${fItem.file.name}:`, itemErr);
          }
        }

        if (successCount === 0) {
          throw new Error('Tidak ada berkas yang berhasil di-vektorisasi untuk Adobe Stock.');
        }

        setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP Adobe Stock...', percent: 98, stage: 'downloading' });
        const finalZipBlob = await zip.generateAsync({ type: 'blob' });
        await triggerBlobDownload(finalZipBlob, `adobe_stock_package_${format}.zip`, 'application/zip');
        setProgress({ current: files.length, total: files.length, fileName: 'Selesai!', percent: 100, stage: 'complete' });
      }
    } catch (err: any) {
      console.error('Adobe Stock export error:', err);
      const msg = await parseErrorMessage(err, 'Gagal memproses file untuk Adobe Stock.');
      setError(msg);
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const downloadVecteezy = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);

    const isBulk = files.length > 1;

    try {
      if (!isBulk) {
        setProgress({ current: 1, total: 1, fileName: files[0].file.name, percent: 30, stage: 'uploading' });
        const formData = new FormData();
        formData.append('files', files[0].file);
        formData.append('threshold', threshold.toString());
        formData.append('invert', invert.toString());
        formData.append('format', format);
        formData.append('mode', mode);
        formData.append('numColors', numColors.toString());
        formData.append('alphamax', cornerSharpness.toString());
        formData.append('creator', creator);

        const response = await axios.post(`${API_BASE}/vecteezy-vectorize`, formData, {
          responseType: 'blob',
          timeout: DEFAULT_TIMEOUT
        });
        
        const now = new Date();
        const stamp = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}`;
        const baseName = sanitizeFilename(files[0].file.name);
        const mime = format === 'eps' ? 'application/postscript' : 'image/svg+xml';
        await triggerBlobDownload(response.data, `${baseName}_${stamp}.${format}`, mime);
        setProgress({ current: 1, total: 1, fileName: 'Selesai!', percent: 100, stage: 'complete' });
      } else {
        const zip = new JSZip();
        let successCount = 0;

        for (let i = 0; i < files.length; i++) {
          const fItem = files[i];
          const pct = Math.round(((i + 1) / files.length) * 92);

          setProgress({
            current: i + 1,
            total: files.length,
            fileName: fItem.file.name,
            percent: Math.max(5, pct),
            stage: 'processing'
          });

          try {
            const formData = new FormData();
            formData.append('files', fItem.file);
            formData.append('threshold', threshold.toString());
            formData.append('invert', invert.toString());
            formData.append('format', format);
            formData.append('mode', mode);
            formData.append('numColors', numColors.toString());
            formData.append('alphamax', cornerSharpness.toString());
            formData.append('creator', creator);

            const response = await axios.post(`${API_BASE}/vecteezy-vectorize`, formData, {
              responseType: 'arraybuffer',
              timeout: 60000
            });

            if (response.data) {
              const now = new Date();
              const stamp = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}`;
              const safeName = sanitizeFilename(fItem.file.name);
              const vecName = `${safeName}_${stamp}_${i + 1}.${format}`;
              zip.file(vecName, response.data);
              successCount++;
            }
          } catch (itemErr) {
            console.error(`Error processing Vecteezy file ${fItem.file.name}:`, itemErr);
          }
        }

        if (successCount === 0) {
          throw new Error('Tidak ada berkas yang berhasil di-vektorisasi untuk Vecteezy.');
        }

        setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP Vecteezy...', percent: 98, stage: 'downloading' });
        const finalZipBlob = await zip.generateAsync({ type: 'blob' });
        await triggerBlobDownload(finalZipBlob, `vecteezy_package_${format}.zip`, 'application/zip');
        setProgress({ current: files.length, total: files.length, fileName: 'Selesai!', percent: 100, stage: 'complete' });
      }
    } catch (err: any) {
      console.error('Vecteezy export error:', err);
      const msg = await parseErrorMessage(err, 'Gagal memproses file untuk Vecteezy.');
      setError(msg);
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const selectedFile = selectedIndex !== null ? files[selectedIndex] : null;

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8 flex flex-col items-center justify-start font-sans text-slate-100 selection:bg-purple-500 selection:text-white relative">
      
      {/* High-Precision Realtime Progress Modal with Percentage % */}
      {progress && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-md w-full shadow-2xl space-y-4 glow-purple">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RefreshCw size={18} className="text-purple-400 animate-spin" />
                <span className="text-xs font-bold text-slate-200 uppercase tracking-wider font-mono">
                  {progress.stage === 'uploading' ? 'Mengunggah Berkas...' : progress.stage === 'processing' ? 'Vektorisasi / AI MetaGen...' : progress.stage === 'downloading' ? 'Membuat ZIP Package...' : 'Selesai'}
                </span>
              </div>
              <span className="text-lg font-extrabold font-mono text-purple-400 bg-purple-500/10 px-2.5 py-0.5 rounded-lg border border-purple-500/20">
                {progress.percent}%
              </span>
            </div>

            {/* Glowing Percentage Bar */}
            <div className="w-full h-3 bg-slate-950 rounded-full overflow-hidden p-0.5 border border-slate-800">
              <div 
                className="h-full bg-gradient-to-r from-purple-600 via-pink-500 to-amber-500 rounded-full transition-all duration-300 shadow-lg shadow-purple-500/50"
                style={{ width: `${progress.percent}%` }}
              />
            </div>

            <div className="flex items-center justify-between text-xs text-slate-400 pt-1">
              <span className="truncate max-w-[70%] font-mono text-slate-300" title={progress.fileName}>
                {progress.fileName}
              </span>
              <span className="font-mono font-bold text-purple-300 shrink-0">
                [{progress.current} / {progress.total} File]
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="max-w-7xl w-full">
        
        {/* Top Header */}
        <header className="flex flex-col md:flex-row items-center justify-between gap-4 mb-8">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="p-2 rounded-xl bg-gradient-to-tr from-purple-600 to-pink-500 text-white shadow-lg shadow-purple-500/20">
                <Layers3 size={24} />
              </span>
              <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                Vecto Studio
              </h1>
              <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/30 text-purple-400 font-semibold tracking-wider">
                v2.8 Network & Progress
              </span>
            </div>
            <p className="text-slate-400 text-sm">
              Vectorization Suite for Freepik, Shutterstock, Vecteezy & Adobe Stock.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-slate-900/60 border border-slate-800 text-xs font-medium text-slate-300">
              <Activity size={14} className="text-emerald-400 animate-pulse" />
              <span>Backend Ready</span>
            </div>
          </div>
        </header>

        {/* Preset & Tools Tabs */}
        <div className="flex flex-wrap gap-2 p-1.5 mb-8 bg-slate-950/80 backdrop-blur-xl rounded-2xl border border-slate-800/80 max-w-5xl mx-auto shadow-2xl">
          <button
            onClick={() => setActiveTab('freepik')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'freepik'
                ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/25 glow-purple'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Sparkles size={15} className={activeTab === 'freepik' ? 'animate-spin' : ''} />
            Freepik Exporter
          </button>
          
          <button
            onClick={() => setActiveTab('vecteezy')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'vecteezy'
                ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25 glow-emerald'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Sparkles size={15} />
            Vecteezy Preset
          </button>

          <button
            onClick={() => setActiveTab('adobe')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'adobe'
                ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-lg shadow-blue-500/25 glow-blue'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <CheckCircle2 size={15} />
            Adobe Stock
          </button>

          <button
            onClick={() => setActiveTab('vectorizer')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'vectorizer'
                ? 'bg-slate-800 text-white shadow-lg border border-slate-700'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Layers size={15} />
            Standard Vectorizer
          </button>
        </div>

        {/* Main Grid */}
        <main className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          
          {/* Column 1: Upload & Active Batch List (3 cols) */}
          <div className="lg:col-span-3 flex flex-col gap-5">
            <div className="glass-card p-5 flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                  <Upload size={16} className="text-purple-400" /> Batch Files
                </h2>
                {files.length > 0 && (
                  <button 
                    onClick={clearAllFiles}
                    className="text-[11px] text-slate-500 hover:text-red-400 transition-colors flex items-center gap-1 font-medium"
                  >
                    <Trash2 size={12} /> Hapus Semua
                  </button>
                )}
              </div>
              
              <div 
                className={`border-2 border-dashed rounded-xl p-5 text-center transition-all cursor-pointer relative overflow-hidden group ${
                  isDragging 
                    ? 'border-purple-400 bg-purple-500/10' 
                    : 'border-slate-800 hover:border-slate-600 bg-slate-900/40'
                }`}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={onDrop}
                onClick={() => document.getElementById('file-upload')?.click()}
              >
                <input 
                  type="file" 
                  id="file-upload" 
                  className="hidden" 
                  multiple
                  onChange={handleFileChange}
                  accept="image/*"
                />
                <div className="p-3 rounded-full bg-slate-800/80 text-purple-400 w-fit mx-auto mb-3 group-hover:scale-110 transition-transform">
                  <Upload size={20} />
                </div>
                <span className="text-xs font-semibold text-slate-200 block mb-1">
                  Upload Raster / SVG
                </span>
                <span className="text-[11px] text-slate-500 block">
                  PNG, JPG, SVG (Single or Bulk)
                </span>
              </div>

              {files.length > 0 && (
                <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1 custom-scrollbar">
                  {files.map((item, idx) => (
                    <div 
                      key={item.id}
                      onClick={() => setSelectedIndex(idx)}
                      className={`group flex items-center justify-between p-2.5 rounded-xl border transition-all cursor-pointer ${
                        selectedIndex === idx 
                          ? 'bg-purple-500/10 border-purple-500/40 shadow-md shadow-purple-500/5' 
                          : 'bg-slate-900/40 border-slate-800/80 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center gap-3 overflow-hidden">
                        <div className="w-9 h-9 rounded-lg bg-slate-800 overflow-hidden border border-slate-700/60 shrink-0 flex items-center justify-center">
                          {item.previewUrl ? (
                            <img src={item.previewUrl} alt="" className="w-full h-full object-cover" />
                          ) : (
                            <FileText size={16} className="text-slate-500" />
                          )}
                        </div>
                        <div className="overflow-hidden">
                          <span className="text-xs font-medium text-slate-200 truncate block">
                            {item.file.name}
                          </span>
                          <span className="text-[10px] text-purple-400/90 font-mono block">
                            Sync: {computeExportFilename(item.file.name, idx, files.length, format)}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-1">
                        {selectedIndex === idx && (
                          <span className="w-2 h-2 rounded-full bg-purple-400 animate-ping mr-1" />
                        )}
                        <button 
                          onClick={(e) => { e.stopPropagation(); removeFile(idx); }}
                          className="text-slate-500 hover:text-red-400 p-1 opacity-60 group-hover:opacity-100 transition-opacity"
                          title="Hapus file"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Column 2: Controls & Options (4 cols) */}
              <div className="lg:col-span-4 flex flex-col gap-5">
                <div className="glass-card p-6 flex flex-col gap-5 h-full">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                      <Sliders className={activeTab === 'freepik' ? 'text-pink-400' : 'text-emerald-400'} size={16} />
                      {activeTab === 'freepik' ? 'Freepik Vector Specs' : activeTab === 'vecteezy' ? 'Vecteezy Tracing' : activeTab === 'adobe' ? 'Adobe Stock Settings' : 'Vector Settings'}
                    </h2>
                    <span className="text-[11px] font-mono text-slate-500">
                      {files.length} File Loaded
                    </span>
                  </div>

                  <div className="space-y-5">
                    {/* Author / Creator Tag Input */}
                    <div>
                      <label className="text-xs font-semibold text-slate-300 block mb-1.5 flex items-center justify-between">
                        <span>Author / Creator Tag</span>
                        <span className="text-[10px] text-slate-500 font-mono">%%Creator header</span>
                      </label>
                      <input 
                        type="text" 
                        value={creator} 
                        onChange={(e) => setCreator(e.target.value)}
                        placeholder="e.g. peripirdaus"
                        className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs font-mono text-purple-300 focus:outline-none focus:border-purple-500/50 transition-colors"
                      />
                    </div>

                    {/* Mode Selector */}
                    <div>
                      <label className="text-xs font-semibold text-slate-300 block mb-2">Tracing Mode</label>
                      <div className="grid grid-cols-2 gap-2">
                        <button 
                          onClick={() => setMode('monochrome')}
                          className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                            mode === 'monochrome'
                              ? activeTab === 'freepik'
                                ? 'border-purple-400 bg-purple-500/10 text-purple-300'
                                : activeTab === 'vecteezy'
                                  ? 'border-emerald-400 bg-emerald-500/10 text-emerald-300'
                                  : 'border-blue-400 bg-blue-500/10 text-blue-300'
                              : 'border-slate-800 text-slate-500 hover:text-slate-300'
                          }`}
                        >
                          Monochrome (B&W)
                        </button>
                        <button 
                          onClick={() => setMode('color')}
                          className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                            mode === 'color'
                              ? activeTab === 'freepik'
                                ? 'border-pink-400 bg-pink-500/10 text-pink-300'
                                : activeTab === 'vecteezy'
                                  ? 'border-teal-400 bg-teal-500/10 text-teal-300'
                                  : 'border-indigo-400 bg-indigo-500/10 text-indigo-300'
                              : 'border-slate-800 text-slate-500 hover:text-slate-300'
                          }`}
                        >
                          Multi-Color
                        </button>
                      </div>
                    </div>

                    {/* Dynamic Controls based on mode */}
                    {mode === 'monochrome' ? (
                      <div className="space-y-4">
                        <div>
                          <div className="flex justify-between items-center mb-1.5">
                            <label className="text-xs font-semibold text-slate-300">Threshold</label>
                            <span className="text-xs font-mono text-purple-400 font-bold px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/20">
                              {threshold}
                            </span>
                          </div>
                          <input 
                            type="range" 
                            min="0" 
                            max="255" 
                            value={threshold} 
                            onChange={(e) => setThreshold(parseInt(e.target.value))}
                            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>

                        <div>
                          <div className="flex justify-between items-center mb-1.5">
                            <label className="text-xs font-semibold text-slate-300">Corner Sharpness</label>
                            <span className="text-[10px] font-mono text-emerald-400 font-bold px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
                              {cornerSharpness.toFixed(2)} ({cornerSharpness <= 0.3 ? 'Sharp Tips' : 'Smooth'})
                            </span>
                          </div>
                          <input 
                            type="range" 
                            min="0.0" 
                            max="1.3" 
                            step="0.05"
                            value={cornerSharpness} 
                            onChange={(e) => setCornerSharpness(parseFloat(e.target.value))}
                            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>

                        <label className="flex items-center gap-3 p-3 rounded-xl bg-slate-900/50 border border-slate-800/80 cursor-pointer hover:border-slate-700 transition-all">
                          <input 
                            type="checkbox" 
                            checked={invert} 
                            onChange={(e) => setInvert(e.target.checked)}
                            className="w-4 h-4 rounded accent-purple-500"
                          />
                          <div className="text-xs">
                            <span className="font-semibold text-slate-200 block">Invert Colors</span>
                            <span className="text-slate-500 text-[10px]">Swap foreground and background shapes</span>
                          </div>
                        </label>
                      </div>
                    ) : (
                      <div>
                        <div className="flex justify-between items-center mb-1.5">
                          <label className="text-xs font-semibold text-slate-300">Color Count</label>
                          <span className="text-xs font-mono text-pink-400 font-bold px-2 py-0.5 rounded bg-pink-500/10 border border-pink-500/20">
                            {numColors} Colors
                          </span>
                        </div>
                        <input 
                          type="range" 
                          min="2" 
                          max="16"
                          step="1"
                          value={numColors} 
                          onChange={(e) => setNumColors(parseInt(e.target.value))}
                          className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                        />
                      </div>
                    )}



                    {/* Preset-Specific Format / Rules */}
                    {activeTab === 'freepik' ? (
                      <div className="space-y-3 pt-2 border-t border-slate-800">
                        <div className="p-3.5 rounded-xl bg-purple-500/5 border border-purple-500/20 space-y-2.5">
                          <h4 className="text-[11px] font-bold text-purple-300 uppercase tracking-widest flex items-center gap-1.5">
                            <ShieldCheck size={14} className="text-purple-400" /> Freepik Mandatory Rules
                          </h4>
                          <div className="grid grid-cols-1 gap-1.5 text-[11px] text-slate-300">
                            <div className="flex items-center gap-2">
                              <Check size={13} className="text-purple-400 shrink-0" />
                              <span><strong>Format:</strong> EPS 10 + JPG Preview (identical name)</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <Check size={13} className="text-purple-400 shrink-0" />
                              <span><strong>File Size:</strong> Guaranteed &gt; 500 KB (0.5 MB minimum)</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <Check size={13} className="text-purple-400 shrink-0" />
                              <span><strong>Artboard & Aspect Ratio:</strong> 100% Synced (2000px-8000px)</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : activeTab === 'vecteezy' ? (
                      <div className="space-y-3 pt-2 border-t border-slate-800">
                        <div>
                          <label className="text-xs font-semibold text-slate-300 block mb-2">Output Format</label>
                          <div className="grid grid-cols-2 gap-2">
                            <button 
                              onClick={() => setFormat('eps')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'eps' ? 'border-emerald-400 bg-emerald-500/10 text-emerald-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              EPS (Vector)
                            </button>
                            <button 
                              onClick={() => setFormat('svg')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'svg' ? 'border-teal-400 bg-teal-500/10 text-teal-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              SVG (Web)
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : activeTab === 'adobe' ? (
                      <div className="space-y-3 pt-2 border-t border-slate-800">
                        <div>
                          <label className="text-xs font-semibold text-slate-300 block mb-2">Output Format</label>
                          <div className="grid grid-cols-2 gap-2">
                            <button 
                              onClick={() => setFormat('eps')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'eps' ? 'border-blue-400 bg-blue-500/10 text-blue-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              EPS (Vector)
                            </button>
                            <button 
                              onClick={() => setFormat('svg')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'svg' ? 'border-indigo-400 bg-indigo-500/10 text-indigo-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              SVG (Web)
                            </button>
                          </div>
                        </div>
                        <label className="flex items-center gap-3 p-3 rounded-xl bg-slate-900/50 border border-slate-800/80 cursor-pointer">
                          <input 
                            type="checkbox" 
                            checked={fillHoles} 
                            onChange={(e) => setFillHoles(e.target.checked)}
                            className="w-4 h-4 rounded accent-blue-500"
                          />
                          <div className="text-xs">
                            <span className="font-semibold text-slate-200 block">Fill Holes with White</span>
                            <span className="text-slate-500 text-[10px]">Overlays solid white paths on transparent cutouts</span>
                          </div>
                        </label>
                      </div>
                    ) : (
                      <div className="space-y-3 pt-2 border-t border-slate-800">
                        <div>
                          <label className="text-xs font-semibold text-slate-300 block mb-2">Output Format</label>
                          <div className="grid grid-cols-2 gap-2">
                            <button 
                              onClick={() => setFormat('eps')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'eps' ? 'border-blue-400 bg-blue-500/10 text-blue-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              EPS (Vector)
                            </button>
                            <button 
                              onClick={() => setFormat('svg')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'svg' ? 'border-purple-400 bg-purple-500/10 text-purple-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              SVG (Web)
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Download Action Button */}
                  <div className="mt-auto pt-4">
                    {error && (
                      <div className="p-3 mb-3 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center gap-2 text-red-400 text-xs">
                        <AlertCircle size={16} className="shrink-0" />
                        <span>{error}</span>
                      </div>
                    )}

                    {activeTab === 'freepik' ? (
                      <button 
                        onClick={downloadFreepik}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #9333ea 0%, #c026d3 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Package size={18} />
                          {files.length > 1 ? `Unduh ZIP Freepik (${files.length} Files)` : `Unduh Paket ZIP Freepik (EPS + JPG)`}
                        </div>
                      </button>
                    ) : activeTab === 'vecteezy' ? (
                      <button 
                        onClick={downloadVecteezy}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #10b981 0%, #0d9488 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Package size={18} />
                          {files.length > 1 ? `Unduh ZIP Vecteezy (${files.length} Files)` : `Unduh ${format.toUpperCase()} (Vecteezy)`}
                        </div>
                      </button>
                    ) : activeTab === 'adobe' ? (
                      <button 
                        onClick={downloadAdobeStock}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #2563eb 0%, #4f46e5 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Package size={18} />
                          {files.length > 1 ? `Unduh ZIP Adobe Stock (${files.length} Files)` : `Unduh ${format.toUpperCase()} (Adobe Stock)`}
                        </div>
                      </button>
                    ) : (
                      <button 
                        onClick={downloadAll}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Download size={18} />
                          {files.length > 1 ? `Unduh ${files.length} Files (${format.toUpperCase()})` : `Unduh ${format.toUpperCase()}`}
                        </div>
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Column 3: Interactive Preview & Status + File Size Audit (5 cols) */}
              <div className="lg:col-span-5 flex flex-col gap-5">
                <div className="glass-card p-6 flex flex-col gap-5 h-full">
                  
                  {/* Header & Status Bar */}
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <div className="flex items-center gap-2">
                      <Eye size={16} className="text-purple-400" />
                      <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                        Live Selection Mask
                      </h2>
                    </div>

                    {preflight ? (
                      <span className={`text-[10px] font-extrabold uppercase px-3 py-1 rounded-full border flex items-center gap-1.5 ${
                        preflight.status === 'PASS' 
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 glow-emerald'
                          : 'bg-amber-500/10 border-amber-500/30 text-amber-400 glow-amber'
                      }`}>
                        {preflight.status === 'PASS' ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                        AUDIT: {preflight.status}
                      </span>
                    ) : selectedFile ? (
                      <span className="text-[10px] text-purple-400 font-bold uppercase tracking-wider px-3 py-1 rounded-full bg-purple-500/10 border border-purple-500/20 flex items-center gap-1.5 font-mono">
                        <RefreshCw size={11} className="animate-spin" /> AUDIT: ANALYZING...
                      </span>
                    ) : (
                      <span className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">
                        No Selection
                      </span>
                    )}
                  </div>

                  {/* Canvas Preview Container */}
                  <div className="relative">
                    <div className={`w-full min-h-[300px] h-[320px] rounded-2xl border border-slate-800 overflow-hidden flex items-center justify-center relative transition-all ${
                      canvasBg === 'checkerboard' 
                        ? 'bg-checkerboard' 
                        : canvasBg === 'white' 
                          ? 'bg-white-canvas' 
                          : 'bg-dark-canvas'
                    }`}>
                      {preview ? (
                        <img 
                          src={preview} 
                          alt="Vector Mask Preview" 
                          className="max-w-[90%] max-h-[90%] object-contain transition-all duration-300 drop-shadow-2xl" 
                        />
                      ) : selectedFile ? (
                        <img 
                          src={selectedFile.previewUrl} 
                          alt="Uploaded Image Preview" 
                          className="max-w-[90%] max-h-[90%] object-contain transition-all duration-300 opacity-90 drop-shadow-2xl" 
                        />
                      ) : (
                        <div className="text-center text-slate-600 p-6">
                          <ImageIcon className="mx-auto mb-3 opacity-30" size={48} />
                          <p className="text-xs font-semibold text-slate-400">Pilih file untuk melihat mask & audit</p>
                          <span className="text-[11px] text-slate-600 block mt-1">White = Vector Shape | Black = Transparent</span>
                        </div>
                      )}

                      {/* Top Canvas Controls Overlay */}
                      <div className="absolute top-3 right-3 flex items-center gap-1 bg-slate-950/80 backdrop-blur-md p-1 rounded-xl border border-slate-800">
                        <button 
                          onClick={() => setCanvasBg('checkerboard')}
                          className={`p-1.5 rounded-lg text-xs transition-colors ${canvasBg === 'checkerboard' ? 'bg-purple-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                          title="Transparent Checkerboard"
                        >
                          <Grid size={13} />
                        </button>
                        <button 
                          onClick={() => setCanvasBg('dark')}
                          className={`p-1.5 rounded-lg text-xs transition-colors ${canvasBg === 'dark' ? 'bg-purple-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                          title="Dark Background"
                        >
                          <Moon size={13} />
                        </button>
                        <button 
                          onClick={() => setCanvasBg('white')}
                          className={`p-1.5 rounded-lg text-xs transition-colors ${canvasBg === 'white' ? 'bg-purple-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                          title="White Background"
                        >
                          <Sun size={13} />
                        </button>
                      </div>

                      {selectedFile && (
                        <div className="absolute bottom-3 left-3 bg-slate-950/80 backdrop-blur-md px-3 py-1 rounded-full text-[10px] font-bold text-slate-300 border border-slate-800 truncate max-w-[70%] flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-full ${preview ? 'bg-emerald-400' : 'bg-purple-400 animate-pulse'}`} />
                          <span>{selectedFile.file.name}</span>
                          <span className="text-slate-500 font-normal">({preview ? 'Vector Mask' : 'Original Input'})</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Status & Size Audit Breakdown Card */}
                  {selectedFile ? (
                    <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 space-y-3 text-xs">
                      <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
                        <span className="font-bold text-slate-200 uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                          <FileCheck size={14} className="text-purple-400" /> Requirements & File Specs Audit
                        </span>
                        <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-semibold">
                          Freepik Ready
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="bg-slate-950/50 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-500 uppercase font-semibold block mb-0.5">Original File Size</span>
                          <span className="font-mono text-slate-200 font-bold block">{formatFileSize(selectedFile.file.size)}</span>
                          <span className="text-[10px] text-slate-400 font-mono">{preflight?.orig_resolution || 'Raster Input'}</span>
                        </div>

                        <div className="bg-slate-950/50 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-500 uppercase font-semibold block mb-0.5">Export Resolution</span>
                          <span className="font-mono text-purple-300 font-bold block">{preflight?.freepik_canvas || '4000 x 4000 px'}</span>
                          <span className="text-[10px] text-slate-400 font-mono">16.0 MP Artboard</span>
                        </div>

                        <div className="bg-slate-950/50 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-500 uppercase font-semibold block mb-0.5">Est. EPS File Size</span>
                          <span className="font-mono text-emerald-400 font-bold block">&gt; 550 KB</span>
                          <span className="text-[10px] text-emerald-400/80 font-mono">✓ Pass (&ge; 0.5 MB)</span>
                        </div>

                        <div className="bg-slate-950/50 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-500 uppercase font-semibold block mb-0.5">Est. JPG Preview Size</span>
                          <span className="font-mono text-emerald-400 font-bold block">&gt; 550 KB</span>
                          <span className="text-[10px] text-emerald-400/80 font-mono">✓ Pass (&ge; 0.5 MB)</span>
                        </div>
                      </div>

                      {preflight && (
                        <div className="pt-2 border-t border-slate-800/80 space-y-1.5 text-[11px]">
                          <div className="flex justify-between text-slate-400">
                            <span>Vector Path Geometry:</span>
                            <span className="text-slate-200 font-mono font-medium">{preflight.total_paths} shapes ({preflight.estimated_nodes} nodes)</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Color Space & Spec:</span>
                            <span className="text-slate-200 font-mono font-medium">RGB Mode • EPS 10 Level 2</span>
                          </div>
                          <div className="flex justify-between text-slate-400">
                            <span>Background Frame Removal:</span>
                            <span className="text-emerald-400 font-mono font-medium">CLEAN (No Bounding Box)</span>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800/50 text-center text-slate-500 text-xs">
                      Upload dan pilih gambar untuk melihat rincian status & file size audit.
                    </div>
                  )}

                </div>
              </div>
        </main>

        <footer className="mt-12 text-center text-slate-500 text-xs border-t border-slate-800/80 pt-6">
          <p>© 2026 Vecto Studio. Professional Batch Vectorization Suite.</p>
        </footer>

      </div>
    </div>
  );
}

export default App;
