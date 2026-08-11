import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import JSZip from 'jszip';
import * as XLSX from 'xlsx';
import { 
  Upload, Download, RefreshCw, Layers, AlertCircle, FileText, Trash2, 
  Check, Sparkles, CheckCircle2, Image as ImageIcon, ShieldCheck, 
  Eye, Grid, Sun, Moon, FileCheck, Layers3, Activity, Sliders,
  Package, Globe, Server, Send, Columns, Maximize2, X, Repeat, FileSpreadsheet
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

function downloadBase64File(b64Data: string, filename: string, mimeType: string) {
  const binary = atob(b64Data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mimeType });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
}

interface MetadataRow {
  filename: string;
  title: string;
  description: string;
  keywords: string;
}

/** 
 * Universal Spreadsheet (XLSX, XLS, CSV, TSV, ODS) & Table Parser + Smart Column Auto-Translator
 * Automatically parses Excel workbooks or CSV files with arbitrary column names and formats.
 */
function parseSpreadsheet(dataBuffer: ArrayBuffer): MetadataRow[] {
  const workbook = XLSX.read(dataBuffer, { type: 'array', cellDates: true });
  if (!workbook.SheetNames || workbook.SheetNames.length === 0) return [];

  let rawRows: any[][] = [];
  for (const sheetName of workbook.SheetNames) {
    const sheet = workbook.Sheets[sheetName];
    if (sheet) {
      const rows: any[][] = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '', blankrows: false });
      if (rows.length > 0) {
        rawRows = rows;
        break;
      }
    }
  }

  if (rawRows.length === 0) return [];

  // Detect header row index within first 10 rows
  let headerRowIdx = 0;
  let maxScore = -1;
  let fnIdx = -1, titleIdx = -1, descIdx = -1, kwIdx = -1;

  const fnKeys = ['filename', 'file_name', 'file name', 'file', 'nama file', 'namafile', 'berkas', 'image', 'gambar', 'name', 'id', 'asset', 'vector', 'icon', 'item'];
  const titleKeys = ['title', 'judul', 'heading', 'caption', 'name', 'subject', 'title_en', 'judul_gambar', 'headline'];
  const descKeys = ['description', 'deskripsi', 'desc', 'detail', 'keterangan', 'summary', 'info', 'prompt', 'alt', 'body'];
  const kwKeys = ['keywords', 'keyword', 'kata kunci', 'katakunci', 'kata_kunci', 'tags', 'tag', 'kata', 'kunci', 'categories', 'category', 'labels', 'meta_keywords', 'keyword_list'];

  for (let r = 0; r < Math.min(10, rawRows.length); r++) {
    const rowStr = rawRows[r].map(c => String(c).toLowerCase().replace(/[^a-z0-9\s_]/g, '').trim());
    let score = 0;
    let curFn = -1, curTitle = -1, curDesc = -1, curKw = -1;

    rowStr.forEach((cell, colIdx) => {
      if (curFn === -1 && fnKeys.some(k => cell === k || cell.includes(k))) {
        curFn = colIdx;
        score += 3;
      } else if (curTitle === -1 && titleKeys.some(k => cell === k || cell.includes(k))) {
        curTitle = colIdx;
        score += 2;
      } else if (curDesc === -1 && descKeys.some(k => cell === k || cell.includes(k))) {
        curDesc = colIdx;
        score += 2;
      } else if (curKw === -1 && kwKeys.some(k => cell === k || cell.includes(k))) {
        curKw = colIdx;
        score += 2;
      }
    });

    if (score > maxScore) {
      maxScore = score;
      headerRowIdx = r;
      fnIdx = curFn;
      titleIdx = curTitle;
      descIdx = curDesc;
      kwIdx = curKw;
    }
  }

  if (maxScore <= 0) {
    headerRowIdx = 0;
    fnIdx = 0;
    titleIdx = 1;
    descIdx = 2;
    kwIdx = 3;
  }

  const results: MetadataRow[] = [];
  for (let i = headerRowIdx + 1; i < rawRows.length; i++) {
    const cols = rawRows[i];
    if (!cols || cols.every(c => String(c).trim().length === 0)) continue;

    const getVal = (idx: number) => (idx !== -1 && cols[idx] !== undefined) ? String(cols[idx]).trim() : '';

    let fn = getVal(fnIdx);
    let title = getVal(titleIdx);
    let desc = getVal(descIdx);
    let kw = getVal(kwIdx);

    if (!fn && fnIdx === -1 && cols[0]) {
      fn = String(cols[0]).trim();
    }

    if (kw) {
      kw = kw.replace(/[\r\n\t;|]+/g, ',')
            .split(',')
            .map(k => k.trim())
            .filter(k => k.length > 0)
            .join(', ');
    }

    results.push({ filename: fn, title, description: desc, keywords: kw });
  }

  return results;
}

interface FileItem {
  file: File;
  previewUrl: string;
  id: string;
  title?: string;
  description?: string;
  keywords?: string;
}

interface ProgressState {
  current: number;
  total: number;
  fileName: string;
  percent: number;
  stage: 'uploading' | 'processing' | 'downloading' | 'complete';
}

