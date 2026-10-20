"""Mandalina - Windows icin "surukle + Shift" dosya donusturucu.

Explorer'da bir dosyayi surukle, surukleme sirasinda Shift'e bir kez bas:
imlecin etrafinda bir donusum carki acilir. Dosyayi istedigin formatin
dilimine birak; donusturulmus dosya orijinalin yanina kaydedilir.
Her sey yerelde calisir (Pillow + ffmpeg).
"""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import zipfile

from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

VK_LBUTTON, VK_SHIFT, VK_ESCAPE = 0x01, 0x10, 0x1B
WM_DROPFILES = 0x0233
WM_COPYGLOBALDATA = 0x0049
GWLP_WNDPROC = -4
DRAG_THRESHOLD = 12  # piksel
RADIUS_OUT, RADIUS_IN = 150, 48
TRANSPARENT = "#010203"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".heic", ".heif", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".m4v", ".flv"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma", ".aiff"}
PDF_EXT = {".pdf"}
WORD_EXT = {".docx", ".doc", ".rtf", ".odt", ".docm"}
EXCEL_EXT = {".xlsx", ".xls", ".xlsm", ".xlsb", ".csv", ".ods"}
SLIDES_EXT = {".pptx", ".ppt", ".odp", ".pptm"}

TARGETS = {
    "image": ["PNG", "JPG", "WEBP", "PDF", "ICO", "BMP", "TIFF", "ZIP"],
    "video": ["MP4", "MOV", "MKV", "WEBM", "GIF", "MP3", "WAV", "ZIP"],
    "audio": ["MP3", "WAV", "FLAC", "M4A", "OGG", "OPUS", "ZIP"],
    "pdf": ["DOCX", "BİRLEŞTİR", "PARÇALA", "PNG", "JPG", "TXT", "ZIP"],
    "word": ["PDF", "BİRLEŞTİR", "DOCX", "TXT", "RTF", "ODT", "ZIP"],
    "excel": ["PDF", "XLSX", "CSV", "ODS", "ZIP"],
    "slides": ["PDF", "PNG", "JPG", "PPTX", "ZIP"],
    "other": ["ZIP", "YOLU KOPYALA"],
    "unknown": ["PNG", "JPG", "PDF", "DOCX", "MP4", "MP3", "ZIP"],
}

COLORS = {"bg": "#1e1e22", "text": "#1d1d1f", "edge": "#111114", "ring": "#ff8a1f",
          "slice": "#fafafa", "line": "#d8d8dc", "hot": "#ff8a1f", "hot_text": "#ffffff",
          "hub": "#ffffff", "hub_text": "#c85a00"}


def kind_of(path):
    if os.path.isdir(path):
        return "other"
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    for kind, exts in (("pdf", PDF_EXT), ("word", WORD_EXT), ("excel", EXCEL_EXT), ("slides", SLIDES_EXT)):
        if ext in exts:
            return kind
    return "other"


def short_name(name, limit=22):
    if len(name) <= limit:
        return name
    stem, ext = os.path.splitext(name)
    return stem[: limit - len(ext) - 1] + "…" + ext


def kind_of_all(paths):
    kinds = {kind_of(p) for p in paths}
    if len(kinds) == 1:
        return kinds.pop()
    if "pdf" in kinds and kinds <= {"pdf", "image", "word"}:
        return "pdf"  # karisik PDF / Word / gorsel -> birlestirilebilir
    if kinds == {"word", "image"} or kinds == {"word"}:
        return "word"
    return "other"


def log_event(text):
    """Sorun teshisi icin kisa olay kaydi (%LOCALAPPDATA%\\Mandalina\\olaylar.log)."""
    try:
        folder = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Mandalina")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "olaylar.log")
        if os.path.exists(path) and os.path.getsize(path) > 500_000:
            os.replace(path, path + ".eski")
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except Exception:
        pass


def log_error():
    import traceback
    try:
        folder = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Mandalina")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "hata.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Donusumler
# --------------------------------------------------------------------------
def unique_path(src, ext):
    base = os.path.splitext(src.rstrip("\\/"))[0]
    out = f"{base}.{ext.lower()}"
    n = 1
    while os.path.exists(out):
        out = f"{base} ({n}).{ext.lower()}"
        n += 1
    return out


def ffmpeg(args):
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    local = os.path.join(here, "ffmpeg.exe")
    exe = local if os.path.exists(local) else shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg bulunamadı (Mandalina.exe'nin yanına ffmpeg.exe koy)")
    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "ffmpeg hatasi")


