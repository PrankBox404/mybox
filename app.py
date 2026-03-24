"""
DropLoad — Video & Audio Downloader
====================================
Backend Flask com yt-dlp.
Suporta YouTube, Instagram, Facebook, TikTok e muitos mais.

INSTALAR DEPENDÊNCIAS:
    pip install flask yt-dlp flask-login werkzeug

CORRER LOCAL:
    python app.py
    → Abre http://localhost:5000 no browser

VARIÁVEIS DE AMBIENTE (opcional):
    INVITE_CODE   = código de convite para registo (default: gerado automaticamente)
    SECRET_KEY    = chave secreta para sessões (default: gerada automaticamente)
    ADMIN_USER    = utilizador admin criado automaticamente (default: admin)
    ADMIN_PASS    = password do admin (default: mostrada no arranque)
    DOWNLOAD_DIR  = pasta de downloads (default: ./downloads)
"""

import os
import sys
import threading
import uuid
import json
import time
import shutil
import subprocess
import importlib
import hashlib
import secrets
from pathlib import Path
from functools import wraps
from flask import (Flask, request, jsonify, send_file,
                   render_template_string, Response, stream_with_context,
                   session, redirect, url_for)
import yt_dlp

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "./downloads"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"

# Chave secreta para sessões
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Código de convite — define em variável de ambiente ou é gerado e mostrado no arranque
INVITE_CODE = os.environ.get("INVITE_CODE") or secrets.token_urlsafe(12)

# ─── Gestão de utilizadores (JSON simples) ────────────────────────────────────
def _load_users():
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_users(users):
    USERS_FILE.write_text(json.dumps(users, indent=2))

def _hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def _create_admin():
    """Cria utilizador admin na primeira execução."""
    users = _load_users()
    if not users:
        admin_user = os.environ.get("ADMIN_USER", "admin")
        admin_pass = os.environ.get("ADMIN_PASS") or secrets.token_urlsafe(10)
        users[admin_user] = {
            "password": _hash_pw(admin_pass),
            "role": "admin",
            "created": time.strftime("%Y-%m-%d %H:%M"),
        }
        _save_users(users)
        print(f"\n{'─'*50}")
        print(f"  👤 Admin criado!")
        print(f"  Utilizador : {admin_user}")
        print(f"  Password   : {admin_pass}")
        print(f"  Convite    : {INVITE_CODE}")
        print(f"  Link registo: http://localhost:5000/register?invite={INVITE_CODE}")
        print(f"{'─'*50}\n")
    else:
        print(f"\n  🔑 Código de convite: {INVITE_CODE}")
        print(f"  Link: http://localhost:5000/register?invite={INVITE_CODE}\n")

# ─── Decorador de autenticação ────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Não autenticado"}), 401
            return redirect(url_for("login_page", next=request.path))
        return f(*args, **kwargs)
    return decorated

# ─── Páginas de Auth ──────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    if request.method == "POST":
        data = request.form
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        users = _load_users()
        user = users.get(username)
        if user and user["password"] == _hash_pw(password):
            session["user"] = username
            session["role"] = user.get("role", "user")
            next_url = request.args.get("next", "/")
            return redirect(next_url)
        error = "Utilizador ou password incorretos."
    return render_template_string(_login_html(), error=error)