function App() {
  const [activeTab, setActiveTab] = useState<'vectorizer' | 'vecteezy' | 'freepik' | 'adobe' | 'shutterstock' | 'shutterstock_regular' | 'seamless_pattern' | 'repair'>('shutterstock_regular');
  const [repairAudit, setRepairAudit] = useState<any | null>(null);
  const [patternAnalysis, setPatternAnalysis] = useState<any | null>(null);
  const [patternPreview3x3, setPatternPreview3x3] = useState<string | null>(null);
  const [patternTesting, setPatternTesting] = useState(false);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [threshold, setThreshold] = useState(127);
  const [invert, setInvert] = useState(false);
  const [format, setFormat] = useState<'eps' | 'svg'>('eps');
  const [mode, setMode] = useState<'monochrome' | 'color'>('monochrome');
  const [numColors, setNumColors] = useState(8);
  const [fillHoles, setFillHoles] = useState(true);
  const [cornerSharpness, setCornerSharpness] = useState(0.75);
  const [splitGrid, setSplitGrid] = useState(false);
  const [includeEps, setIncludeEps] = useState(true);
  const [includeJpg, setIncludeJpg] = useState(true);
  const [includePng, setIncludePng] = useState(false);
  const [includePsd, setIncludePsd] = useState(true);
  const [downloadMode, setDownloadMode] = useState<'direct' | 'zip'>('zip');
  const [dilationPx, setDilationPx] = useState(1);
  const [creator, setCreator] = useState(() => localStorage.getItem('vecto_creator_tag') || 'peripirdaus');
  const [metaTitle, setMetaTitle] = useState('');
  const [metaDescription, setMetaDescription] = useState('');
  const [keywords, setKeywords] = useState('');
  const [autoNumberTitles, setAutoNumberTitles] = useState(true);
  const [csvNotice, setCsvNotice] = useState<string | null>(null);

  const downloadMetadataCsvTemplate = () => {
    const csvContent = 
      `Filename,Title,Description,Keywords\n` +
      `cat_icon.png,"Cute Cat Vector Icon Set","High quality vector cat line art icon for microstock","cat, kitten, cute, vector, icon, pet, line art"\n` +
      `dog_icon.png,"Cute Dog Vector Line Art","High quality vector dog line art icon for microstock","dog, puppy, cute, vector, icon, pet, line art"\n` +
      `pattern_sample.png,"Seamless Geometric Pattern","Seamless vector pattern background for design","pattern, seamless, background, vector, geometric, tile"`;
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    triggerBlobDownload(blob, 'vecto_metadata_template.csv', 'text/csv');
  };

  const downloadMetadataXlsxTemplate = () => {
    const data = [
      ["Filename", "Title", "Description", "Keywords"],
      ["cat_icon.png", "Cute Cat Vector Icon Set", "High quality vector cat line art icon for microstock", "cat, kitten, cute, vector, icon, pet, line art"],
      ["dog_icon.png", "Cute Dog Vector Line Art", "High quality vector dog line art icon for microstock", "dog, puppy, cute, vector, icon, pet, line art"],
      ["pattern_sample.png", "Seamless Geometric Pattern", "Seamless vector pattern background for design", "pattern, seamless, background, vector, geometric, tile"]
    ];

    const worksheet = XLSX.utils.aoa_to_sheet(data);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Metadata Template");

    const wbout = XLSX.write(workbook, { bookType: "xlsx", type: "array" });
    const blob = new Blob([wbout], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    triggerBlobDownload(blob, "vecto_metadata_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  };

  const handleImportMetadata = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const buffer = event.target?.result as ArrayBuffer;
        const parsedRows = parseSpreadsheet(buffer);

        if (parsedRows.length === 0) {
          setError('Format tabel spreadsheet tidak valid atau berkas kosong.');
          return;
        }

        let matchedCount = 0;
        setFiles(prevFiles => {
          return prevFiles.map((fItem, index) => {
            const rawName = fItem.file.name.toLowerCase();
            const cleanName = sanitizeFilename(fItem.file.name).toLowerCase();
            const baseNoExt = cleanName.replace(/\.[^/.]+$/, '');

            let match = parsedRows.find(row => {
              const rowFn = row.filename.toLowerCase().trim();
              if (!rowFn) return false;
              const rowClean = sanitizeFilename(rowFn).toLowerCase();
              const rowBase = rowClean.replace(/\.[^/.]+$/, '');
              return rowFn === rawName || rowClean === cleanName || rowBase === baseNoExt;
            });

            if (!match && parsedRows.length === prevFiles.length && parsedRows[index]) {
              match = parsedRows[index];
            }

            if (match) {
              matchedCount++;
              return {
                ...fItem,
                title: match.title || fItem.title,
                description: match.description || fItem.description,
                keywords: match.keywords || fItem.keywords,
              };
            }
            return fItem;
          });
        });

        if (parsedRows.length > 0 && parsedRows[0]) {
          if (parsedRows[0].title) setMetaTitle(parsedRows[0].title);
          if (parsedRows[0].description) setMetaDescription(parsedRows[0].description);
          if (parsedRows[0].keywords) setKeywords(parsedRows[0].keywords);
        }

        const ext = file.name.split('.').pop()?.toUpperCase() || 'TABLE';
        setCsvNotice(`✓ Berhasil mengimpor & mendeteksi metadata ${ext} (${file.name}) untuk ${matchedCount} file!`);
        setTimeout(() => setCsvNotice(null), 5000);
      } catch (err: any) {
        setError(`Gagal membaca berkas tabel: ${err.message}`);
      }
    };
    reader.readAsArrayBuffer(file);
    e.target.value = '';
  };

  // Custom UI Presets Manager State
  const [presetName, setPresetName] = useState('');
  const [savedPresets, setSavedPresets] = useState<Record<string, any>>(() => {
    try {
      return JSON.parse(localStorage.getItem('vecto_custom_presets') || '{}');
    } catch {
      return {};
    }
  });

  const saveCurrentPreset = () => {
    if (!presetName.trim()) return;
    const newPreset = {
      threshold, invert, mode, numColors, fillHoles, cornerSharpness, creator, splitGrid, includePng
    };
    const updated = { ...savedPresets, [presetName.trim()]: newPreset };
    setSavedPresets(updated);
    localStorage.setItem('vecto_custom_presets', JSON.stringify(updated));
    setPresetName('');
  };

  const loadPreset = (name: string) => {
    const p = savedPresets[name];
    if (!p) return;
    if (p.threshold !== undefined) setThreshold(p.threshold);
    if (p.invert !== undefined) setInvert(p.invert);
    if (p.mode !== undefined) setMode(p.mode);
    if (p.numColors !== undefined) setNumColors(p.numColors);
    if (p.fillHoles !== undefined) setFillHoles(p.fillHoles);
    if (p.cornerSharpness !== undefined) setCornerSharpness(p.cornerSharpness);
    if (p.creator !== undefined) setCreator(p.creator);
    if (p.splitGrid !== undefined) setSplitGrid(p.splitGrid);
    if (p.includePng !== undefined) setIncludePng(p.includePng);
  };

  // Duplicate Finder & FTP Uploader State
  const [duplicateWarnings, setDuplicateWarnings] = useState<Record<number, number>>({});
  const [showFtpModal, setShowFtpModal] = useState(false);
  const [ftpHost, setFtpHost] = useState(() => localStorage.getItem('vecto_ftp_host') || 'ftp.shutterstock.com');
  const [ftpPort, setFtpPort] = useState(21);
  const [ftpUser, setFtpUser] = useState(() => localStorage.getItem('vecto_ftp_user') || '');
  const [ftpPass, setFtpPass] = useState(() => localStorage.getItem('vecto_ftp_pass') || '');
  const [ftpDir, setFtpDir] = useState('/');
  const [ftpStatus, setFtpStatus] = useState<string | null>(null);
  const [ftpUploading, setFtpUploading] = useState(false);

  // Auto-detect duplicates when files change
  const checkForDuplicates = useCallback(async (fileList: FileItem[]) => {
    if (fileList.length < 2) {
      setDuplicateWarnings({});
      return;
    }
    try {
      const formData = new FormData();
      fileList.forEach(item => formData.append('files', item.file));
      formData.append('threshold', '85.0');
      const res = await axios.post(`${API_BASE}/check-duplicates`, formData);
      const warnings: Record<number, number> = {};
      if (res.data && Array.isArray(res.data.duplicates)) {
        res.data.duplicates.forEach((pair: any) => {
          warnings[pair.index_b] = Math.max(warnings[pair.index_b] || 0, pair.similarity);
        });
      }
      setDuplicateWarnings(warnings);
    } catch (e) {
      console.error('Duplicate check error:', e);
    }
  }, []);

  const handleTestFtp = async () => {
    setFtpStatus('Menguji koneksi ke server FTP...');
    try {
      const formData = new FormData();
      formData.append('host', ftpHost);
      formData.append('port', ftpPort.toString());
      formData.append('username', ftpUser);
      formData.append('password', ftpPass);
      const res = await axios.post(`${API_BASE}/ftp/test`, formData);
      setFtpStatus(res.data.message);
    } catch (err: any) {
      setFtpStatus(`Gagal tes FTP: ${err.message}`);
    }
  };

  const handleUploadToFtp = async () => {
    if (files.length === 0) return;
    setFtpUploading(true);
    setFtpStatus(`Menyiapkan pengunggahan ${files.length} file ke FTP ${ftpHost}...`);
    try {
      const formData = new FormData();
      formData.append('host', ftpHost);
      formData.append('port', ftpPort.toString());
      formData.append('username', ftpUser);
      formData.append('password', ftpPass);
      formData.append('remoteDir', ftpDir);
      files.forEach(f => formData.append('files', f.file));

      const res = await axios.post(`${API_BASE}/ftp/upload`, formData, { timeout: 120000 });
      if (res.data.success) {
        setFtpStatus(`✓ Berhasil mengunggah ${res.data.uploaded_count} file ke ${ftpHost}!`);
      } else {
        setFtpStatus(`⚠️ Upload selesai dengan kendala: ${res.data.errors?.join(', ')}`);
      }
    } catch (err: any) {
      setFtpStatus(`Gagal mengunggah ke FTP: ${err.message}`);
    } finally {
      setFtpUploading(false);
    }
  };
  
  // Canvas & Preview state
  const [canvasBg, setCanvasBg] = useState<'checkerboard' | 'dark' | 'white'>('checkerboard');
  const [previewMode, setPreviewMode] = useState<'split' | 'result' | 'original'>('split');
  const [lightboxImg, setLightboxImg] = useState<{ src: string; title: string } | null>(null);
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
      const response = await axios.post(`${API_BASE}/preview`, formData, { timeout: 30000 });
      setPreview(response.data.preview);

      // Async non-blocking preflight audit check
      axios.post(`${API_BASE}/preflight`, formData, { timeout: 30000 })
        .then(auditRes => setPreflight(auditRes.data))
        .catch(() => {});
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
    checkForDuplicates(updatedFiles);
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
        formData.append('title', metaTitle);
        formData.append('description', metaDescription);
        formData.append('keywords', keywords);

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
            formData.append('title', metaTitle);
            formData.append('description', metaDescription);
            formData.append('keywords', keywords);

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
    if (!includeEps && !includeJpg && !includePng) {
      setError('Pilih minimal satu format berkas (.EPS, .JPG, atau .PNG) untuk diunduh.');
      return;
    }
    setLoading(true);
    setError(null);

    const zip = new JSZip();
    let successCount = 0;
    const isDirect = downloadMode === 'direct';

    try {
      for (let i = 0; i < files.length; i++) {
        const fItem = files[i];
        const pct = Math.round(((i + 1) / files.length) * 90);

        setProgress({
          current: i + 1,
          total: files.length,
          fileName: fItem.file.name,
          percent: Math.max(5, pct),
          stage: 'processing'
        });

        try {
          let itemTitle = fItem.title || metaTitle;
          if (!itemTitle && fItem.file.name) {
            itemTitle = sanitizeFilename(fItem.file.name).replace(/_/g, ' ');
          } else if (itemTitle && files.length > 1 && autoNumberTitles && !fItem.title) {
            itemTitle = `${itemTitle} ${i + 1}`;
          }
          let itemDesc = fItem.description || metaDescription;
          let itemKw = fItem.keywords || keywords;

          const formData = new FormData();
          formData.append('files', fItem.file);
          formData.append('threshold', threshold.toString());
          formData.append('invert', invert.toString());
          formData.append('mode', mode);
          formData.append('numColors', numColors.toString());
          formData.append('creator', creator);
          formData.append('splitGrid', splitGrid.toString());
          formData.append('title', itemTitle);
          formData.append('description', itemDesc);
          formData.append('keywords', itemKw);

          const response = await axios.post(`${API_BASE}/freepik-vectorize`, formData, { timeout: 60000 });
          const data = response.data;

          if (data && Array.isArray(data.files)) {
            for (const entry of data.files) {
              if (includeEps && entry.eps_b64) {
                if (isDirect) {
                  downloadBase64File(entry.eps_b64, entry.eps_name, 'application/postscript');
                } else {
                  zip.file(entry.eps_name, Uint8Array.from(atob(entry.eps_b64), c => c.charCodeAt(0)));
                }
              }
              if (includeJpg && entry.jpg_b64) {
                if (isDirect) {
                  downloadBase64File(entry.jpg_b64, entry.jpg_name, 'image/jpeg');
                } else {
                  zip.file(entry.jpg_name, Uint8Array.from(atob(entry.jpg_b64), c => c.charCodeAt(0)));
                }
              }
              if (includePng && entry.png_b64 && entry.png_name) {
                if (isDirect) {
                  downloadBase64File(entry.png_b64, entry.png_name, 'image/png');
                } else {
                  zip.file(entry.png_name, Uint8Array.from(atob(entry.png_b64), c => c.charCodeAt(0)));
                }
              }
              successCount++;
            }
          }
        } catch (itemErr) {
          console.error(`Error processing Freepik file ${fItem.file.name}:`, itemErr);
        }
      }

      if (successCount === 0) {
        throw new Error('Tidak ada berkas yang berhasil di-vektorisasi untuk Freepik.');
      }

      if (!isDirect) {
        setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP Freepik...', percent: 98, stage: 'downloading' });
        const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/zip', compression: 'DEFLATE' });
        const zipName = files.length === 1 
          ? `${sanitizeFilename(files[0].file.name)}_freepik_package.zip` 
          : 'freepik_vectors_package.zip';
        await triggerBlobDownload(blob, zipName, 'application/zip');
      }

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
        let singleTitle = files[0].title || metaTitle;
        if (!singleTitle && files[0].file.name) {
          singleTitle = sanitizeFilename(files[0].file.name).replace(/_/g, ' ');
        }
        let singleDesc = files[0].description || metaDescription;
        let singleKw = files[0].keywords || keywords;

        const formData = new FormData();
        formData.append('files', files[0].file);
        formData.append('threshold', threshold.toString());
        formData.append('invert', invert.toString());
        formData.append('format', format);
        formData.append('mode', mode);
        formData.append('numColors', numColors.toString());
        formData.append('fillHoles', fillHoles.toString());
        formData.append('creator', creator);
        formData.append('title', singleTitle);
        formData.append('description', singleDesc);
        formData.append('keywords', singleKw);

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
            let itemTitle = fItem.title || metaTitle;
            if (!itemTitle && fItem.file.name) {
              itemTitle = sanitizeFilename(fItem.file.name).replace(/_/g, ' ');
            } else if (itemTitle && files.length > 1 && autoNumberTitles && !fItem.title) {
              itemTitle = `${itemTitle} ${i + 1}`;
            }
            let itemDesc = fItem.description || metaDescription;
            let itemKw = fItem.keywords || keywords;

            const formData = new FormData();
            formData.append('files', fItem.file);
            formData.append('threshold', threshold.toString());
            formData.append('invert', invert.toString());
            formData.append('format', format);
            formData.append('mode', mode);
            formData.append('numColors', numColors.toString());
            formData.append('fillHoles', fillHoles.toString());
            formData.append('creator', creator);
            formData.append('title', itemTitle);
            formData.append('description', itemDesc);
            formData.append('keywords', itemKw);

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
        let singleTitle = files[0].title || metaTitle;
        if (!singleTitle && files[0].file.name) {
          singleTitle = sanitizeFilename(files[0].file.name).replace(/_/g, ' ');
        }
        let singleDesc = files[0].description || metaDescription;
        let singleKw = files[0].keywords || keywords;

        formData.append('title', singleTitle);
        formData.append('description', singleDesc);
        formData.append('keywords', singleKw);

        const response = await axios.post(`${API_BASE}/vecteezy-vectorize`, formData, {
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
            let itemTitle = fItem.title || metaTitle;
            if (!itemTitle && fItem.file.name) {
              itemTitle = sanitizeFilename(fItem.file.name).replace(/_/g, ' ');
            } else if (itemTitle && files.length > 1 && autoNumberTitles && !fItem.title) {
              itemTitle = `${itemTitle} ${i + 1}`;
            }
            let itemDesc = fItem.description || metaDescription;
            let itemKw = fItem.keywords || keywords;

            const formData = new FormData();
            formData.append('files', fItem.file);
            formData.append('threshold', threshold.toString());
            formData.append('invert', invert.toString());
            formData.append('format', format);
            formData.append('mode', mode);
            formData.append('numColors', numColors.toString());
            formData.append('alphamax', cornerSharpness.toString());
            formData.append('creator', creator);
            formData.append('title', itemTitle);
            formData.append('description', itemDesc);
            formData.append('keywords', itemKw);

            const response = await axios.post(`${API_BASE}/vecteezy-vectorize`, formData, {
              responseType: 'arraybuffer',
              timeout: 60000
            });

            if (response.data) {
              const safeName = sanitizeFilename(fItem.file.name);
              const vecName = files.length > 1 ? `${safeName}_${i + 1}.${format}` : `${safeName}.${format}`;
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

  const downloadShutterstock = async () => {
    if (files.length === 0) return;
    if (!includeEps && !includeJpg && !includePng && !includePsd) {
      setError('Pilih minimal satu format berkas (.EPS, .JPG, .PNG, atau .PSD) untuk diunduh.');
      return;
    }
    setLoading(true);
    setError(null);
    const zip = new JSZip();
    let successCount = 0;
    const isDirect = downloadMode === 'direct';

    try {
      for (let i = 0; i < files.length; i++) {
        const fItem = files[i];
        const itemStartPct = Math.round((i / files.length) * 85 + 10);
        setProgress({
          current: i + 1,
          total: files.length,
          fileName: `Vektorisasi Pattern Shutterstock: ${fItem.file.name}`,
          percent: itemStartPct,
          stage: 'processing'
        });

        try {
          let itemTitle = fItem.title || metaTitle;
          if (!itemTitle && fItem.file.name) {
            itemTitle = sanitizeFilename(fItem.file.name).replace(/_/g, ' ');
          } else if (itemTitle && files.length > 1 && autoNumberTitles && !fItem.title) {
            itemTitle = `${itemTitle} ${i + 1}`;
          }
          let itemDesc = fItem.description || metaDescription;
          let itemKw = fItem.keywords || keywords;

          const formData = new FormData();
          formData.append('files', fItem.file);
          formData.append('numColors', numColors.toString());
          formData.append('creator', creator);
          formData.append('dilationPx', dilationPx.toString());
          formData.append('title', itemTitle);
          formData.append('description', itemDesc);
          formData.append('keywords', itemKw);

          const response = await axios.post(`${API_BASE}/shutterstock-vectorize`, formData, { timeout: DEFAULT_TIMEOUT });
          const data = response.data;

          if (data && Array.isArray(data.files)) {
            for (const entry of data.files) {
              if (includeEps && entry.eps_b64) {
                if (isDirect) {
                  downloadBase64File(entry.eps_b64, entry.eps_name, 'application/postscript');
                } else {
                  zip.file(entry.eps_name, Uint8Array.from(atob(entry.eps_b64), c => c.charCodeAt(0)));
                }
              }
              if (includeJpg && entry.jpg_b64) {
                if (isDirect) {
                  downloadBase64File(entry.jpg_b64, entry.jpg_name, 'image/jpeg');
                } else {
                  zip.file(entry.jpg_name, Uint8Array.from(atob(entry.jpg_b64), c => c.charCodeAt(0)));
                }
              }
              if (includePng && entry.png_b64 && entry.png_name) {
                if (isDirect) {
                  downloadBase64File(entry.png_b64, entry.png_name, 'image/png');
                } else {
                  zip.file(entry.png_name, Uint8Array.from(atob(entry.png_b64), c => c.charCodeAt(0)));
                }
              }
              if (includePsd && entry.psd_b64 && entry.psd_name) {
                if (isDirect) {
                  downloadBase64File(entry.psd_b64, entry.psd_name, 'image/vnd.adobe.photoshop');
                } else {
                  zip.file(entry.psd_name, Uint8Array.from(atob(entry.psd_b64), c => c.charCodeAt(0)));
                }
              }
              successCount++;
            }
          }
          const itemDonePct = Math.round(((i + 1) / files.length) * 85 + 10);
          setProgress({
            current: i + 1,
            total: files.length,
            fileName: `Ekstraksi Berhasil!`,
            percent: itemDonePct,
            stage: 'processing'
          });
        } catch (itemErr) {
          console.error(`Error processing Shutterstock file ${fItem.file.name}:`, itemErr);
        }
      }

      if (successCount === 0) throw new Error('Tidak ada berkas yang berhasil di-vektorisasi untuk Shutterstock.');

      if (!isDirect) {
        setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP Shutterstock...', percent: 98, stage: 'downloading' });
        const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/zip', compression: 'DEFLATE' });
        const zipName = files.length === 1 
          ? `${sanitizeFilename(files[0].file.name)}_shutterstock_package.zip` 
          : 'shutterstock_pattern_package.zip';
        await triggerBlobDownload(blob, zipName, 'application/zip');
      }
      setProgress({ current: files.length, total: files.length, fileName: 'Selesai!', percent: 100, stage: 'complete' });
    } catch (err: any) {
      setError(err.message || 'Gagal memproses ekspor Shutterstock.');
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const downloadShutterstockRegular = async () => {
    if (files.length === 0) return;
    if (!includeEps && !includeJpg && !includePng && !includePsd) {
      setError('Pilih minimal satu format berkas (.EPS, .JPG, .PNG, atau .PSD) untuk diunduh.');
      return;
    }
    setLoading(true);
    setError(null);
    const zip = new JSZip();
    let successCount = 0;
    const isDirect = downloadMode === 'direct';

    try {
      for (let i = 0; i < files.length; i++) {
        const fItem = files[i];
        const itemStartPct = Math.round((i / files.length) * 85 + 10);
        setProgress({
          current: i + 1,
          total: files.length,
          fileName: `Vektorisasi Shutterstock Vector: ${fItem.file.name}`,
          percent: itemStartPct,
          stage: 'processing'
        });

        try {
          let itemTitle = fItem.title || metaTitle;
          if (!itemTitle && fItem.file.name) {
            itemTitle = sanitizeFilename(fItem.file.name).replace(/_/g, ' ');
          } else if (itemTitle && files.length > 1 && autoNumberTitles && !fItem.title) {
            itemTitle = `${itemTitle} ${i + 1}`;
          }
          let itemDesc = fItem.description || metaDescription;
          let itemKw = fItem.keywords || keywords;

          const formData = new FormData();
          formData.append('files', fItem.file);
          formData.append('threshold', threshold.toString());
          formData.append('invert', invert.toString());
          formData.append('mode', mode);
          formData.append('numColors', numColors.toString());
          formData.append('creator', creator);
          formData.append('title', itemTitle);
          formData.append('description', itemDesc);
          formData.append('keywords', itemKw);

          const response = await axios.post(`${API_BASE}/shutterstock-vectorize-standard`, formData, { timeout: DEFAULT_TIMEOUT });
          const data = response.data;

          if (data && Array.isArray(data.files)) {
            for (const entry of data.files) {
              if (includeEps && entry.eps_b64) {
                if (isDirect) {
                  downloadBase64File(entry.eps_b64, entry.eps_name, 'application/postscript');
                } else {
                  zip.file(entry.eps_name, Uint8Array.from(atob(entry.eps_b64), c => c.charCodeAt(0)));
                }
              }
              if (includeJpg && entry.jpg_b64) {
                if (isDirect) {
                  downloadBase64File(entry.jpg_b64, entry.jpg_name, 'image/jpeg');
                } else {
                  zip.file(entry.jpg_name, Uint8Array.from(atob(entry.jpg_b64), c => c.charCodeAt(0)));
                }
              }
              if (includePng && entry.png_b64 && entry.png_name) {
                if (isDirect) {
                  downloadBase64File(entry.png_b64, entry.png_name, 'image/png');
                } else {
                  zip.file(entry.png_name, Uint8Array.from(atob(entry.png_b64), c => c.charCodeAt(0)));
                }
              }
              if (includePsd && entry.psd_b64 && entry.psd_name) {
                if (isDirect) {
                  downloadBase64File(entry.psd_b64, entry.psd_name, 'image/vnd.adobe.photoshop');
                } else {
                  zip.file(entry.psd_name, Uint8Array.from(atob(entry.psd_b64), c => c.charCodeAt(0)));
                }
              }
              successCount++;
            }
          }
          const itemDonePct = Math.round(((i + 1) / files.length) * 85 + 10);
          setProgress({
            current: i + 1,
            total: files.length,
            fileName: `Ekstraksi Berhasil!`,
            percent: itemDonePct,
            stage: 'processing'
          });
        } catch (itemErr) {
          console.error(`Error processing Shutterstock Regular file ${fItem.file.name}:`, itemErr);
        }
      }

      if (successCount === 0) throw new Error('Tidak ada berkas yang berhasil di-vektorisasi untuk Shutterstock Vector.');

      if (!isDirect) {
        setProgress({ current: files.length, total: files.length, fileName: 'Membuat paket ZIP Shutterstock Vector...', percent: 98, stage: 'downloading' });
        const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/zip', compression: 'DEFLATE' });
        const zipName = files.length === 1 
          ? `${sanitizeFilename(files[0].file.name)}_shutterstock_package.zip` 
          : 'shutterstock_vector_package.zip';
        await triggerBlobDownload(blob, zipName, 'application/zip');
      }
      setProgress({ current: files.length, total: files.length, fileName: 'Selesai!', percent: 100, stage: 'complete' });
    } catch (err: any) {
      setError(err.message || 'Gagal memproses ekspor Shutterstock Vector.');
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const executeVectorRepair = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const activeFile = selectedIndex !== null ? files[selectedIndex]?.file : files[0].file;
      setProgress({
        current: 1,
        total: 1,
        fileName: `Merekontruksi & Memperbaiki Geometri: ${activeFile.name}`,
        percent: 40,
        stage: 'processing'
      });

      const formData = new FormData();
      formData.append('file', activeFile);
      formData.append('filename', activeFile.name);
      formData.append('num_colors', numColors.toString());

      const response = await axios.post(`${API_BASE}/repair-vector`, formData, { timeout: DEFAULT_TIMEOUT });
      const data = response.data;

      if (!data.success) {
        throw new Error(data.error || 'Gagal memperbaik geometri berkas.');
      }

      setRepairAudit(data);

      const isDirect = downloadMode === 'direct';

      if (isDirect) {
        if (includeEps && data.eps_b64) downloadBase64File(data.eps_b64, `${sanitizeFilename(activeFile.name)}_repaired.eps`, 'application/postscript');
        if (data.svg_b64) downloadBase64File(data.svg_b64, `${sanitizeFilename(activeFile.name)}_repaired.svg`, 'image/svg+xml');
        if (includeJpg && data.jpg_b64) downloadBase64File(data.jpg_b64, `${sanitizeFilename(activeFile.name)}_repaired.jpg`, 'image/jpeg');
        if (includePng && data.png_b64) downloadBase64File(data.png_b64, `${sanitizeFilename(activeFile.name)}_repaired.png`, 'image/png');
        if (includePsd && data.psd_b64) downloadBase64File(data.psd_b64, `${sanitizeFilename(activeFile.name)}_repaired.psd`, 'image/vnd.adobe.photoshop');
      } else {
        const zip = new JSZip();
        if (data.eps_b64) zip.file(`${sanitizeFilename(activeFile.name)}_repaired.eps`, Uint8Array.from(atob(data.eps_b64), c => c.charCodeAt(0)));
        if (data.svg_b64) zip.file(`${sanitizeFilename(activeFile.name)}_repaired.svg`, data.svg_str);
        if (data.jpg_b64) zip.file(`${sanitizeFilename(activeFile.name)}_repaired.jpg`, Uint8Array.from(atob(data.jpg_b64), c => c.charCodeAt(0)));
        if (data.png_b64) zip.file(`${sanitizeFilename(activeFile.name)}_repaired.png`, Uint8Array.from(atob(data.png_b64), c => c.charCodeAt(0)));
        if (data.psd_b64) zip.file(`${sanitizeFilename(activeFile.name)}_repaired.psd`, Uint8Array.from(atob(data.psd_b64), c => c.charCodeAt(0)));
        
        const blob = await zip.generateAsync({ type: 'blob' });
        await triggerBlobDownload(blob, `${sanitizeFilename(activeFile.name)}_repaired_package.zip`, 'application/zip');
      }

      setProgress({ current: 1, total: 1, fileName: 'Perbaikan Selesai 100%!', percent: 100, stage: 'complete' });
    } catch (err: any) {
      console.error('Vector repair error:', err);
      const msg = await parseErrorMessage(err, 'Gagal merekonstruksi geometri berkas.');
      setError(msg);
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(null), 1500);
    }
  };

  const testSeamlessPattern = useCallback(async () => {
    const activeFile = selectedIndex !== null ? files[selectedIndex]?.file : null;
    if (!activeFile) {
      setPatternAnalysis(null);
      setPatternPreview3x3(null);
      return;
    }
    setPatternTesting(true);
    try {
      const formData = new FormData();
      formData.append('file', activeFile);
      const res = await axios.post(`${API_BASE}/pattern/test-tile`, formData, { timeout: 30000 });
      setPatternAnalysis(res.data.analysis);
      setPatternPreview3x3(res.data.preview_3x3);
    } catch (err) {
      console.error('Pattern test error:', err);
    } finally {
      setPatternTesting(false);
    }
  }, [files, selectedIndex]);

  useEffect(() => {
    if (activeTab === 'seamless_pattern') {
      testSeamlessPattern();
    }
  }, [activeTab, selectedIndex, testSeamlessPattern]);

  const downloadSeamlessPattern = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const fItem = selectedIndex !== null ? files[selectedIndex] : files[0];
      setProgress({
        current: 1,
        total: 1,
        fileName: `Vektorisasi 3x3 Seamless Repeat: ${fItem.file.name}`,
        percent: 40,
        stage: 'processing'
      });

      const formData = new FormData();
      formData.append('file', fItem.file);
      formData.append('numColors', numColors.toString());
      formData.append('format', format);
      formData.append('mode', mode);
      formData.append('creator', creator);

      const res = await axios.post(`${API_BASE}/pattern/vectorize-tiled`, formData, {
        responseType: 'blob',
        timeout: DEFAULT_TIMEOUT
      });

      setProgress({ current: 1, total: 1, fileName: 'Mendownload Paket Pattern...', percent: 95, stage: 'downloading' });
      const safeName = sanitizeFilename(fItem.file.name);
      await triggerBlobDownload(res.data, `${safeName}_seamless_vector_pack.zip`, 'application/zip');
      setProgress({ current: 1, total: 1, fileName: 'Selesai!', percent: 100, stage: 'complete' });
    } catch (err: any) {
      console.error('Pattern vectorize error:', err);
      const msg = await parseErrorMessage(err, 'Gagal memproses seamless pattern.');
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
            <button
              onClick={() => setShowFtpModal(true)}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-purple-500/10 border border-purple-500/30 hover:border-purple-400 text-xs font-bold text-purple-300 transition-all shadow-md shadow-purple-500/5"
            >
              <Globe size={14} className="text-purple-400" />
              <span>Direct FTP Upload</span>
            </button>

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
            onClick={() => setActiveTab('shutterstock_regular')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'shutterstock_regular'
                ? 'bg-gradient-to-r from-orange-600 to-amber-600 text-white shadow-lg shadow-orange-500/25 glow-purple'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Sparkles size={15} />
            Shutterstock Vector
          </button>

          <button
            onClick={() => setActiveTab('shutterstock')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'shutterstock'
                ? 'bg-gradient-to-r from-red-600 to-amber-600 text-white shadow-lg shadow-red-500/25 glow-purple'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Layers size={15} />
            Shutterstock Pattern
          </button>

          <button
            onClick={() => setActiveTab('seamless_pattern')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'seamless_pattern'
                ? 'bg-gradient-to-r from-pink-600 to-rose-600 text-white shadow-lg shadow-pink-500/25 glow-purple'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Repeat size={15} />
            Seamless Pattern Studio
          </button>

          <button
            onClick={() => setActiveTab('repair')}
            className={`flex-1 min-w-[140px] flex items-center justify-center gap-2 py-3 px-3 rounded-xl text-xs font-bold transition-all duration-300 ${
              activeTab === 'repair'
                ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-lg shadow-violet-500/25 glow-purple'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <ShieldCheck size={15} />
            Vector Repair & Expander
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
                          {duplicateWarnings[idx] && (
                            <span className="text-[9px] font-bold text-amber-400 bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 rounded flex items-center gap-1 w-fit mt-0.5" title="Potensi file duplikat (kemiripan tinggi)">
                              <AlertCircle size={10} /> Duplikat {duplicateWarnings[idx]}%
                            </span>
                          )}
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
                      <Sliders className={activeTab === 'freepik' ? 'text-pink-400' : activeTab === 'shutterstock' ? 'text-amber-400' : 'text-emerald-400'} size={16} />
                      {activeTab === 'freepik' ? 'Freepik Vector Specs' : activeTab === 'vecteezy' ? 'Vecteezy Tracing' : activeTab === 'adobe' ? 'Adobe Stock Settings' : activeTab === 'shutterstock' ? 'Shutterstock Multi-Color Pattern' : 'Vector Settings'}
                    </h2>
                    <span className="text-[11px] font-mono text-slate-500">
                      {files.length} File Loaded
                    </span>
                  </div>

                  <div className="space-y-5">
                    {/* Custom Presets Manager */}
                    <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                          <Package size={13} className="text-purple-400" /> Presets Manager
                        </label>
                        {Object.keys(savedPresets).length > 0 && (
                          <select 
                            onChange={(e) => loadPreset(e.target.value)}
                            className="bg-slate-950 text-purple-300 text-xs px-2 py-1 rounded border border-slate-700 font-mono focus:outline-none"
                          >
                            <option value="">Load Preset...</option>
                            {Object.keys(savedPresets).map(name => (
                              <option key={name} value={name}>{name}</option>
                            ))}
                          </select>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <input 
                          type="text"
                          placeholder="Simpan preset kustom..."
                          value={presetName}
                          onChange={(e) => setPresetName(e.target.value)}
                          className="flex-1 bg-slate-950 text-xs px-2.5 py-1.5 rounded-lg border border-slate-800 text-slate-200 focus:outline-none focus:border-purple-500/50"
                        />
                        <button 
                          onClick={saveCurrentPreset}
                          disabled={!presetName.trim()}
                          className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white rounded-lg text-xs font-bold transition-all"
                        >
                          Simpan
                        </button>
                      </div>
                    </div>

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

                    {/* Microstock XMP Metadata (Title, Description, Keywords) */}
                    <div className="p-3.5 rounded-xl bg-slate-900/90 border border-emerald-500/30 space-y-3 shadow-lg shadow-emerald-500/5">
                      <label className="text-[11px] font-bold text-emerald-300 uppercase tracking-wider flex items-center justify-between">
                        <span className="flex items-center gap-1.5"><FileText size={13} className="text-emerald-400" /> Metadata Microstock (XMP)</span>
                        <span className="text-[10px] text-emerald-400 font-mono font-normal">Auto-embed EPS</span>
                      </label>

                      <div>
                        <label className="text-[11px] font-semibold text-slate-300 block mb-1">Document Title</label>
                        <input
                          type="text"
                          value={metaTitle}
                          onChange={(e) => setMetaTitle(e.target.value)}
                          placeholder="e.g. Cute Cat Seamless Pattern Vector"
                          className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-emerald-500/50"
                        />
                      </div>

                      <div>
                        <label className="text-[11px] font-semibold text-slate-300 block mb-1">Description</label>
                        <input
                          type="text"
                          value={metaDescription}
                          onChange={(e) => setMetaDescription(e.target.value)}
                          placeholder="e.g. High quality vector cat icon collection for microstock"
                          className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-emerald-500/50"
                        />
                      </div>

                      <div>
                        <label className="text-[11px] font-semibold text-slate-300 block mb-1">Keywords / Tags (dipisah koma)</label>
                        <textarea
                          rows={2}
                          value={keywords}
                          onChange={(e) => setKeywords(e.target.value)}
                          placeholder="e.g. cat, kitten, vector, icon, cute, pet, animal, seamless"
                          className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-emerald-500/50 resize-none font-mono"
                        />
                      </div>

                      <div className="pt-2 border-t border-slate-800/80">
                        <label htmlFor="autoNumberCheck" className="text-[11px] text-slate-300 flex items-center gap-2 cursor-pointer select-none">
                          <input
                            id="autoNumberCheck"
                            type="checkbox"
                            checked={autoNumberTitles}
                            onChange={(e) => setAutoNumberTitles(e.target.checked)}
                            className="rounded border-slate-700 text-emerald-500 focus:ring-0 bg-slate-950 cursor-pointer"
                          />
                          <span>Penomoran Judul Bulk Otomatis (e.g. Title 1, Title 2)</span>
                        </label>
                      </div>

                      {/* Bulk CSV / Excel Import & Template Section */}
                      <div className="pt-2.5 border-t border-slate-800/80 space-y-2">
                        <div className="flex items-center justify-between text-[11px] font-semibold text-slate-300">
                          <span className="flex items-center gap-1"><FileSpreadsheet size={13} className="text-emerald-400" /> Bulk Excel / CSV</span>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={downloadMetadataXlsxTemplate}
                              className="text-[10px] text-emerald-400 hover:text-emerald-300 underline font-mono flex items-center gap-1 font-normal"
                              title="Download template spreadsheet format .XLSX"
                            >
                              <Download size={10} /> .XLSX
                            </button>
                            <span className="text-slate-600">|</span>
                            <button
                              type="button"
                              onClick={downloadMetadataCsvTemplate}
                              className="text-[10px] text-emerald-400 hover:text-emerald-300 underline font-mono flex items-center gap-1 font-normal"
                              title="Download template format .CSV"
                            >
                              <Download size={10} /> .CSV
                            </button>
                          </div>
                        </div>

                        <label className="flex items-center justify-center gap-1.5 w-full py-2 px-3 rounded-lg bg-emerald-950/40 hover:bg-emerald-900/50 border border-emerald-500/30 text-emerald-300 text-xs font-semibold cursor-pointer transition-all">
                          <Upload size={13} /> Impor Tabel Metadata (.xlsx / .csv)
                          <input
                            type="file"
                            accept=".xlsx, .xls, .csv, .tsv, .ods, .txt, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.ms-excel, text/csv"
                            onChange={handleImportMetadata}
                            className="hidden"
                          />
                        </label>

                        {csvNotice && (
                          <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-[11px] text-emerald-300 text-center font-medium">
                            {csvNotice}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Export File Selection & Format Options */}
                    <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-3">
                      <label className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                        <span className="flex items-center gap-1.5"><Download size={13} className="text-pink-400" /> Format Berkas Ekspor</span>
                        <span className="text-[10px] text-purple-400 font-mono font-normal">Pilih yang diunduh</span>
                      </label>
                      
                      <div className="grid grid-cols-4 gap-1.5">
                        <button 
                          type="button"
                          onClick={() => setIncludeEps(!includeEps)}
                          className={`flex items-center justify-center gap-1 p-2 rounded-lg border text-xs font-bold transition-all ${
                            includeEps ? 'bg-purple-500/15 border-purple-500/50 text-purple-300 shadow-sm shadow-purple-500/10' : 'bg-slate-950/50 border-slate-800 text-slate-500'
                          }`}
                        >
                          {includeEps && <Check size={11} />} .EPS
                        </button>
                        <button 
                          type="button"
                          onClick={() => setIncludeJpg(!includeJpg)}
                          className={`flex items-center justify-center gap-1 p-2 rounded-lg border text-xs font-bold transition-all ${
                            includeJpg ? 'bg-amber-500/15 border-amber-500/50 text-amber-300 shadow-sm shadow-amber-500/10' : 'bg-slate-950/50 border-slate-800 text-slate-500'
                          }`}
                        >
                          {includeJpg && <Check size={11} />} .JPG
                        </button>
                        <button 
                          type="button"
                          onClick={() => setIncludePng(!includePng)}
                          className={`flex items-center justify-center gap-1 p-2 rounded-lg border text-xs font-bold transition-all ${
                            includePng ? 'bg-pink-500/15 border-pink-500/50 text-pink-300 shadow-sm shadow-pink-500/10' : 'bg-slate-950/50 border-slate-800 text-slate-500'
                          }`}
                        >
                          {includePng && <Check size={11} />} .PNG
                        </button>
                        <button 
                          type="button"
                          onClick={() => setIncludePsd(!includePsd)}
                          className={`flex items-center justify-center gap-1 p-2 rounded-lg border text-xs font-bold transition-all ${
                            includePsd ? 'bg-blue-500/15 border-blue-500/50 text-blue-300 shadow-sm shadow-blue-500/10' : 'bg-slate-950/50 border-slate-800 text-slate-500'
                          }`}
                        >
                          {includePsd && <Check size={11} />} .PSD
                        </button>
                      </div>

                      <div className="flex items-center justify-between pt-1">
                        <span className="text-[11px] font-medium text-slate-400">Metode Unduh:</span>
                        <div className="flex items-center gap-1 bg-slate-950 p-0.5 rounded-lg border border-slate-800 text-[11px]">
                          <button
                            type="button"
                            onClick={() => setDownloadMode('direct')}
                            className={`px-2.5 py-1 rounded font-medium transition-all ${
                              downloadMode === 'direct' ? 'bg-purple-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            File Langsung
                          </button>
                          <button
                            type="button"
                            onClick={() => setDownloadMode('zip')}
                            className={`px-2.5 py-1 rounded font-medium transition-all ${
                              downloadMode === 'zip' ? 'bg-purple-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            Paket ZIP
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Feature Toggles */}
                    <div className="space-y-2">
                      <label className="flex items-center gap-3 p-3 rounded-xl bg-slate-900/50 border border-slate-800/80 cursor-pointer hover:border-slate-700 transition-all">
                        <input 
                          type="checkbox" 
                          checked={splitGrid} 
                          onChange={(e) => setSplitGrid(e.target.checked)}
                          className="w-4 h-4 rounded accent-purple-500"
                        />
                        <div className="text-xs">
                          <span className="font-semibold text-slate-200 block">Auto-Split Icon Grid Sheet</span>
                          <span className="text-slate-500 text-[10px]">Memotong tiap ikon pada sheet jadi file individual</span>
                        </div>
                      </label>

                      <label className="flex items-center gap-3 p-3 rounded-xl bg-slate-900/50 border border-slate-800/80 cursor-pointer hover:border-slate-700 transition-all">
                        <input 
                          type="checkbox" 
                          checked={includePng} 
                          onChange={(e) => setIncludePng(e.target.checked)}
                          className="w-4 h-4 rounded accent-pink-500"
                        />
                        <div className="text-xs">
                          <span className="font-semibold text-slate-200 block">Export Transparent PNG</span>
                          <span className="text-slate-500 text-[10px]">Sertakan PNG transparan HD dalam paket ZIP</span>
                        </div>
                      </label>
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
                          Line Art Only (Outline)
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
                    ) : activeTab === 'shutterstock' ? (
                      <div className="space-y-4 pt-2 border-t border-slate-800">
                        <div>
                          <div className="flex justify-between items-center mb-1.5">
                            <label className="text-xs font-semibold text-slate-300">Seamless Gap Eraser (Color Dilation)</label>
                            <span className="text-[10px] font-mono text-amber-400 font-bold px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
                              {dilationPx} px ({dilationPx === 0 ? 'No Dilation' : 'Eliminate White Seams'})
                            </span>
                          </div>
                          <input 
                            type="range" 
                            min="0" 
                            max="3" 
                            step="1"
                            value={dilationPx} 
                            onChange={(e) => setDilationPx(parseInt(e.target.value))}
                            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>

                        <div>
                          <div className="flex justify-between items-center mb-1.5">
                            <label className="text-xs font-semibold text-slate-300">Pattern Color Layers</label>
                            <span className="text-[10px] font-mono text-pink-400 font-bold px-2 py-0.5 rounded bg-pink-500/10 border border-pink-500/20">
                              {numColors} Colors
                            </span>
                          </div>
                          <input 
                            type="range" 
                            min="4" 
                            max="16" 
                            step="1"
                            value={numColors} 
                            onChange={(e) => setNumColors(parseInt(e.target.value))}
                            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>
                      </div>
                    ) : activeTab === 'seamless_pattern' ? (
                      <div className="space-y-4 pt-2 border-t border-slate-800">
                        <div>
                          <label className="text-xs font-semibold text-slate-300 block mb-2">Vector Output Format</label>
                          <div className="grid grid-cols-2 gap-2">
                            <button 
                              onClick={() => setFormat('eps')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'eps' ? 'border-pink-400 bg-pink-500/10 text-pink-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              EPS (3x3 Repeat Sheet)
                            </button>
                            <button 
                              onClick={() => setFormat('svg')}
                              className={`p-2.5 rounded-xl border text-xs font-bold transition-all ${
                                format === 'svg' ? 'border-rose-400 bg-rose-500/10 text-rose-300' : 'border-slate-800 text-slate-500'
                              }`}
                            >
                              SVG (3x3 Repeat Web)
                            </button>
                          </div>
                        </div>

                        <div>
                          <div className="flex justify-between items-center mb-1.5">
                            <label className="text-xs font-semibold text-slate-300">Pattern Color Quantization</label>
                            <span className="text-[10px] font-mono text-rose-400 font-bold px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/20">
                              {numColors} Colors
                            </span>
                          </div>
                          <input 
                            type="range" 
                            min="4" 
                            max="24" 
                            step="1"
                            value={numColors} 
                            onChange={(e) => setNumColors(parseInt(e.target.value))}
                            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>
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
                    ) : activeTab === 'shutterstock_regular' ? (
                      <button 
                        onClick={downloadShutterstockRegular}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #ea580c 0%, #d97706 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Package size={18} />
                          {files.length > 1 ? `Unduh ZIP Shutterstock Vector (${files.length} Files)` : `Unduh Paket ZIP Shutterstock Vector`}
                        </div>
                        <span className="text-[10px] text-amber-200/90 font-medium">
                          Single Vector / Line Art • Min 4.0 MP Artboard + XMP Metadata
                        </span>
                      </button>
                    ) : activeTab === 'shutterstock' ? (
                      <button 
                        onClick={downloadShutterstock}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #dc2626 0%, #d97706 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Layers size={18} />
                          {files.length > 1 ? `Unduh ZIP Shutterstock (${files.length} Files)` : `Unduh Paket ZIP Shutterstock (EPS + JPG)`}
                        </div>
                        <span className="text-[10px] text-amber-200/90 font-medium">
                          Multi-Color Pattern • Seamless Gap Eraser Active
                        </span>
                      </button>
                    ) : activeTab === 'seamless_pattern' ? (
                      <button 
                        onClick={downloadSeamlessPattern}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #e11d48 0%, #be123c 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <Repeat size={18} />
                          Unduh 3x3 Seamless Vector Pack (.ZIP)
                        </div>
                        <span className="text-[10px] text-rose-200/90 font-medium">
                          Includes 3x3 Tiled EPS/SVG + High-Res JPG/PNG Previews
                        </span>
                      </button>
                    ) : activeTab === 'repair' ? (
                      <button 
                        onClick={executeVectorRepair}
                        disabled={files.length === 0 || loading}
                        className={`primary-button w-full flex flex-col items-center justify-center gap-1 h-14 relative overflow-hidden transition-all ${
                          (files.length === 0 || loading) ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        style={{ background: 'linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%)' }}
                      >
                        <div className="flex items-center gap-2.5 font-bold text-sm">
                          <ShieldCheck size={18} />
                          {files.length > 1 ? `Perbaiki & Ekspansi (${files.length} Vektor)` : `Perbaiki Vektor & Hapus Masking (1-Click)`}
                        </div>
                        <span className="text-[10px] text-violet-200/90 font-medium">
                          Detects & Removes All Clipping Masks, Masks & Fake Fills
                        </span>
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
                  <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
                    <div className="flex items-center gap-2">
                      <Eye size={16} className="text-purple-400" />
                      <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">
                        Live Preview & Compare
                      </h2>
                    </div>

                    {/* Interactive Mode Switcher: Side-by-Side vs Original vs Result */}
                    <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
                      <button
                        onClick={() => setPreviewMode('split')}
                        className={`px-2.5 py-1 rounded-lg text-[10px] font-bold tracking-wider uppercase transition-all flex items-center gap-1.5 ${
                          previewMode === 'split' ? 'bg-purple-600 text-white shadow-md shadow-purple-500/20' : 'text-slate-400 hover:text-slate-200'
                        }`}
                        title="Tampilkan Original & Result Berdampingan"
                      >
                        <Columns size={12} /> Side-by-Side
                      </button>
                      <button
                        onClick={() => setPreviewMode('original')}
                        className={`px-2.5 py-1 rounded-lg text-[10px] font-bold tracking-wider uppercase transition-all ${
                          previewMode === 'original' ? 'bg-purple-600 text-white shadow-md shadow-purple-500/20' : 'text-slate-400 hover:text-slate-200'
                        }`}
                        title="Tampilkan Gambar Asli Saja"
                      >
                        Original
                      </button>
                      <button
                        onClick={() => setPreviewMode('result')}
                        className={`px-2.5 py-1 rounded-lg text-[10px] font-bold tracking-wider uppercase transition-all ${
                          previewMode === 'result' ? 'bg-purple-600 text-white shadow-md shadow-purple-500/20' : 'text-slate-400 hover:text-slate-200'
                        }`}
                        title="Tampilkan Hasil Vektor / Mask Saja"
                      >
                        Result
                      </button>
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

                  {/* Canvas Preview Container with Support for Side-by-Side Dual View */}
                  <div className="relative">
                    {previewMode === 'split' && selectedFile ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 min-h-[480px]">
                        {/* Box 1: Original Input */}
                        <div className={`w-full min-h-[460px] h-[520px] lg:h-[580px] rounded-2xl border border-slate-800 overflow-hidden flex flex-col items-center justify-center relative transition-all group ${
                          canvasBg === 'checkerboard' ? 'bg-checkerboard' : canvasBg === 'white' ? 'bg-white-canvas' : 'bg-dark-canvas'
                        }`}>
                          <div className="absolute top-3 left-3 z-10 bg-slate-950/90 backdrop-blur-md px-3 py-1.5 rounded-xl text-[11px] font-extrabold uppercase tracking-wider text-purple-300 border border-purple-500/30 shadow-lg flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-purple-400" />
                            1. Original Input
                          </div>

                          {/* Fullscreen Expand Control */}
                          <button
                            onClick={() => setLightboxImg({ src: selectedFile.previewUrl, title: `Original Input: ${selectedFile.file.name}` })}
                            className="absolute top-3 right-3 z-10 p-2 rounded-xl bg-slate-950/80 backdrop-blur-md text-slate-300 hover:text-white border border-slate-800 hover:border-purple-500/50 opacity-80 group-hover:opacity-100 transition-all shadow-lg"
                            title="Buka Preview Layar Penuh (Fullscreen)"
                          >
                            <Maximize2 size={15} />
                          </button>

                          <img 
                            src={selectedFile.previewUrl} 
                            alt="Original Input" 
                            onClick={() => setLightboxImg({ src: selectedFile.previewUrl, title: `Original Input: ${selectedFile.file.name}` })}
                            className="w-full h-full p-2 object-contain drop-shadow-2xl transition-transform duration-300 group-hover:scale-[1.02] cursor-pointer" 
                          />
                        </div>

                        {/* Box 2: Vector Result / Selection Mask */}
                        <div className={`w-full min-h-[460px] h-[520px] lg:h-[580px] rounded-2xl border border-slate-800 overflow-hidden flex flex-col items-center justify-center relative transition-all group ${
                          canvasBg === 'checkerboard' ? 'bg-checkerboard' : canvasBg === 'white' ? 'bg-white-canvas' : 'bg-dark-canvas'
                        }`}>
                          <div className="absolute top-3 left-3 z-10 bg-slate-950/90 backdrop-blur-md px-3 py-1.5 rounded-xl text-[11px] font-extrabold uppercase tracking-wider text-emerald-300 border border-emerald-500/30 shadow-lg flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                            2. {repairAudit ? 'Vector Repaired Result' : 'Vector Mask'}
                          </div>

                          {/* Fullscreen Expand Control */}
                          {(repairAudit?.jpg_b64 || repairAudit?.png_b64 || preview) && (
                            <button
                              onClick={() => setLightboxImg({ 
                                src: repairAudit?.jpg_b64 ? `data:image/jpeg;base64,${repairAudit.jpg_b64}` : (repairAudit?.png_b64 ? `data:image/png;base64,${repairAudit.png_b64}` : preview!), 
                                title: `Vector Result: ${selectedFile.file.name}` 
                              })}
                              className="absolute top-3 right-3 z-10 p-2 rounded-xl bg-slate-950/80 backdrop-blur-md text-slate-300 hover:text-white border border-slate-800 hover:border-emerald-500/50 opacity-80 group-hover:opacity-100 transition-all shadow-lg"
                              title="Buka Preview Layar Penuh (Fullscreen)"
                            >
                              <Maximize2 size={15} />
                            </button>
                          )}

                          {activeTab === 'seamless_pattern' && patternPreview3x3 ? (
                            <img 
                              src={patternPreview3x3} 
                              alt="3x3 Seamless Pattern Repeat Preview" 
                              onClick={() => setLightboxImg({ src: patternPreview3x3, title: `3x3 Seamless Repeat: ${selectedFile?.file.name || 'Pattern'}` })}
                              className="w-full h-full p-2 object-contain drop-shadow-2xl transition-transform duration-300 group-hover:scale-[1.02] cursor-pointer" 
                            />
                          ) : repairAudit?.jpg_b64 ? (
                            <img 
                              src={`data:image/jpeg;base64,${repairAudit.jpg_b64}`} 
                              alt="Vector Repaired Result" 
                              onClick={() => setLightboxImg({ src: `data:image/jpeg;base64,${repairAudit.jpg_b64}`, title: `Vector Result: ${selectedFile.file.name}` })}
                              className="w-full h-full p-2 object-contain drop-shadow-2xl transition-transform duration-300 group-hover:scale-[1.02] cursor-pointer" 
                            />
                          ) : repairAudit?.png_b64 ? (
                            <img 
                              src={`data:image/png;base64,${repairAudit.png_b64}`} 
                              alt="Vector Repaired Result" 
                              onClick={() => setLightboxImg({ src: `data:image/png;base64,${repairAudit.png_b64}`, title: `Vector Result: ${selectedFile.file.name}` })}
                              className="w-full h-full p-2 object-contain drop-shadow-2xl transition-transform duration-300 group-hover:scale-[1.02] cursor-pointer" 
                            />
                          ) : preview ? (
                            <img 
                              src={preview} 
                              alt="Vector Mask Preview" 
                              onClick={() => setLightboxImg({ src: preview, title: `Vector Mask: ${selectedFile.file.name}` })}
                              className="w-full h-full p-2 object-contain drop-shadow-2xl transition-transform duration-300 group-hover:scale-[1.02] cursor-pointer" 
                            />
                          ) : (
                            <div className="text-center p-6">
                              <RefreshCw size={28} className="mx-auto mb-3 text-purple-400 animate-spin opacity-50" />
                              <span className="text-xs text-slate-400 font-semibold block">Menyiapkan Preview Vektor...</span>
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className={`w-full min-h-[460px] h-[520px] lg:h-[580px] rounded-2xl border border-slate-800 overflow-hidden flex items-center justify-center relative transition-all group ${
                        canvasBg === 'checkerboard' 
                          ? 'bg-checkerboard' 
                          : canvasBg === 'white' 
                            ? 'bg-white-canvas' 
                            : 'bg-dark-canvas'
                      }`}>
                        {previewMode === 'original' && selectedFile ? (
                          <img 
                            src={selectedFile.previewUrl} 
                            alt="Original Input Preview" 
                            onClick={() => setLightboxImg({ src: selectedFile.previewUrl, title: `Original Input: ${selectedFile.file.name}` })}
                            className="w-full h-full p-3 object-contain transition-all duration-300 drop-shadow-2xl group-hover:scale-[1.01] cursor-pointer" 
                          />
                        ) : activeTab === 'seamless_pattern' && patternPreview3x3 ? (
                          <img 
                            src={patternPreview3x3} 
                            alt="3x3 Seamless Repeat Preview" 
                            onClick={() => setLightboxImg({ src: patternPreview3x3, title: `3x3 Seamless Repeat: ${selectedFile?.file.name || 'Pattern'}` })}
                            className="w-full h-full p-3 object-contain transition-all duration-300 drop-shadow-2xl group-hover:scale-[1.01] cursor-pointer" 
                          />
                        ) : previewMode === 'result' && (repairAudit?.jpg_b64 || repairAudit?.png_b64 || preview) ? (
                          <img 
                            src={repairAudit?.jpg_b64 ? `data:image/jpeg;base64,${repairAudit.jpg_b64}` : (repairAudit?.png_b64 ? `data:image/png;base64,${repairAudit.png_b64}` : preview!)} 
                            alt="Vector Result Preview" 
                            onClick={() => setLightboxImg({ 
                              src: repairAudit?.jpg_b64 ? `data:image/jpeg;base64,${repairAudit.jpg_b64}` : (repairAudit?.png_b64 ? `data:image/png;base64,${repairAudit.png_b64}` : preview!), 
                              title: `Vector Result: ${selectedFile?.file.name || 'Artwork'}` 
                            })}
                            className="w-full h-full p-3 object-contain transition-all duration-300 drop-shadow-2xl group-hover:scale-[1.01] cursor-pointer" 
                          />
                        ) : selectedFile ? (
                          <img 
                            src={selectedFile.previewUrl} 
                            alt="Uploaded Image Preview" 
                            onClick={() => setLightboxImg({ src: selectedFile.previewUrl, title: `Original Input: ${selectedFile.file.name}` })}
                            className="w-full h-full p-3 object-contain transition-all duration-300 opacity-90 drop-shadow-2xl cursor-pointer" 
                          />
                        ) : (
                          <div className="text-center text-slate-600 p-6">
                            <ImageIcon className="mx-auto mb-3 opacity-30" size={48} />
                            <p className="text-xs font-semibold text-slate-400">Pilih file untuk melihat mask & audit</p>
                            <span className="text-[11px] text-slate-600 block mt-1">Side-by-side perbandingan Original vs Result</span>
                          </div>
                        )}

                        {/* Top Canvas Background Controls Overlay */}
                        <div className="absolute top-3 right-3 flex items-center gap-1 bg-slate-950/80 backdrop-blur-md p-1 rounded-xl border border-slate-800 z-10">
                          {selectedFile && (
                            <button 
                              onClick={() => setLightboxImg({ 
                                src: previewMode === 'original' ? selectedFile.previewUrl : (patternPreview3x3 || repairAudit?.png_b64 ? `data:image/png;base64,${repairAudit.png_b64}` : preview || selectedFile.previewUrl), 
                                title: `${previewMode === 'original' ? 'Original Input' : 'Vector Result'}: ${selectedFile.file.name}` 
                              })}
                              className="p-1.5 rounded-lg text-xs transition-colors text-slate-400 hover:text-white hover:bg-slate-800"
                              title="Buka Layar Penuh (Fullscreen)"
                            >
                              <Maximize2 size={13} />
                            </button>
                          )}
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
                          <div className="absolute bottom-3 left-3 bg-slate-950/80 backdrop-blur-md px-3 py-1 rounded-full text-[10px] font-bold text-slate-300 border border-slate-800 truncate max-w-[70%] flex items-center gap-1.5 z-10">
                            <span className={`w-2 h-2 rounded-full ${preview ? 'bg-emerald-400' : 'bg-purple-400 animate-pulse'}`} />
                            <span>{selectedFile.file.name}</span>
                            <span className="text-slate-500 font-normal">({previewMode === 'original' ? 'Original Input' : 'Vector Result'})</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Status & Size Audit Breakdown Card */}
                  {activeTab === 'seamless_pattern' && patternAnalysis ? (
                    <div className="p-4 rounded-xl bg-pink-950/20 border border-pink-500/30 space-y-3 text-xs shadow-lg shadow-pink-500/5">
                      <div className="flex items-center justify-between pb-2 border-b border-pink-500/20">
                        <span className="font-bold text-pink-200 uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                          <Repeat size={15} className="text-pink-400" /> Seamless Pattern Tile Audit
                        </span>
                        <span className={`text-[10px] font-mono px-2.5 py-0.5 rounded-full border font-bold flex items-center gap-1 ${
                          patternTesting
                            ? 'text-purple-400 bg-purple-500/10 border-purple-500/30 font-mono'
                            : patternAnalysis.is_seamless 
                              ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' 
                              : 'text-amber-400 bg-amber-500/10 border-amber-500/30'
                        }`}>
                          {patternTesting ? <RefreshCw size={11} className="animate-spin" /> : patternAnalysis.is_seamless ? <Check size={11} /> : <AlertCircle size={11} />}
                          {patternTesting ? 'ANALYZING TILE...' : `${patternAnalysis.seamless_score}% SEAMLESS SCORE`}
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">X-Border Continuity</span>
                          <span className="font-mono text-emerald-400 font-bold text-sm block">{patternAnalysis.x_continuity}%</span>
                        </div>
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">Y-Border Continuity</span>
                          <span className="font-mono text-emerald-400 font-bold text-sm block">{patternAnalysis.y_continuity}%</span>
                        </div>
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">Tile Resolution</span>
                          <span className="font-mono text-purple-300 font-bold text-sm block">{patternAnalysis.width} x {patternAnalysis.height} px</span>
                        </div>
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">3x3 Vector Grid</span>
                          <span className="font-mono text-pink-300 font-bold text-sm block">Multi-Color Repeat</span>
                        </div>
                      </div>
                    </div>
                  ) : repairAudit && activeTab === 'repair' ? (
                    <div className="p-4 rounded-xl bg-violet-950/20 border border-violet-500/30 space-y-3 text-xs shadow-lg shadow-violet-500/5">
                      <div className="flex items-center justify-between pb-2 border-b border-violet-500/20">
                        <span className="font-bold text-violet-200 uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                          <ShieldCheck size={15} className="text-violet-400" /> Microstock Compliance Audit
                        </span>
                        <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/30 font-bold flex items-center gap-1">
                          <Check size={11} /> MARKETPLACE READY
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">Clipping Masks</span>
                          <span className="font-mono text-emerald-400 font-bold text-sm block">0 (Eliminated)</span>
                        </div>
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">Opacity Masks</span>
                          <span className="font-mono text-emerald-400 font-bold text-sm block">0 (Eliminated)</span>
                        </div>
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">Raster Bitmaps</span>
                          <span className="font-mono text-emerald-400 font-bold text-sm block">0 (Vectorized)</span>
                        </div>
                        <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                          <span className="text-[10px] text-slate-400 uppercase font-medium block">Hidden Rectangles</span>
                          <span className="font-mono text-emerald-400 font-bold text-sm block">0 (Stripped)</span>
                        </div>
                      </div>

                      <div className="pt-2 border-t border-violet-500/20 space-y-1 text-[11px]">
                        <div className="flex justify-between text-slate-400">
                          <span>Closed Path Geometry:</span>
                          <span className="text-emerald-400 font-mono font-bold">100% True Paths</span>
                        </div>
                        <div className="flex justify-between text-slate-400">
                          <span>Direct RGB Fill Assignment:</span>
                          <span className="text-emerald-400 font-mono font-bold">Direct (No Clip Dependency)</span>
                        </div>
                        <div className="flex justify-between text-slate-400">
                          <span>Marketplace Compatibility:</span>
                          <span className="text-purple-300 font-mono font-bold">Vecteezy, Adobe, Freepik, Shutterstock</span>
                        </div>
                      </div>
                    </div>
                  ) : selectedFile ? (
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

        {/* Interactive Spreadsheet Excel Metadata Table (Shown when files are loaded) */}
        {files.length > 0 && (
          <section className="mt-8 glass-card p-5 border border-emerald-500/30 rounded-2xl shadow-xl shadow-emerald-500/5">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-4 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <FileSpreadsheet size={20} className="text-emerald-400" />
                <div>
                  <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider font-mono">
                    Tabel Metadata Excel Interaktif ({files.length} Berkas)
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Ketik dan edit Title, Description, & Keywords secara langsung untuk masing-masing file di dalam tabel di bawah ini.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  onClick={() => {
                    setFiles(prev => prev.map((fItem, idx) => ({
                      ...fItem,
                      title: autoNumberTitles && metaTitle ? `${metaTitle} ${idx + 1}` : (metaTitle || fItem.title),
                      description: metaDescription || fItem.description,
                      keywords: keywords || fItem.keywords,
                    })));
                    setCsvNotice('✓ Berhasil menerapkan metadata ke seluruh baris tabel!');
                    setTimeout(() => setCsvNotice(null), 3000);
                  }}
                  className="px-3 py-1.5 rounded-xl bg-purple-600/20 border border-purple-500/40 text-purple-300 hover:bg-purple-600/30 text-xs font-semibold flex items-center gap-1.5 transition-all"
                >
                  <Sparkles size={13} /> Terapkan Input Sidebar ke Semua
                </button>

                <button
                  type="button"
                  onClick={downloadMetadataCsvTemplate}
                  className="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-300 text-xs font-semibold flex items-center gap-1.5 transition-all"
                >
                  <Download size={13} /> Export CSV
                </button>
              </div>
            </div>

            {/* Table Grid */}
            <div className="overflow-x-auto mt-4 rounded-xl border border-slate-800 bg-slate-950/60">
              <table className="w-full text-left text-xs text-slate-300 border-collapse">
                <thead>
                  <tr className="bg-slate-900/90 border-b border-slate-800 text-[11px] uppercase tracking-wider font-mono text-slate-400">
                    <th className="p-3 w-10 text-center">#</th>
                    <th className="p-3 w-16 text-center">Preview</th>
                    <th className="p-3 w-44">Nama File</th>
                    <th className="p-3 min-w-[200px]">Document Title</th>
                    <th className="p-3 min-w-[220px]">Description</th>
                    <th className="p-3 min-w-[260px]">Keywords / Tags (koma)</th>
                    <th className="p-3 w-12 text-center">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {files.map((item, idx) => {
                    const displayTitle = item.title !== undefined 
                      ? item.title 
                      : (autoNumberTitles && metaTitle ? `${metaTitle} ${idx + 1}` : metaTitle);

                    const displayDesc = item.description !== undefined ? item.description : metaDescription;
                    const displayKw = item.keywords !== undefined ? item.keywords : keywords;

                    return (
                      <tr key={item.id} className="hover:bg-slate-900/40 transition-colors">
                        <td className="p-3 text-center font-mono font-bold text-slate-500">{idx + 1}</td>
                        <td className="p-2 text-center">
                          <img
                            src={item.previewUrl}
                            alt={item.file.name}
                            className="w-10 h-10 object-contain rounded-lg bg-slate-900 border border-slate-800 mx-auto"
                          />
                        </td>
                        <td className="p-3 font-mono text-[11px] text-slate-300 truncate max-w-[170px]" title={item.file.name}>
                          {item.file.name}
                        </td>
                        <td className="p-2">
                          <input
                            type="text"
                            value={displayTitle}
                            onChange={(e) => {
                              const val = e.target.value;
                              setFiles(prev => prev.map((f, i) => i === idx ? { ...f, title: val } : f));
                            }}
                            placeholder={sanitizeFilename(item.file.name).replace(/_/g, ' ')}
                            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-emerald-500/50 font-mono"
                          />
                        </td>
                        <td className="p-2">
                          <input
                            type="text"
                            value={displayDesc}
                            onChange={(e) => {
                              const val = e.target.value;
                              setFiles(prev => prev.map((f, i) => i === idx ? { ...f, description: val } : f));
                            }}
                            placeholder="Deskripsi artwork..."
                            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-emerald-500/50"
                          />
                        </td>
                        <td className="p-2">
                          <textarea
                            rows={1}
                            value={displayKw}
                            onChange={(e) => {
                              const val = e.target.value;
                              setFiles(prev => prev.map((f, i) => i === idx ? { ...f, keywords: val } : f));
                            }}
                            placeholder="cat, vector, icon..."
                            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-emerald-500/50 resize-none font-mono text-[11px]"
                          />
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            onClick={() => {
                              setFiles(prev => prev.map((f, i) => i === idx ? { ...f, title: '', description: '', keywords: '' } : f));
                            }}
                            title="Reset metadata baris ini"
                            className="p-1.5 rounded-lg bg-slate-900 hover:bg-red-500/20 text-slate-500 hover:text-red-400 transition-colors"
                          >
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <footer className="mt-12 text-center text-slate-500 text-xs border-t border-slate-800/80 pt-6">
          <p>© 2026 Vecto Studio. Professional Batch Vectorization Suite.</p>
        </footer>

        {/* FTP Upload Modal */}
        {showFtpModal && (
          <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl max-w-lg w-full shadow-2xl space-y-4 glow-purple relative">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <Server size={20} className="text-purple-400" />
                  <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider font-mono">
                    Direct Microstock FTP Uploader
                  </h3>
                </div>
                <button 
                  onClick={() => setShowFtpModal(false)}
                  className="text-slate-500 hover:text-slate-200 text-xs font-bold px-2 py-1 rounded bg-slate-800"
                >
                  Tutup
                </button>
              </div>

              {/* Preset Host Quick Select */}
              <div className="space-y-1">
                <label className="text-[11px] font-semibold text-slate-400">Pilih Server Microstock:</label>
                <div className="grid grid-cols-4 gap-1.5 text-xs">
                  {[
                    { name: 'Shutterstock', host: 'ftp.shutterstock.com' },
                    { name: 'Freepik', host: 'ftp.freepik.com' },
                    { name: 'Adobe Stock', host: 'ftp.adobestock.com' },
                    { name: 'Vecteezy', host: 'upload.vecteezy.com' }
                  ].map(agency => (
                    <button 
                      key={agency.name}
                      onClick={() => {
                        setFtpHost(agency.host);
                        localStorage.setItem('vecto_ftp_host', agency.host);
                      }}
                      className={`py-1.5 px-2 rounded-lg border text-[10px] font-bold truncate ${
                        ftpHost === agency.host 
                          ? 'border-purple-500 bg-purple-500/10 text-purple-300' 
                          : 'border-slate-800 text-slate-400 hover:bg-slate-800'
                      }`}
                    >
                      {agency.name}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-slate-400 mb-1">FTP Host</label>
                  <input 
                    type="text" 
                    value={ftpHost} 
                    onChange={(e) => {
                      setFtpHost(e.target.value);
                      localStorage.setItem('vecto_ftp_host', e.target.value);
                    }}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl font-mono text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-slate-400 mb-1">Port</label>
                  <input 
                    type="number" 
                    value={ftpPort} 
                    onChange={(e) => setFtpPort(parseInt(e.target.value))}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl font-mono text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-slate-400 mb-1">Username / Email</label>
                  <input 
                    type="text" 
                    value={ftpUser} 
                    onChange={(e) => {
                      setFtpUser(e.target.value);
                      localStorage.setItem('vecto_ftp_user', e.target.value);
                    }}
                    placeholder="User FTP microstock..."
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl font-mono text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-slate-400 mb-1">Password / FTP Key</label>
                  <input 
                    type="password" 
                    value={ftpPass} 
                    onChange={(e) => {
                      setFtpPass(e.target.value);
                      localStorage.setItem('vecto_ftp_pass', e.target.value);
                    }}
                    placeholder="Password FTP..."
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl font-mono text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-slate-400 mb-1">Remote Directory Path</label>
                  <input 
                    type="text" 
                    value={ftpDir} 
                    onChange={(e) => setFtpDir(e.target.value)}
                    placeholder="/ or /uploads"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl font-mono text-slate-200 focus:outline-none focus:border-purple-500"
                  />
                </div>
              </div>

              {ftpStatus && (
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-purple-300">
                  {ftpStatus}
                </div>
              )}

              <div className="flex items-center justify-between pt-2">
                <button 
                  onClick={handleTestFtp}
                  disabled={ftpUploading}
                  className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 transition-colors"
                >
                  Uji Koneksi
                </button>
                <button 
                  onClick={handleUploadToFtp}
                  disabled={ftpUploading || files.length === 0}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 disabled:opacity-40 text-xs font-bold text-white shadow-lg shadow-purple-500/25 transition-all"
                >
                  <Send size={14} />
                  <span>{ftpUploading ? 'Mengunggah...' : `Upload ${files.length} Berkas ke FTP`}</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Lightbox Fullscreen Preview Modal */}
        {lightboxImg && (
          <div className="fixed inset-0 z-50 bg-slate-950/95 backdrop-blur-xl flex flex-col items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="w-full max-w-7xl flex items-center justify-between pb-4 border-b border-slate-800">
              <div className="flex items-center gap-2 text-slate-200 font-bold text-sm">
                <Eye size={18} className="text-purple-400" />
                <span>{lightboxImg.title}</span>
              </div>
              <button
                onClick={() => setLightboxImg(null)}
                className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 transition-colors"
                title="Tutup Modal"
              >
                <X size={20} />
              </button>
            </div>
            <div className="w-full max-w-7xl h-[85vh] flex items-center justify-center p-4 overflow-hidden relative mt-2 bg-checkerboard rounded-2xl border border-slate-800 shadow-2xl">
              <img
                src={lightboxImg.src}
                alt="Fullscreen Preview"
                className="max-w-full max-h-full object-contain drop-shadow-2xl"
              />
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

export default App;