def convert_image(src, fmt):
    out = unique_path(src, "jpg" if fmt == "JPG" else fmt)
    img = Image.open(src)
    if fmt in ("JPG", "PDF", "BMP") and img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    if fmt == "JPG":
        img.save(out, "JPEG", quality=92)
    elif fmt == "ICO":
        img.save(out, sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    elif fmt == "WEBP":
        img.save(out, "WEBP", quality=90)
    else:
        img.save(out, {"TIFF": "TIFF", "PNG": "PNG", "PDF": "PDF", "BMP": "BMP"}[fmt])
    return out


def convert_media(src, fmt):
    out = unique_path(src, fmt)
    if fmt == "GIF":
        ffmpeg(["-i", src, "-vf",
                "fps=15,scale='min(640,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                out])
    elif fmt in ("MP3", "WAV", "FLAC", "M4A", "OGG", "OPUS"):
        codec = {"MP3": ["-c:a", "libmp3lame", "-q:a", "2"], "WAV": ["-c:a", "pcm_s16le"],
                 "FLAC": ["-c:a", "flac"], "M4A": ["-c:a", "aac", "-b:a", "192k"],
                 "OGG": ["-c:a", "libvorbis", "-q:a", "5"], "OPUS": ["-c:a", "libopus", "-b:a", "128k"]}[fmt]
        ffmpeg(["-i", src, "-vn", *codec, out])
    elif fmt == "WEBM":
        ffmpeg(["-i", src, "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus", out])
    else:  # MP4 / MOV / MKV
        ffmpeg(["-i", src, "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out])
    return out


def make_zip(paths):
    out = unique_path(paths[0] if len(paths) == 1 else os.path.join(os.path.dirname(paths[0]), "Arsiv"), "zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            if os.path.isdir(p):
                parent = os.path.dirname(p.rstrip("\\/"))
                for dp, _, files in os.walk(p):
                    for f in files:
                        full = os.path.join(dp, f)
                        z.write(full, os.path.relpath(full, parent))
            else:
                z.write(p, os.path.basename(p))
    return out


def unique_dir(src, suffix):
    base = os.path.splitext(src)[0] + f" ({suffix})"
    out, n = base, 1
    while os.path.exists(out):
        out = f"{base} {n}"
        n += 1
    os.makedirs(out)
    return out


# ---- PDF (PyMuPDF / pdf2docx) ----
def convert_pdf(src, fmt):
    import pymupdf
    if fmt == "DOCX":
        from pdf2docx import Converter
        out = unique_path(src, "docx")
        cv = Converter(src)
        try:
            cv.convert(out)
        finally:
            cv.close()
        return out
    with pymupdf.open(src) as doc:
        if fmt == "TXT":
            out = unique_path(src, "txt")
            with open(out, "w", encoding="utf-8") as f:
                for i, page in enumerate(doc, 1):
                    f.write(f"--- Sayfa {i} ---\n{page.get_text()}\n")
            return out
        ext = "png" if fmt == "PNG" else "jpg"
        if doc.page_count == 1:
            out = unique_path(src, ext)
            doc[0].get_pixmap(dpi=200).save(out)
            return out
        folder = unique_dir(src, "sayfalar")
        for i, page in enumerate(doc, 1):
            page.get_pixmap(dpi=200).save(os.path.join(folder, f"sayfa-{i:03d}.{ext}"))
        return folder


def merge_pdfs(paths):
    """PDF, Word ve gorselleri verilen sirayla tek PDF'te birlestirir.
    Siralama degistirilmez: Explorer suruklemede tutulan dosyayi listenin basina koyar,
    boylece tutulan PDF birlesik dosyanin ilk sayfalari olur."""
    import pymupdf
    import tempfile
    out = unique_path(os.path.join(os.path.dirname(paths[0]), "Birlesik"), "pdf")
    tmp = tempfile.mkdtemp(prefix="mandalina")
    try:
        with pymupdf.open() as merged:
            for p in paths:
                k = kind_of(p)
                if k == "pdf":
                    with pymupdf.open(p) as d:
                        merged.insert_pdf(d)
                elif k == "image":
                    with pymupdf.open(p) as d:
                        merged.insert_pdf(pymupdf.open("pdf", d.convert_to_pdf()))
                elif k == "word":
                    pdf = convert_word(p, "PDF", out_dir=tmp)
                    with pymupdf.open(pdf) as d:
                        merged.insert_pdf(d)
            merged.save(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def split_pdf(src):
    """Her sayfayi ayri bir PDF olarak '<ad> (sayfalar)' klasorune yazar."""
    import pymupdf
    with pymupdf.open(src) as doc:
        if doc.page_count < 2:
            raise RuntimeError("tek sayfalık PDF parçalanamaz")
        folder = unique_dir(src, "sayfalar")
        stem = os.path.splitext(os.path.basename(src))[0]
        for i in range(doc.page_count):
            with pymupdf.open() as one:
                one.insert_pdf(doc, from_page=i, to_page=i)
                one.save(os.path.join(folder, f"{stem} - sayfa {i + 1:03d}.pdf"))
    return folder


# ---- Office (Word / Excel / PowerPoint, COM uzerinden) ----
WORD_FMT = {"PDF": (17, "pdf"), "DOCX": (16, "docx"), "TXT": (2, "txt"), "RTF": (6, "rtf"), "ODT": (23, "odt")}
EXCEL_FMT = {"XLSX": (51, "xlsx"), "CSV": (62, "csv"), "ODS": (60, "ods")}
SLIDES_FMT = {"PDF": (32, "pdf"), "PPTX": (24, "pptx"), "PNG": (18, "png"), "JPG": (17, "jpg")}


def office_app(progid):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        return win32com.client.DispatchEx(progid)
    except Exception:
        raise RuntimeError(f"{progid.split('.')[0]} bulunamadı (Microsoft Office gerekli)")


def convert_word(src, fmt, out_dir=None):
    code, ext = WORD_FMT[fmt]
    out = unique_path(os.path.join(out_dir, os.path.basename(src)) if out_dir else src, ext)
    app = office_app("Word.Application")
    try:
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(src, False, True, False)  # ConfirmConversions, ReadOnly, AddToRecent
        try:
            if fmt == "TXT":
                doc.SaveAs2(out, FileFormat=code, Encoding=65001)
            else:
                doc.SaveAs2(out, FileFormat=code)
        finally:
            doc.Close(False)
    finally:
        app.Quit()
    return out


def convert_excel(src, fmt):
    out = unique_path(src, "pdf" if fmt == "PDF" else EXCEL_FMT[fmt][1])
    app = office_app("Excel.Application")
    try:
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(src, 0, True)  # UpdateLinks, ReadOnly
        try:
            if fmt == "PDF":
                wb.ExportAsFixedFormat(0, out)
            else:
                wb.SaveAs(out, EXCEL_FMT[fmt][0])
        finally:
            wb.Close(False)
    finally:
        app.Quit()
    return out


def convert_slides(src, fmt):
    code, ext = SLIDES_FMT[fmt]
    out = unique_dir(src, "slaytlar") if fmt in ("PNG", "JPG") else unique_path(src, ext)
    if fmt in ("PNG", "JPG"):
        os.rmdir(out)  # PowerPoint klasoru kendisi olusturur
    app = office_app("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(src, True, False, False)  # ReadOnly, Untitled, WithWindow
        try:
            pres.SaveAs(out, code)
        finally:
            pres.Close()
    finally:
        if app.Presentations.Count == 0:  # kullanicinin acik sunumu varsa PowerPoint'i kapatma
            app.Quit()
    return out


def convert(paths, fmt):
    """(basarili ciktilar, hatalar) dondurur."""
    if fmt == "ZIP":
        return [make_zip(paths)], []
    if fmt == "BİRLEŞTİR":
        return [merge_pdfs(paths)], []
    images = [p for p in paths if kind_of(p) == "image"]
    # Birden fazla gorsel -> tek PDF
    if fmt == "PDF" and len(images) > 1 and len(images) == len(paths):
        pages = [Image.open(p).convert("RGB") for p in images]
        out = unique_path(os.path.join(os.path.dirname(images[0]), "Birlesik"), "pdf")
        pages[0].save(out, "PDF", save_all=True, append_images=pages[1:])
        return [out], []
    outs, errs = [], []
    for p in paths:
        k = kind_of(p)
        try:
            if k == "image" and fmt in TARGETS["image"]:
                outs.append(convert_image(p, fmt))
            elif k == "video" and fmt in TARGETS["video"]:
                outs.append(convert_media(p, fmt))
            elif k == "audio" and fmt in TARGETS["audio"]:
                outs.append(convert_media(p, fmt))
            elif k == "pdf" and fmt == "PARÇALA":
                outs.append(split_pdf(p))
            elif k == "pdf" and fmt in ("DOCX", "PNG", "JPG", "TXT"):
                outs.append(convert_pdf(p, fmt))
            elif k == "word" and fmt in WORD_FMT:
                outs.append(convert_word(p, fmt))
            elif k == "excel" and fmt in ("PDF", *EXCEL_FMT):
                outs.append(convert_excel(p, fmt))
            elif k == "slides" and fmt in SLIDES_FMT:
                outs.append(convert_slides(p, fmt))
            else:
                errs.append(f"{os.path.basename(p)}: {fmt} desteklenmiyor")
        except Exception as e:
            msg = str(e)
            if hasattr(e, "excepinfo") and e.excepinfo and e.excepinfo[2]:
                msg = e.excepinfo[2]  # Office'in kendi hata mesaji
            errs.append(f"{os.path.basename(p)}: {msg}")
    return outs, errs


# --------------------------------------------------------------------------
# WM_DROPFILES alimi (tkinter penceresinin WndProc'unu sarmalar)
# --------------------------------------------------------------------------
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
user32.CallWindowProcW.restype = LRESULT
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetAncestor.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetForegroundWindow.restype = wt.HWND
shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wt.UINT, wt.LPWSTR, wt.UINT]
shell32.DragFinish.argtypes = [ctypes.c_void_p]
shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]


def accept_drops(hwnd, callback):
    for msg in (WM_DROPFILES, WM_COPYGLOBALDATA):  # yonetici olarak calisirken de drop alabilmek icin
        user32.ChangeWindowMessageFilterEx(hwnd, msg, 1, None)
    shell32.DragAcceptFiles(hwnd, True)

    def proc(h, msg, wp, lp):
        if msg == WM_DROPFILES:
            n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
            files = []
            for i in range(n):
                buf = ctypes.create_unicode_buffer(shell32.DragQueryFileW(wp, i, None, 0) + 1)
                shell32.DragQueryFileW(wp, i, buf, len(buf))
                files.append(buf.value)
            shell32.DragFinish(wp)
            callback(files)
            return 0
        return user32.CallWindowProcW(old, h, msg, wp, lp)

    new = WNDPROC(proc)
    old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(new, ctypes.c_void_p))
    return new  # referansi canli tut


# --------------------------------------------------------------------------
# OLE IDropTarget: suruklenen dosyalari, birakmadan once (DragEnter'da)
# dogrudan surukleme verisinden okur. Explorer'a ayrica soru sormaya gerek
# kalmaz ve her zaman "kopyala" doner, kaynak dosyaya asla dokunulmaz.
# --------------------------------------------------------------------------
DROPEFFECT_COPY = 1
ole32 = ctypes.WinDLL("ole32")
HRESULT = ctypes.c_long
E_NOINTERFACE = -2147467262  # 0x80004002


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                ("d4", ctypes.c_ubyte * 8)]


def _iid(text):
    g = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return bytes(g)


IID_IUNKNOWN = _iid("{00000000-0000-0000-C000-000000000046}")
IID_IDROPTARGET = _iid("{00000122-0000-0000-C000-000000000046}")


class FORMATETC(ctypes.Structure):
    _fields_ = [("cfFormat", wt.WORD), ("ptd", ctypes.c_void_p), ("dwAspect", wt.DWORD),
                ("lindex", ctypes.c_long), ("tymed", wt.DWORD)]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [("tymed", wt.DWORD), ("hGlobal", ctypes.c_void_p), ("pUnkForRelease", ctypes.c_void_p)]


GETDATA = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))
ole32.ReleaseStgMedium.argtypes = [ctypes.POINTER(STGMEDIUM)]
ole32.RegisterDragDrop.argtypes = [wt.HWND, ctypes.c_void_p]
ole32.OleInitialize.argtypes = [ctypes.c_void_p]


def hdrop_files(pdata):
    """IDataObject'ten CF_HDROP (dosya listesi) okur."""
    vtbl = ctypes.cast(pdata, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    get_data = GETDATA(vtbl[3])  # IUnknown(3 metot) sonrasi ilk metot: GetData
    fe = FORMATETC(15, None, 1, -1, 1)  # CF_HDROP, DVASPECT_CONTENT, lindex, TYMED_HGLOBAL
    sm = STGMEDIUM()
    if get_data(pdata, ctypes.byref(fe), ctypes.byref(sm)) != 0:
        return []
    try:
        h = sm.hGlobal
        n = shell32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
        files = []
        for i in range(n):
            buf = ctypes.create_unicode_buffer(shell32.DragQueryFileW(h, i, None, 0) + 1)
            shell32.DragQueryFileW(h, i, buf, len(buf))
            files.append(buf.value)
        return files
    finally:
        ole32.ReleaseStgMedium(ctypes.byref(sm))


QI_FUNC = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
REF_FUNC = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
# POINTL degerle gecer; x64'te 8 baytlik tek bir tamsayi olarak gelir
ENTER_FUNC = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_int64,
                                ctypes.POINTER(wt.DWORD))
OVER_FUNC = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wt.DWORD, ctypes.c_int64, ctypes.POINTER(wt.DWORD))
LEAVE_FUNC = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)