@app.route("/register", methods=["GET", "POST"])
def register_page():
    invite = request.args.get("invite", "")
    error = None
    success = None
    if request.method == "POST":
        invite_in = (request.form.get("invite") or "").strip()
        username  = (request.form.get("username") or "").strip().lower()
        password  = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if invite_in != INVITE_CODE:
            error = "Código de convite inválido."
        elif not username or len(username) < 3:
            error = "Nome de utilizador demasiado curto (mín. 3 caracteres)."
        elif not password or len(password) < 6:
            error = "Password demasiado curta (mín. 6 caracteres)."
        elif password != password2:
            error = "As passwords não coincidem."
        else:
            users = _load_users()
            if username in users:
                error = "Este utilizador já existe."
            else:
                users[username] = {
                    "password": _hash_pw(password),
                    "role": "user",
                    "created": time.strftime("%Y-%m-%d %H:%M"),
                }
                _save_users(users)
                session["user"] = username
                session["role"] = "user"
                return redirect("/")
    return render_template_string(_register_html(), invite=invite, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ─── Admin: ver utilizadores ──────────────────────────────────────────────────
@app.route("/admin/users")
@login_required
def admin_users():
    if session.get("role") != "admin":
        return "Acesso negado", 403
    users = _load_users()
    rows = "".join(
        f"<tr><td>{u}</td><td>{v['role']}</td><td>{v['created']}</td>"
        f"<td><a href='/admin/delete/{u}' onclick=\"return confirm('Eliminar {u}?')\">❌</a></td></tr>"
        for u, v in users.items()
    )
    return f"""<!DOCTYPE html><html><head><title>Utilizadores</title>
    <style>body{{font-family:monospace;background:#0d0f14;color:#c8d0e0;padding:30px}}
    table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border:1px solid #252835;text-align:left}}
    a{{color:#ff4757}}h2{{color:#00d4ff}}</style></head><body>
    <h2>👥 Utilizadores</h2>
    <p>🔑 Código de convite: <strong style="color:#f5c542">{INVITE_CODE}</strong></p>
    <p>Link: <code>http://seuservidor/register?invite={INVITE_CODE}</code></p>
    <table><tr><th>Utilizador</th><th>Papel</th><th>Criado</th><th>Ação</th></tr>{rows}</table>
    <br><a href="/" style="color:#6c63ff">← Voltar</a></body></html>"""

@app.route("/admin/delete/<username>")
@login_required
def admin_delete_user(username):
    if session.get("role") != "admin":
        return "Acesso negado", 403
    users = _load_users()
    if username in users and users[username].get("role") != "admin":
        del users[username]
        _save_users(users)
    return redirect("/admin/users")

# ─── Auto-detectar ffmpeg ─────────────────────────────────────────────────────
FFMPEG_PATH = None

def _find_ffmpeg():
    """Tenta encontrar o ffmpeg — pelo PATH do sistema ou via imageio-ffmpeg."""
    global FFMPEG_PATH

    # 1. Verifica se está no PATH do sistema
    ffmpeg_cmd = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    found = shutil.which(ffmpeg_cmd)
    if found:
        FFMPEG_PATH = found
        print(f"✓ ffmpeg encontrado no PATH: {found}")
        return

    # 2. Tenta via imageio-ffmpeg (pip install imageio-ffmpeg)
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            FFMPEG_PATH = path
            print(f"✓ ffmpeg via imageio-ffmpeg: {path}")
            return
    except ImportError:
        pass

    # 3. Não encontrou — tenta instalar imageio-ffmpeg automaticamente
    print("⚠ ffmpeg não encontrado. A instalar imageio-ffmpeg...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "imageio-ffmpeg", "-q"],
            check=True, timeout=60
        )
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            FFMPEG_PATH = path
            print(f"✓ ffmpeg instalado via imageio-ffmpeg: {path}")
            return
    except Exception as e:
        print(f"✗ Não foi possível instalar ffmpeg automaticamente: {e}")

    print("✗ ffmpeg não disponível — MP3 e HD (merge) não vão funcionar.")

_find_ffmpeg()

# Jobs em memória { job_id: { status, progress, filename, error, ... } }
jobs = {}

# ─── HTML (serve a UI) ────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    html_path = Path(__file__).parent / "index.html"
    html = html_path.read_text(encoding="utf-8")
    user = session.get("user", "?")
    role = session.get("role", "user")
    html = (html
        .replace("__USERNAME__", user)
        .replace("__ROLE__", role)
        .replace("__INITIAL__", user[0].upper()))
    return render_template_string(html)

def _height_from_fmt(fmt_id):
    """Extrai a altura (ex: 1080) do format_id composto '137+251'. Devolve 9999 se não encontrar."""
    try:
        # fmt_id pode ser "137+251" — o primeiro é o vídeo
        vid_id = fmt_id.split("+")[0]
        # Tenta mapear IDs conhecidos do YouTube para altura
        known = {"137": 1080, "248": 1080, "399": 1080,
                 "136": 720,  "247": 720,  "398": 720,
                 "135": 480,  "244": 480,  "397": 480,
                 "134": 360,  "243": 360,  "396": 360,
                 "133": 240,  "242": 240,  "395": 240}
        return known.get(vid_id, 9999)
    except Exception:
        return 9999


def _get_ytdlp_version():
    """Obtém a versão do yt-dlp — compatível com versões antigas e novas."""
    try:
        import yt_dlp.version as _v
        return _v.__version__
    except Exception:
        pass
    try:
        import yt_dlp as _y
        return getattr(_y, "__version__", None) or getattr(_y, "version_string", None)
    except Exception:
        pass
    return "desconhecida"


# ─── API: Info do vídeo ───────────────────────────────────────────────────────
@app.route("/api/info", methods=["POST"])
@login_required
def get_info():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL em falta"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # Formatos disponíveis
        formats = []
        seen_compat  = set()  # resoluções já adicionadas como compat
        seen_quality = set()  # resoluções já adicionadas como qualidade

        all_fmts = info.get("formats") or []

        # ── Encontra melhor áudio AAC (para merge sem re-encode)
        best_aac_id  = None
        best_aac_abr = 0
        best_audio_id  = None
        best_audio_abr = 0
        for f in all_fmts:
            if f.get("vcodec", "none") != "none":
                continue
            acodec = f.get("acodec", "") or ""
            abr    = f.get("abr") or 0
            if "aac" in acodec.lower() and abr > best_aac_abr:
                best_aac_abr = abr
                best_aac_id  = f["format_id"]
            if abr > best_audio_abr:
                best_audio_abr = abr
                best_audio_id  = f["format_id"]

        # ── Formatos COMPAT: H264 + AAC nativos (sem conversão, instantâneos)
        # São os streams "progressive" do YouTube — vídeo+áudio num único ficheiro
        for f in all_fmts:
            vcodec = (f.get("vcodec") or "").lower()
            acodec = (f.get("acodec") or "").lower()
            height = f.get("height")
            if not height or not vcodec or vcodec == "none":
                continue
            # Só interessa se já tem áudio AAC e vídeo H264 juntos
            if "avc" not in vcodec and "h264" not in vcodec:
                continue
            if "aac" not in acodec and acodec not in ("mp4a", ""):
                continue
            if acodec in ("none", ""):
                continue
            if height in seen_compat:
                continue
            seen_compat.add(height)
            size = f.get("filesize") or f.get("filesize_approx") or 0
            formats.append({
                "id":      f["format_id"],
                "type":    "video",
                "label":   f"{height}p — Rápido ⚡ (H.264+AAC)",
                "height":  height,
                "ext":     "mp4",
                "size":    _fmt_size(size),
                "compat":  True,
                "needs_convert": False,
            })

        # ── Formatos QUALIDADE: melhor vídeo + merge áudio
        for f in all_fmts:
            vcodec = (f.get("vcodec") or "").lower()
            height = f.get("height")
            if not height or not vcodec or vcodec == "none":
                continue
            if f.get("acodec", "none") not in ("none", None, ""):
                continue  # já tem áudio, já foi adicionado acima
            if height in seen_quality:
                continue
            seen_quality.add(height)
            size = f.get("filesize") or f.get("filesize_approx") or 0

            # Usa AAC se disponível (evita conversão), senão usa melhor áudio
            audio_id = best_aac_id or best_audio_id
            needs_convert = not bool(best_aac_id)

            if audio_id:
                fmt_str = f"{f['format_id']}+{audio_id}"
            else:
                fmt_str = f["format_id"]

            formats.append({
                "id":      fmt_str,
                "type":    "video",
                "label":   f"{height}p — Alta Qualidade {'⚡' if not needs_convert else '🔄'}",
                "height":  height,
                "ext":     "mp4",
                "size":    _fmt_size(size),
                "compat":  False,
                "needs_convert": needs_convert,
            })

        # Áudio
        for f in all_fmts:
            if f.get("vcodec", "none") != "none":
                continue
            abr = f.get("abr") or 0
            ext = f.get("ext", "m4a")
            key = ("audio", int(abr), ext)
            if key in seen_compat:
                continue
            seen_compat.add(key)
            size = f.get("filesize") or f.get("filesize_approx") or 0
            if abr:
                formats.append({
                    "id":    f["format_id"],
                    "type":  "audio",
                    "label": f"Áudio {int(abr)}kbps {ext.upper()}",
                    "abr":   int(abr),
                    "ext":   ext,
                    "size":  _fmt_size(size),
                })

        # MP3 sempre disponível
        formats.append({
            "id":    "mp3",
            "type":  "audio",
            "label": "MP3 (melhor qualidade)",
            "abr":   320,
            "ext":   "mp3",
            "size":  "—",
        })

        # Ordena: vídeo por resolução desc, áudio por bitrate desc
        video_fmts = sorted([f for f in formats if f["type"] == "video"],
                            key=lambda x: x.get("height", 0), reverse=True)
        audio_fmts = sorted([f for f in formats if f["type"] == "audio"],
                            key=lambda x: x.get("abr", 0), reverse=True)

        thumbnail = info.get("thumbnail") or ""
        duration  = info.get("duration") or 0

        return jsonify({
            "title":     info.get("title", "Sem título"),
            "uploader":  info.get("uploader") or info.get("channel", ""),
            "duration":  _fmt_duration(duration),
            "thumbnail": thumbnail,
            "platform":  _detect_platform(url),
            "formats":   video_fmts + audio_fmts,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Iniciar download ────────────────────────────────────────────────────
@app.route("/api/download", methods=["POST"])
@login_required
def start_download():
    data = request.json or {}
    url           = (data.get("url") or "").strip()
    fmt_id        = data.get("format_id", "best")
    fmt_ext       = data.get("ext", "mp4")
    is_mp3        = fmt_id == "mp3"
    needs_convert = data.get("needs_convert", False)  # só True se não há AAC nativo

    if not url:
        return jsonify({"error": "URL em falta"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status":   "a processar",
        "progress": 0,
        "speed":    "",
        "eta":      "",
        "filename": None,
        "error":    None,
        "started":  time.time(),
    }

    def _progress_hook(d):
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                jobs[job_id]["progress"] = float(pct)
            except ValueError:
                pass
            jobs[job_id]["speed"]  = d.get("_speed_str", "").strip()
            jobs[job_id]["eta"]    = d.get("_eta_str", "").strip()
            jobs[job_id]["status"] = "a descarregar"
        elif d["status"] == "finished":
            jobs[job_id]["status"]   = "a processar"
            jobs[job_id]["progress"] = 99

    def _do_download():
        out_tmpl = str(DOWNLOAD_DIR / f"{job_id}_%(title).60s.%(ext)s")

        # Opções base com ffmpeg se disponível
        ffmpeg_opts = {}
        if FFMPEG_PATH:
            ffmpeg_opts["ffmpeg_location"] = FFMPEG_PATH

        if is_mp3:
            if not FFMPEG_PATH:
                jobs[job_id]["error"] = "MP3 requer ffmpeg. Abre o painel 'Atualizar yt-dlp' e clica em 'Instalar ffmpeg'."
                jobs[job_id]["status"] = "erro"
                return
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": out_tmpl,
                "quiet": True,
                "progress_hooks": [_progress_hook],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }],
                **ffmpeg_opts,
            }
        else:
            if FFMPEG_PATH:
                fmt = fmt_id
            else:
                fmt = "best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best"

            ydl_opts = {
                "format": fmt,
                "outtmpl": out_tmpl,
                "quiet": True,
                "progress_hooks": [_progress_hook],
                "noplaylist": True,
                "merge_output_format": "mp4",
                **ffmpeg_opts,
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                files = list(DOWNLOAD_DIR.glob(f"{job_id}_*"))
                if not files:
                    jobs[job_id]["error"]  = "Ficheiro não encontrado após download."
                    jobs[job_id]["status"] = "erro"
                    return

                src = files[0]

                # Verifica o áudio real do ficheiro descarregado
                # Se não for AAC → converte (só áudio, vídeo copia direto = rápido)
                should_convert = False
                if FFMPEG_PATH and not is_mp3:
                    try:
                        import re
                        probe = subprocess.run(
                            [FFMPEG_PATH, "-i", str(src)],
                            capture_output=True, text=True, timeout=10
                        )
                        # Verifica se o áudio é AAC
                        audio_line = [l for l in probe.stderr.splitlines() if "Audio:" in l]
                        if audio_line:
                            is_aac = "aac" in audio_line[0].lower()
                            should_convert = not is_aac
                    except Exception:
                        should_convert = needs_convert  # fallback ao flag original

                if should_convert and FFMPEG_PATH and not is_mp3:
                    jobs[job_id]["status"]   = "a converter áudio para AAC..."
                    jobs[job_id]["progress"] = 99
                    dst = src.with_name(src.stem + "_aac.mp4")

                    # Duração real para progresso
                    total_secs = 0
                    try:
                        import re
                        probe = subprocess.run([FFMPEG_PATH, "-i", str(src)],
                                               capture_output=True, text=True, timeout=10)
                        m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", probe.stderr)
                        if m:
                            total_secs = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
                    except Exception:
                        pass

                    # -vcodec copy = copia vídeo sem re-encode (instantâneo)
                    # só converte o áudio para AAC
                    cmd = [
                        FFMPEG_PATH, "-y",
                        "-i", str(src),
                        "-vcodec",   "copy",
                        "-acodec",   "aac",
                        "-ar",       "44100",
                        "-ac",       "2",
                        "-b:a",      "192k",
                        "-movflags", "+faststart",
                        "-progress", "pipe:1",
                        str(dst)
                    ]
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, encoding="utf-8", errors="replace"
                    )
                    for line in proc.stdout:
                        if line.startswith("out_time_ms="):
                            try:
                                secs = int(line.split("=")[1]) / 1_000_000
                                if total_secs > 0:
                                    pct = min(99, 50 + (secs / total_secs) * 49)
                                    jobs[job_id]["progress"] = round(pct, 1)
                                    jobs[job_id]["status"] = f"a converter áudio {int(secs)}s / {int(total_secs)}s"
                            except Exception:
                                pass
                    proc.wait()

                    if proc.returncode == 0 and dst.exists():
                        src.unlink()
                        jobs[job_id]["filename"] = dst.name
                    else:
                        jobs[job_id]["filename"] = src.name
                else:
                    jobs[job_id]["filename"] = src.name

                jobs[job_id]["status"]   = "pronto"
                jobs[job_id]["progress"] = 100
        except Exception as e:
            jobs[job_id]["error"]  = str(e)
            jobs[job_id]["status"] = "erro"

    threading.Thread(target=_do_download, daemon=True).start()
    return jsonify({"job_id": job_id})


# ─── API: Estado do ffmpeg ───────────────────────────────────────────────────
@app.route("/api/ffmpeg-status")
@login_required
def ffmpeg_status():
    return jsonify({
        "available": bool(FFMPEG_PATH),
        "path": FFMPEG_PATH or None,
    })


# ─── API: Estado do job ───────────────────────────────────────────────────────
@app.route("/api/status/<job_id>")
@login_required
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job não encontrado"}), 404
    return jsonify(job)


# ─── API: Servir ficheiro ─────────────────────────────────────────────────────
@app.route("/api/file/<job_id>")
@login_required
def serve_file(job_id):
    job = jobs.get(job_id)
    if not job or not job.get("filename"):
        return jsonify({"error": "Ficheiro não disponível"}), 404
    filepath = DOWNLOAD_DIR / job["filename"]
    if not filepath.exists():
        return jsonify({"error": "Ficheiro não encontrado no disco"}), 404
    return send_file(str(filepath), as_attachment=True,
                     download_name=job["filename"].split("_", 1)[-1])


# ─── API: Limpar ficheiros antigos ────────────────────────────────────────────
@app.route("/api/cleanup", methods=["POST"])
@login_required
def cleanup():
    count = 0
    cutoff = time.time() - 3600  # 1 hora
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            count += 1
    return jsonify({"deleted": count})


# ─── API: Versão atual do yt-dlp ─────────────────────────────────────────────
@app.route("/api/ytdlp-version")
@login_required
def ytdlp_version():
    ver = _get_ytdlp_version()

    # Tenta obter a versão mais recente do PyPI sem instalar nada
    latest = None
    try:
        import urllib.request
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=4) as r:
            data = json.loads(r.read())
            latest = data["info"]["version"]
    except Exception:
        pass

    # Normaliza versão tipo "2026.03.17" → "2026.3.17" para comparar
    def _norm(v):
        if not v:
            return v
        try:
            return ".".join(str(int(p)) for p in v.split("."))
        except Exception:
            return v

    cur_norm    = _norm(ver)
    latest_norm = _norm(latest)

    return jsonify({
        "current": ver,
        "latest":  latest,
        "outdated": bool(latest and cur_norm != latest_norm),
    })