class _DropVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", QI_FUNC), ("AddRef", REF_FUNC), ("Release", REF_FUNC),
                ("DragEnter", ENTER_FUNC), ("DragOver", OVER_FUNC), ("DragLeave", LEAVE_FUNC),
                ("Drop", ENTER_FUNC)]


class _DropObj(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_DropVtbl))]


class OleDropTarget:
    """Saf ctypes IDropTarget (pywin32'nin COM sunucu katmani Python 3.14'te cokuyor).
    Her zaman "kopyala" doner, kaynak dosyaya asla dokunulmaz."""

    def __init__(self, on_enter, on_drop):
        self.on_enter, self.on_drop = on_enter, on_drop
        self.vtbl = _DropVtbl(QI_FUNC(self._qi), REF_FUNC(lambda this: 1), REF_FUNC(lambda this: 1),
                              ENTER_FUNC(self._enter), OVER_FUNC(self._over), LEAVE_FUNC(lambda this: 0),
                              ENTER_FUNC(self._drop))
        self.obj = _DropObj(ctypes.pointer(self.vtbl))
        self.ptr = ctypes.addressof(self.obj)

    def _qi(self, this, riid, ppv):
        if ctypes.string_at(riid, 16) in (IID_IUNKNOWN, IID_IDROPTARGET):
            ppv[0] = this
            return 0
        ppv[0] = None
        return E_NOINTERFACE

    def _enter(self, this, pdata, keys, pt, effect):
        try:
            self.on_enter(hdrop_files(pdata))
        except Exception:
            log_error()
        effect[0] = DROPEFFECT_COPY
        return 0

    def _over(self, this, keys, pt, effect):
        effect[0] = DROPEFFECT_COPY
        return 0

    def _drop(self, this, pdata, keys, pt, effect):
        try:
            self.on_drop(hdrop_files(pdata))
        except Exception:
            log_error()
        effect[0] = DROPEFFECT_COPY
        return 0


def register_ole_drop(hwnds, wheel):
    hr = ole32.OleInitialize(None)
    if hr not in (0, 1):  # S_OK / S_FALSE
        log_event(f"OleInitialize basarisiz: {hr:#x}")
        return None
    # COM cagrisinin icinde tkinter'a dokunmak Python'u cokertiyor: sadece kuyruga yaz,
    # isleme App.poll'da (normal Tk dongusunde) yapilir.
    target = OleDropTarget(lambda files: wheel.ole_events.append(("enter", files)),
                           lambda files: wheel.ole_events.append(("drop", files)))
    for h in hwnds:
        hr = ole32.RegisterDragDrop(h, target.ptr)
        if hr != 0:
            log_event(f"RegisterDragDrop {h:#x} basarisiz: {hr & 0xFFFFFFFF:#x}")
    return target


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# --------------------------------------------------------------------------
# Arayuz
# --------------------------------------------------------------------------
class Wheel:
    def __init__(self, root, on_pick=None):
        self.root = root
        self.on_pick = on_pick
        size = RADIUS_OUT * 2 + 20
        self.size = size
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT)
        self.win.attributes("-transparentcolor", TRANSPARENT)
        self.canvas = tk.Canvas(self.win, width=size, height=size, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self.win.update_idletasks()
        hwnd = user32.GetAncestor(self.win.winfo_id(), 2)
        self._proc = accept_drops(hwnd, self.on_drop)  # yedek yol (WM_DROPFILES)
        self._ole = None
        self.ole_events = []  # OLE geri cagrilarinin biraktigi ("enter"/"drop", dosyalar)
        if on_pick:  # yalnizca surukle-birak modunda
            self._ole = register_ole_drop([self.canvas.winfo_id(), hwnd], self)
        self.labels, self.hot, self.center = [], None, (0, 0)
        self.title = ""
        self.known = None  # suruklenen dosyalar (DragEnter'da ogrenilir)
        self.visible = False

    def on_enter(self, files):
        """Surukleme carkin uzerine girdi: dosya turune gore dilimleri guncelle."""
        if not files or files == self.known or not self.visible:
            return
        self.known = files
        labels, title = wheel_for(files)
        log_event(f"suruklenen: {title}")
        if labels != self.labels or title != self.title:
            self.labels, self.title, self.hot = labels, title, None
            self.draw()

    def show(self, x, y, labels, title):
        self.labels, self.hot, self.center, self.title = labels, None, (x, y), title
        self.known = None
        h = self.size // 2
        self.win.geometry(f"{self.size}x{self.size}+{x - h}+{y - h}")
        self.draw()
        self.win.deiconify()
        self.win.lift()
        self.visible = True

    def hide(self):
        self.win.withdraw()
        self.visible = False

    def slice_at(self, x, y):
        dx, dy = x - self.center[0], y - self.center[1]
        r = math.hypot(dx, dy)
        if r < RADIUS_IN or r > RADIUS_OUT + 10 or not self.labels:
            return None
        ang = (math.degrees(math.atan2(-dy, dx)) - 90) % 360  # 0 = yukari, saat yonunun tersi
        step = 360 / len(self.labels)
        return int(((360 - ang) % 360 + step / 2) // step) % len(self.labels)

    def track(self, x, y):
        s = self.slice_at(x, y)
        if s != self.hot:
            self.hot = s
            self.draw()

    def draw(self):
        c, n, m = self.canvas, len(self.labels), self.size // 2
        c.delete("all")
        R, r = RADIUS_OUT, RADIUS_IN
        # Koyu dis hale + kalin turuncu halka: hem siyah hem beyaz arka planda secilir
        c.create_oval(m - R - 9, m - R - 9, m + R + 9, m + R + 9, fill=COLORS["edge"], outline="")
        c.create_oval(m - R - 6, m - R - 6, m + R + 6, m + R + 6, fill=COLORS["ring"], outline="")
        step = 360 / n
        for i, lab in enumerate(self.labels):
            fill = COLORS["hot"] if i == self.hot else COLORS["slice"]
            if n == 1:  # tk 360 derecelik dilimi duzgun cizemiyor
                c.create_oval(m - R, m - R, m + R, m + R, fill=fill, outline=COLORS["line"], width=2)
            else:
                start = 90 - i * step - step / 2  # tk acilari: 0 = sag, saat yonunun tersi
                c.create_arc(m - R, m - R, m + R, m + R, start=start, extent=step, style="pieslice",
                             fill=fill, outline=COLORS["line"], width=2)
            a = math.radians(90 - i * step)
            tr = (R + r) / 2 + 4
            c.create_text(m + tr * math.cos(a), m - tr * math.sin(a), text=lab.replace(" ", "\n"),
                          justify="center", fill=COLORS["hot_text"] if i == self.hot else COLORS["text"],
                          font=("Segoe UI Black", 13 if len(lab) <= 5 else 10))
        c.create_oval(m - r, m - r, m + r, m + r, fill=COLORS["hub"], outline=COLORS["ring"], width=4)
        c.create_text(m, m, text=short_name(self.title), fill=COLORS["hub_text"], font=("Segoe UI Semibold", 8),
                      width=r * 2 - 14, justify="center")

    def enable_click(self, on_click):
        """Sag tik menusu modu: carki surukleme yerine tiklamayla kullan."""
        self.canvas.bind("<Motion>", lambda e: self.track(e.x_root, e.y_root))
        self.canvas.bind("<Button-1>", lambda e: on_click(self.slice_at(e.x_root, e.y_root)))

    def on_drop(self, files):
        x, y = cursor_pos()
        s = self.slice_at(x, y)
        log_event(f"birakildi: {[os.path.basename(f) for f in files][:5]}, "
                  f"dilim={self.labels[s] if s is not None else '-'}, cark_acik={self.visible}")
        self.hide()
        if s is not None and self.on_pick:
            self.on_pick(files, self.labels[s])


# --------------------------------------------------------------------------
# Donusumu ayri bir islemde calistir: Office/PDF kutuphaneleri cokse bile
# ana program ayakta kalir.
# --------------------------------------------------------------------------
def self_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(__file__)]


def run_conversion(files, fmt):
    fd, res = tempfile.mkstemp(prefix="mandalina-", suffix=".json")
    os.close(fd)
    try:
        subprocess.run([*self_command(), "--convert", fmt, res, *files],
                       creationflags=0x08000000, timeout=1800)
        with open(res, encoding="utf-8") as f:
            data = json.load(f)
        outs, errs = data["outs"], data["errs"]
    except subprocess.TimeoutExpired:
        outs, errs = [], ["işlem 30 dakikada bitmedi, durduruldu"]
    except Exception:
        log_error()
        outs, errs = [], ["dönüştürme işlemi beklenmedik şekilde kapandı (dosya bozuk ya da korumalı olabilir)"]
    finally:
        try:
            os.remove(res)
        except OSError:
            pass
    if outs:
        msg = f"✓ {len(outs)} dosya hazır: {os.path.basename(outs[0])}" + (" ..." if len(outs) > 1 else "")
    else:
        msg = "Dönüştürülemedi"
    if errs:
        msg += "\n" + "\n".join(errs[:3])
    log_event(f"{fmt} sonucu: " + msg.replace("\n", " | "))
    return msg


def child_convert(fmt, result_path, files):
    try:
        outs, errs = convert(files, fmt)
    except Exception as e:
        log_error()
        outs, errs = [], [str(e)]
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"outs": outs, "errs": errs}, f)