# ─── API: Atualizar yt-dlp / instalar pacotes (streaming SSE) ────────────────
@app.route("/api/update-ytdlp")
@login_required
def update_ytdlp():
    """Server-Sent Events — envia linhas de output em tempo real."""
    # Pacotes a instalar (default: yt-dlp)
    packages_param = request.args.get("packages", "yt-dlp")
    packages = [p.strip() for p in packages_param.split(",") if p.strip()]

    def generate():
        yield f"data: 🔄 A instalar/atualizar: {', '.join(packages)}...\n\n"

        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + packages
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    yield f"data: {line}\n\n"
            proc.wait()

            if proc.returncode == 0:
                # Re-detecta ffmpeg se foi instalado
                if "imageio-ffmpeg" in packages:
                    _find_ffmpeg()
                # Recarrega yt-dlp se foi atualizado
                if "yt-dlp" in packages:
                    try:
                        import importlib, yt_dlp as _ydl, yt_dlp.version as _ydlv
                        importlib.reload(_ydlv)
                        importlib.reload(_ydl)
                        new_ver = _get_ytdlp_version()
                        yield f"data: ✅ Concluído! yt-dlp versão: {new_ver}\n\n"
                    except Exception:
                        yield f"data: ✅ Instalação concluída! Reinicia a app para ver a nova versão.\n\n"
                else:
                    yield f"data: ✅ Instalação concluída!\n\n"
                yield "data: __DONE__\n\n"
            else:
                yield "data: ❌ Erro durante a instalação (ver output acima)\n\n"
                yield "data: __ERROR__\n\n"

        except Exception as e:
            yield f"data: ❌ Exceção: {e}\n\n"
            yield "data: __ERROR__\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ─── API: Archive proxy — contorna bloqueio ISP ───────────────────────────────