def copy_paths(files):
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText("\r\n".join(files), win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


# BİRLEŞTİR'e tek dosya gelirse bekletilir; sonraki BİRLEŞTİR'de birlikte birlestirilir
# (ilk birakilan basta). Dosyada tutulur ki surukleme ve sag tik birlikte kullanilabilsin.
MERGE_WAIT_SECONDS = 600


def _merge_wait_path():
    folder = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "Mandalina")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "birlestir-bekleyen.json")


def merge_queue(files):
    """Birlestirilecek tam listeyi dondurur; tek dosya beklemeye alindiysa None."""
    path = _merge_wait_path()
    pending = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) < MERGE_WAIT_SECONDS:
            pending = [p for p in data.get("files", []) if os.path.exists(p)]
    except (OSError, ValueError):
        pass
    combined = pending + [f for f in files if f not in pending]
    if len(combined) < 2:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"time": time.time(), "files": combined}, f)
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    return combined


def merge_waiting_message(files):
    return (f"1. dosya alındı: {os.path.basename(files[0])}\n"
            "Şimdi 2. dosyayı da BİRLEŞTİR'e bırak (10 dakika içinde).")


def wheel_for(paths):
    kind = kind_of_all(paths)
    title = os.path.basename(paths[0].rstrip("\\/")) if len(paths) == 1 else f"{len(paths)} dosya"
    return TARGETS[kind], title


_toast = None


def toast(root, text, busy=False):
    global _toast
    if _toast is not None:
        try:
            _toast.destroy()
        except tk.TclError:
            pass
    t = tk.Toplevel(root)
    t.overrideredirect(True)
    t.attributes("-topmost", True)
    t.attributes("-alpha", 0.95)
    t.configure(bg=COLORS["ring"])
    tk.Label(t, text=("\U0001F34A  " + text), bg=COLORS["bg"], fg="#f2f2f2", font=("Segoe UI", 10),
             padx=16, pady=10, justify="left", wraplength=420).pack(padx=2, pady=2)
    t.update_idletasks()
    sw, sh = t.winfo_screenwidth(), t.winfo_screenheight()
    t.geometry(f"+{sw - t.winfo_width() - 24}+{sh - t.winfo_height() - 72}")
    _toast = t
    if not busy:
        t.after(6000, lambda: t.destroy() if t.winfo_exists() else None)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.events = queue.Queue()  # diger thread'ler arayuze sadece bu kuyruk uzerinden ulasir
        self.wheel = Wheel(self.root, on_pick=self.pick)
        self.press_pos = None
        self.dragging = False
        self.opened_this_drag = False
        self.shift_was = False
        if context_menu_wanted():
            try:
                register_context_menu()
            except OSError:
                log_error()
        self.jobs = 0  # suren donusum sayisi (guncelleme bunlarin bitmesini bekler)
        if updated_from:
            toast(self.root, f"Mandalina {APP_VERSION} sürümüne güncellendi.")
        else:
            toast(self.root, "Mandalina çalışıyor. Dosya sürükle + Shift'e bas\nya da dosyaya sağ tıkla.\n"
                             "Kapatmak için saat yanındaki turuncu simgeye sağ tıkla.")
        self.tray = start_tray(lambda: self.events.put(("quit", None)))
        self.root.after(15, self.poll)
        if can_self_update():
            threading.Thread(target=self.update_worker, daemon=True).start()

    def update_worker(self):
        time.sleep(5)  # acilisi yavaslatma
        try:
            found = find_update(APP_VERSION)
            if not found:
                return
            tag, url, size = found
            log_event(f"guncelleme bulundu: {tag}")
            self.events.put(("toast", f"Yeni sürüm bulundu ({tag.removeprefix(TAG_PREFIX)}), indiriliyor..."))
            new_exe = download_update(url, size)
            self.events.put(("update", (tag, new_exe)))
        except Exception:
            log_error()

    def install_update(self, tag, new_exe):
        if self.jobs > 0 or self.wheel.visible:  # once suren isler bitsin
            self.root.after(2000, lambda: self.install_update(tag, new_exe))
            return
        try:
            apply_update(new_exe, tag)
        except Exception:
            log_error()
            toast(self.root, "Güncelleme kurulamadı; mevcut sürümle devam ediliyor.")
            return
        self.quit()

    def pick(self, files, fmt):
        if fmt == "YOLU KOPYALA":
            copy_paths(files)
            toast(self.root, f"✓ {len(files)} dosya yolu panoya kopyalandı")
            return
        if fmt == "BİRLEŞTİR":
            combined = merge_queue(files)
            log_event(f"birlestir kuyrugu: {[os.path.basename(f) for f in (combined or files)]}")
            if combined is None:
                toast(self.root, merge_waiting_message(files))
                return
            files = combined
        toast(self.root, f"{fmt} işleniyor...", busy=True)
        self.jobs += 1
        threading.Thread(target=lambda: self.events.put(("done", run_conversion(files, fmt))),
                         daemon=True).start()

    def quit(self):
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def poll(self):
        # Tek bir hata bile dongunun durmasina (ve carkin bir daha acilmamasina) yol acmasin
        try:
            while not self.events.empty():
                kind, data = self.events.get_nowait()
                if kind == "quit":
                    self.quit()
                    return
                if kind == "update":
                    self.install_update(*data)
                    continue
                if kind == "done":
                    self.jobs -= 1
                toast(self.root, data)
            while self.wheel.ole_events:
                kind, files = self.wheel.ole_events.pop(0)
                if kind == "enter":
                    self.wheel.on_enter(files)
                else:
                    self.wheel.on_drop(files)
            self._poll()
        except Exception:
            log_error()
            self.press_pos, self.dragging = None, False
            try:
                self.wheel.hide()
            except Exception:
                pass
        self.root.after(15, self.poll)

    def _poll(self):
        lb, sh = key_down(VK_LBUTTON), key_down(VK_SHIFT)
        pos = cursor_pos()
        if lb:
            if self.press_pos is None:
                self.press_pos = pos
                self.opened_this_drag = False
            elif not self.dragging and math.dist(pos, self.press_pos) > DRAG_THRESHOLD:
                self.dragging = True
            # Shift surukleme sirasinda basilsa da, oncesinden basili tutulsa da carki ac
            if self.dragging and sh and not self.wheel.visible and not self.opened_this_drag:
                self.opened_this_drag = True
                self.open_wheel(pos)
            if self.wheel.visible:
                self.wheel.track(*pos)
                if key_down(VK_ESCAPE):
                    self.wheel.hide()
        else:
            if self.wheel.visible and self.dragging:  # birakildi; drop mesajinin islenmesine firsat ver
                self.root.after(1500, lambda: self.wheel.hide() if not key_down(VK_LBUTTON) else None)
            self.press_pos, self.dragging = None, False
        self.shift_was = sh

    def open_wheel(self, pos):
        # Dosya turu, surukleme carkin uzerine girer girmez (DragEnter) ogrenilir
        log_event("cark acildi")
        self.wheel.show(*pos, TARGETS["unknown"], "Dönüştür")

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------
# Sag tik menusu: "Mandalina ile dönüştür"
# Coklu secimde Explorer her dosya icin ayri islem baslatir; ilk islem
# (lider) digerlerinin yollarini kisa bir sure toplayip tek cark acar.
# --------------------------------------------------------------------------
MENU_KEYS = [r"Software\Classes\*\shell\Mandalina", r"Software\Classes\Directory\shell\Mandalina"]
SETTINGS_KEY = r"Software\Mandalina"