@app.route("/api/reader/archive")
@login_required
def reader_archive():
    url = request.args.get("url", "").strip()
    if not url:
        return "URL em falta", 400

    import urllib.request, ssl, gzip, re

    # Tenta cada mirror do archive até um funcionar
    mirrors = [
        "https://archive.is",
        "https://archive.li",
        "https://archive.fo",
        "https://archive.vn",
        "https://archive.ph",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.google.com/",
    }

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    last_error = ""
    for mirror in mirrors:
        try:
            archive_url = f"{mirror}/{url}"
            req = urllib.request.Request(archive_url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                raw = resp.read()
                enc = resp.headers.get("Content-Encoding", "")
                final_url = resp.geturl()

            html = gzip.decompress(raw).decode("utf-8", errors="replace") if enc == "gzip" else raw.decode("utf-8", errors="replace")

            # Injeta CSS de leitura limpa e remove barra do archive
            clean_css = """<style>
              #HEADER, .TEXT-BLOCK > div:first-child, #TOOLBOX,
              #wm-ipp-base, .wb_highlight_all { display:none!important; }
              body { max-width:820px!important; margin:0 auto!important;
                font-family:Georgia,serif!important; font-size:18px!important;
                line-height:1.85!important; padding:24px!important;
                background:#fafaf8!important; color:#1a1a1a!important; }
              img { max-width:100%!important; height:auto!important; }
            </style>"""

            if "<head>" in html:
                html = html.replace("<head>", "<head>" + clean_css, 1)

            return html, 200, {
                "Content-Type": "text/html; charset=utf-8",
                "X-Archive-Mirror": mirror,
            }
        except Exception as e:
            last_error = str(e)
            continue

    # Nenhum mirror funcionou — tenta Wayback Machine como fallback
    try:
        wayback_api = f"http://archive.org/wayback/available?url={url}"
        req2 = urllib.request.Request(wayback_api, headers=headers)
        with urllib.request.urlopen(req2, context=ctx, timeout=10) as resp2:
            import json as _json
            data = _json.loads(resp2.read())
            snapshot = data.get("archived_snapshots", {}).get("closest", {})
            if snapshot.get("available") and snapshot.get("url"):
                # Redireciona para o snapshot do Wayback
                return redirect(snapshot["url"])
    except Exception:
        pass

    # Devolve página de erro
    return f"""<!DOCTYPE html><html><body style="font-family:monospace;padding:30px;background:#0d0f17;color:#dde1f0">
        <h2 style="color:#f5c542">⚠ Archive inacessível localmente</h2>
        <p style="color:#8890aa;margin:12px 0">
          O Archive.today está bloqueado pelo teu ISP.<br>
          Quando a app estiver num servidor online (Render/Railway) vai funcionar automaticamente.
        </p>
        <p style="margin-top:16px;color:#8890aa">Alternativas agora:</p>
        <div style="margin-top:12px;display:flex;flex-direction:column;gap:10px">
          <a href="https://web.archive.org/web/*/{url}" target="_blank"
            style="color:#fff;background:#6c63ff;padding:10px 18px;border-radius:8px;text-decoration:none;display:inline-block">
            ⏪ Tentar Wayback Machine
          </a>
          <a href="{url}" target="_blank"
            style="color:#6c63ff;text-decoration:none;font-size:13px">
            ↗ Abrir original
          </a>
        </div>
    </body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}


# ─── API: Reader — extrai artigo com Readability ─────────────────────────────
@app.route("/api/reader/extract", methods=["POST"])
@login_required
def reader_extract():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url or not url.startswith("http"):
        return jsonify({"error": "URL inválido"}), 400
    try:
        import urllib.request, ssl, gzip, re

        # Tenta instalar readability-lxml se não estiver disponível
        try:
            from readability import Document
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install",
                           "readability-lxml", "-q"], timeout=60)
            from readability import Document

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
            "Referer": "https://www.google.com/",
            "Upgrade-Insecure-Requests": "1",
        }

        req = urllib.request.Request(url, headers=headers)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            raw = resp.read()
            encoding = resp.headers.get("Content-Encoding", "")

        if encoding == "gzip":
            html = gzip.decompress(raw).decode("utf-8", errors="replace")
        else:
            html = raw.decode("utf-8", errors="replace")

        # Usa readability para extrair o artigo
        doc = Document(html)
        content = doc.summary(html_partial=True)
        title   = doc.title()

        # Limpa o conteúdo extraído
        # Remove scripts e styles residuais
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL|re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>',  '', content, flags=re.DOTALL|re.IGNORECASE)

        # Extrai byline e site name do HTML original
        byline = ""
        site_name = ""
        m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m: site_name = m.group(1)
        m = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m: byline = m.group(1)

        # Verifica se extraiu conteúdo suficiente
        text_len = len(re.sub(r'<[^>]+>', '', content))
        if text_len < 200:
            return jsonify({"error": f"Conteúdo insuficiente extraído ({text_len} chars) — o artigo pode estar bloqueado."}), 200

        return jsonify({
            "title":     title,
            "content":   content,
            "byline":    byline,
            "site_name": site_name,
            "length":    text_len,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 200


# ─── API: PDF Merge ───────────────────────────────────────────────────────────
@app.route("/api/pdf/merge", methods=["POST"])
@login_required
def pdf_merge():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Precisas de pelo menos 2 PDFs"}), 400
    try:
        import importlib
        try:
            import pypdf
            merger_lib = "pypdf"
        except ImportError:
            try:
                import PyPDF2 as pypdf
                merger_lib = "PyPDF2"
            except ImportError:
                subprocess.run([sys.executable, "-m", "pip", "install", "pypdf", "-q"], timeout=30)
                import pypdf
                merger_lib = "pypdf"

        merger = pypdf.PdfMerger()
        for f in files:
            merger.append(f)

        out_path = DOWNLOAD_DIR / f"merged_{uuid.uuid4().hex[:8]}.pdf"
        with open(out_path, "wb") as fout:
            merger.write(fout)
        merger.close()

        return send_file(str(out_path), as_attachment=True, download_name="merged.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _fmt_size(b):
    if not b:
        return "—"
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _fmt_duration(secs):
    if not secs:
        return ""
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _detect_platform(url):
    url = url.lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    if "instagram.com" in url:
        return "Instagram"
    if "facebook.com" in url or "fb.watch" in url:
        return "Facebook"
    if "tiktok.com" in url:
        return "TikTok"
    if "twitter.com" in url or "x.com" in url:
        return "X / Twitter"
    return "Web"

# ─── HTML: Login & Register pages ────────────────────────────────────────────
def _auth_base(title, body):
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — DropLoad</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#07080c;color:#dde1f0;font-family:'Syne',sans-serif;
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  background-image:radial-gradient(circle at 20% 20%,rgba(108,99,255,.1) 0,transparent 50%),
                   radial-gradient(circle at 80% 80%,rgba(255,101,132,.07) 0,transparent 50%)}}
.card{{background:#0e1018;border:1px solid #252835;border-radius:20px;
  padding:40px 36px;width:100%;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,.5)}}
.logo{{text-align:center;margin-bottom:28px}}
.logo-icon{{width:52px;height:52px;background:linear-gradient(135deg,#6c63ff,#ff6584);
  border-radius:14px;display:inline-flex;align-items:center;justify-content:center;
  font-size:26px;box-shadow:0 8px 24px rgba(108,99,255,.35);margin-bottom:10px}}
h1{{font-size:26px;letter-spacing:-0.5px;background:linear-gradient(135deg,#fff 40%,#6c63ff);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.subtitle{{color:#6b7090;font-family:'DM Mono',monospace;font-size:12px;margin-top:4px}}
.field{{margin-bottom:16px}}
label{{display:block;font-size:11px;font-family:'DM Mono',monospace;
  letter-spacing:1.5px;color:#6b7090;text-transform:uppercase;margin-bottom:6px}}
input{{width:100%;background:#161820;border:1px solid #252835;border-radius:10px;
  padding:12px 14px;color:#dde1f0;font-family:'DM Mono',monospace;font-size:14px;
  outline:none;transition:border-color .2s}}
input:focus{{border-color:#6c63ff;box-shadow:0 0 0 2px rgba(108,99,255,.15)}}
.btn{{width:100%;padding:14px;background:linear-gradient(135deg,#6c63ff,#8b5cf6);
  border:none;border-radius:10px;color:#fff;font-family:'Syne',sans-serif;
  font-weight:800;font-size:15px;cursor:pointer;transition:all .2s;margin-top:8px;
  box-shadow:0 4px 16px rgba(108,99,255,.3)}}
.btn:hover{{transform:translateY(-1px);box-shadow:0 6px 20px rgba(108,99,255,.4)}}
.error{{background:rgba(255,71,87,.08);border:1px solid rgba(255,71,87,.3);
  border-radius:8px;padding:10px 14px;color:#ff4757;font-size:13px;
  font-family:'DM Mono',monospace;margin-bottom:16px}}
.link{{text-align:center;margin-top:18px;font-size:13px;color:#6b7090;font-family:'DM Mono',monospace}}
.link a{{color:#6c63ff;text-decoration:none}}
.link a:hover{{text-decoration:underline}}
.divider{{height:1px;background:#252835;margin:20px 0}}
</style>
</head>
<body><div class="card">{body}</div></body>
</html>"""

def _login_html(error=None):
    err = f'<div class="error">⚠ {error}</div>' if error else ''
    body = f"""
<div class="logo">
  <div class="logo-icon">⬇</div>
  <h1>DropLoad</h1>
  <div class="subtitle">// acesso privado</div>
</div>
{err}
<form method="POST">
  <div class="field"><label>Utilizador</label>
    <input name="username" type="text" autocomplete="username" required autofocus></div>
  <div class="field"><label>Password</label>
    <input name="password" type="password" autocomplete="current-password" required></div>
  <button class="btn" type="submit">Entrar</button>
</form>
<div class="link">Tens convite? <a href="/register">Criar conta</a></div>"""
    return _auth_base("Login", body)

def _register_html(invite="", error=None):
    err = f'<div class="error">⚠ {error}</div>' if error else ''
    body = f"""
<div class="logo">
  <div class="logo-icon">⬇</div>
  <h1>Criar Conta</h1>
  <div class="subtitle">// registo por convite</div>
</div>
{err}
<form method="POST">
  <div class="field"><label>Código de Convite</label>
    <input name="invite" type="text" value="{invite}" placeholder="Cole o código aqui" required></div>
  <div class="divider"></div>
  <div class="field"><label>Utilizador</label>
    <input name="username" type="text" autocomplete="username" required minlength="3"
      placeholder="mín. 3 caracteres"></div>
  <div class="field"><label>Password</label>
    <input name="password" type="password" required minlength="6"
      placeholder="mín. 6 caracteres"></div>
  <div class="field"><label>Confirmar Password</label>
    <input name="password2" type="password" required minlength="6"></div>
  <button class="btn" type="submit">Criar Conta</button>
</form>
<div class="link"><a href="/login">← Voltar ao login</a></div>"""
    return _auth_base("Registo", body)

# Patch: usa as funções acima nas rotas de auth
import flask
_orig_login = app.view_functions.get('login_page')
_orig_register = app.view_functions.get('register_page')

# Substitui render das páginas de auth
@app.route("/login", endpoint="login_page_real", methods=["GET","POST"])
def login_page_real():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        users = _load_users()
        user = users.get(username)
        if user and user["password"] == _hash_pw(password):
            session["user"] = username
            session["role"] = user.get("role", "user")
            return redirect(request.args.get("next", "/"))
        error = "Utilizador ou password incorretos."
    return _login_html(error)

# Remove a rota antiga e usa a nova
app.view_functions['login_page'] = login_page_real

@app.route("/register", endpoint="register_page_real", methods=["GET","POST"])
def register_page_real():
    invite = request.args.get("invite", "")
    error = None
    if request.method == "POST":
        invite_in = (request.form.get("invite") or "").strip()
        username  = (request.form.get("username") or "").strip().lower()
        password  = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        if invite_in != INVITE_CODE:
            error = "Código de convite inválido."
        elif len(username) < 3:
            error = "Utilizador demasiado curto (mín. 3 caracteres)."
        elif len(password) < 6:
            error = "Password demasiado curta (mín. 6 caracteres)."
        elif password != password2:
            error = "As passwords não coincidem."
        else:
            users = _load_users()
            if username in users:
                error = "Este utilizador já existe."
            else:
                users[username] = {"password": _hash_pw(password),
                                   "role": "user",
                                   "created": time.strftime("%Y-%m-%d %H:%M")}
                _save_users(users)
                session["user"] = username
                session["role"] = "user"
                return redirect("/")
    return _register_html(invite, error)

app.view_functions['register_page'] = register_page_real

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _create_admin()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"🎬 DropLoad a correr em http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