def gather_menu_paths(first):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Mandalina-Menu")
    leader = ctypes.get_last_error() != 183
    qfile = os.path.join(tempfile.gettempdir(), "mandalina-menu.txt")
    with open(qfile, "a", encoding="utf-8") as f:
        f.write(f"{time.time():.3f}\t{first}\n")
    if not leader:
        return None
    last, stable_since, deadline = -1, time.time(), time.time() + 5
    while time.time() < deadline:
        size = os.path.getsize(qfile) if os.path.exists(qfile) else 0
        if size != last:
            last, stable_since = size, time.time()
        elif time.time() - stable_since > 0.4:
            break
        time.sleep(0.05)
    paths = []
    try:
        with open(qfile, encoding="utf-8") as f:
            lines = f.read().splitlines()
        os.remove(qfile)
    except OSError:
        lines = []
    for line in lines:
        ts, _, p = line.partition("\t")
        try:
            fresh = time.time() - float(ts) < 15  # onceki yarim kalmis kayitlari alma
        except ValueError:
            fresh = False
        if fresh and p and p not in paths:
            paths.append(p)
    kernel32.CloseHandle(handle)
    return paths or [first]


def menu_mode(first):
    paths = gather_menu_paths(first)
    if not paths:
        return
    root = tk.Tk()
    root.withdraw()
    events = queue.Queue()
    started = time.time()
    state = {"done": False}

    def finish(delay=0):
        state["done"] = True
        root.after(delay, root.destroy)

    def click(i):
        if state["done"]:
            return
        wheel.hide()
        if i is None:
            finish()
            return
        fmt = wheel.labels[i]
        if fmt == "YOLU KOPYALA":
            copy_paths(paths)
            toast(root, f"✓ {len(paths)} dosya yolu panoya kopyalandı")
            finish(2500)
            return
        files = paths
        if fmt == "BİRLEŞTİR":
            files = merge_queue(paths)
            if files is None:
                toast(root, merge_waiting_message(paths))
                finish(5000)
                return
        state["done"] = True
        toast(root, f"{fmt} işleniyor...", busy=True)
        threading.Thread(target=lambda: events.put(run_conversion(files, fmt)), daemon=True).start()

    wheel = Wheel(root)
    wheel.enable_click(click)
    labels, title = wheel_for(paths)
    wheel.show(*cursor_pos(), labels, title)
    wheel.win.focus_force()

    def tick():
        try:
            msg = events.get_nowait()
            toast(root, msg)
            root.after(6000, root.destroy)
            return
        except queue.Empty:
            pass
        if wheel.visible and not state["done"]:
            x, y = cursor_pos()
            wheel.track(x, y)
            outside = math.dist((x, y), wheel.center) > RADIUS_OUT + 10
            if key_down(VK_ESCAPE) or (time.time() - started > 0.5 and outside and
                                       (key_down(VK_LBUTTON) or key_down(0x02))):
                wheel.hide()
                finish()
                return
        root.after(30, tick)

    root.after(30, tick)
    root.mainloop()


def _menu_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --menu "%1"', sys.executable
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw}" "{os.path.abspath(__file__)}" --menu "%1"', None


def register_context_menu():
    import winreg
    cmd, icon = _menu_command()
    for key in MENU_KEYS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Mandalina ile dönüştür")
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            if icon:
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)


def unregister_context_menu():
    import winreg
    for key in MENU_KEYS:
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


def context_menu_wanted():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            return winreg.QueryValueEx(k, "ContextMenu")[0] != 0
    except OSError:
        return True  # varsayilan: acik


def toggle_context_menu():
    import winreg
    want = not context_menu_wanted()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
        winreg.SetValueEx(k, "ContextMenu", 0, winreg.REG_DWORD, int(want))
    if want:
        register_context_menu()
    else:
        unregister_context_menu()


# --------------------------------------------------------------------------
# Otomatik guncelleme: acilista GitHub Releases'te daha yeni "mandalina-vX.Y"
# surumu ve Mandalina.exe varligi arar; indirir, calisan exe'yi yeniden adlandirir
# (Windows calisan exe'nin adini degistirmeye izin verir), yenisini yerine koyar
# ve yeniden baslatir. "dev" derlemeler ve .py olarak calistirma guncellenmez.
# --------------------------------------------------------------------------
TAG_PREFIX = "mandalina-v"
UPDATE_API = os.environ.get("MANDALINA_UPDATE_URL",
                            "https://api.github.com/repos/gokhangeo/uzman/releases?per_page=50")


def read_app_version():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


APP_VERSION = read_app_version()
updated_from = None  # --updated ile baslatildiysa eski exe'nin yolu


def version_tuple(text):
    try:
        return tuple(int(x) for x in text.strip().split("."))
    except ValueError:
        return None


def can_self_update():
    return getattr(sys, "frozen", False) and version_tuple(APP_VERSION) is not None


def find_update(current):
    """(etiket, indirme_adresi, boyut) ya da None."""
    import urllib.request
    req = urllib.request.Request(UPDATE_API, headers={"Accept": "application/vnd.github+json",
                                                     "User-Agent": "Mandalina"})
    with urllib.request.urlopen(req, timeout=20) as r:
        releases = json.load(r)
    cur = version_tuple(current)
    skipped = setting("SkipTag")
    best = None
    for rel in releases:
        tag = rel.get("tag_name", "")
        if rel.get("draft") or rel.get("prerelease") or not tag.startswith(TAG_PREFIX) or tag == skipped:
            continue
        v = version_tuple(tag[len(TAG_PREFIX):])
        asset = next((a for a in rel.get("assets", []) if a.get("name") == "Mandalina.exe"), None)
        if v and asset and v > cur and (best is None or v > best[0]):
            best = (v, tag, asset["browser_download_url"], asset["size"])
    return best[1:] if best else None


def download_update(url, size):
    import urllib.request
    dest = os.path.join(os.path.dirname(sys.executable), "Mandalina.guncelleme.exe")
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Mandalina"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 1024)
    if os.path.getsize(part) != size:
        os.remove(part)
        raise RuntimeError("indirilen dosyanın boyutu yanlış")
    os.replace(part, dest)
    return dest


def apply_update(new_exe, tag):
    exe = sys.executable
    old = os.path.splitext(exe)[0] + ".eski.exe"
    if os.path.exists(old):
        os.remove(old)
    os.replace(exe, old)  # calisan exe yeniden adlandirilabilir
    try:
        os.replace(new_exe, exe)
    except OSError:
        os.replace(old, exe)
        raise
    # Yeni surum ayni etikete ragmen hala eski surumu bildirirse sonsuz donguye girme
    set_setting("SkipTag", tag)
    log_event(f"guncelleme kuruldu: {tag}")
    # PYINSTALLER_RESET_ENVIRONMENT: yeni exe, kapanmakta olan eski surumun gecici
    # klasorunu devralmasin, kendi dosyalarini acsin.
    subprocess.Popen([exe, "--updated", old], close_fds=True,
                     env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"),
                     creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | NEW_PROCESS_GROUP


def finish_update(old_exe):
    """Yeni surum ilk acilis: eski surum kapanana kadar bekle, eski exe'yi sil."""
    for _ in range(100):
        if single_instance():
            break
        time.sleep(0.2)
    else:
        return False
    for _ in range(50):
        try:
            if os.path.exists(old_exe):
                os.remove(old_exe)
            break
        except OSError:
            time.sleep(0.2)
    return True


def setting(name):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def set_setting(name, value):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Mandalina")
            return True
    except OSError:
        return False


def toggle_autostart():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if autostart_enabled():
            winreg.DeleteValue(k, "Mandalina")
        else:
            winreg.SetValueEx(k, "Mandalina", 0, winreg.REG_SZ, launch_command())


def app_icon(size=64):
    from PIL import ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.ellipse((4 * s, 10 * s, 60 * s, 62 * s), fill="#ff8a1f")
    d.ellipse((14 * s, 18 * s, 30 * s, 30 * s), fill="#ffb366")
    d.ellipse((28 * s, 2 * s, 46 * s, 14 * s), fill="#3aa845")
    return img


def start_tray(on_quit):
    try:
        import pystray
    except ImportError:
        return None
    menu = pystray.Menu(
        pystray.MenuItem(f"Mandalina {APP_VERSION} — sürükle + Shift", None, enabled=False),
        pystray.MenuItem("Sağ tık menüsünde göster", lambda i, it: toggle_context_menu(),
                         checked=lambda it: context_menu_wanted()),
        pystray.MenuItem("Windows ile başlat", lambda i, it: toggle_autostart(),
                         checked=lambda it: autostart_enabled()),
        pystray.MenuItem("Çıkış", lambda i, it: on_quit()),
    )
    icon = pystray.Icon("Mandalina", app_icon(), "Mandalina", menu)
    icon.run_detached()
    return icon


def single_instance():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    single_instance.handle = kernel32.CreateMutexW(None, False, "Mandalina-DragShift-Converter")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--convert"] and len(args) >= 4:
        child_convert(args[1], args[2], args[3:])
        sys.exit(0)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    if args[:1] == ["--menu"] and len(args) >= 2:
        try:
            menu_mode(args[1])
        except Exception:
            log_error()
        sys.exit(0)
    if args[:1] == ["--updated"] and len(args) >= 2:
        updated_from = args[1]
        if not finish_update(args[1]):
            sys.exit(0)
    elif not single_instance():
        sys.exit(0)
    App().run()
