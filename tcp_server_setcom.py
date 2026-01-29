#!/usr/bin/env python3
"""
tcp_server_setcom.py

Patched: ramp downsampling + easing so total ramp duration respects JSON duration
while respecting a minimum per-step delay and using cosine/linear smoothing.
Keeps last_known_voltage memory, preemption, HTTP/SQLite/monitor behavior.
"""

import os
import sys
import time
import socket
import threading
import subprocess
import shlex
import logging
import signal
import sqlite3
import json
import http.server
import socketserver
import traceback
import re
import math

# ---------------- CONFIG ----------------
HOST = "0.0.0.0"
PORT = 4998

EXEC_PATH = r"C:\MIT\program\setcom"
EXEC_CWD = os.path.dirname(EXEC_PATH) or r"C:\MIT\program"

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
PID_FILE = os.path.join(BASE_DIR, "tcp_server_setcom.pid")
LOG_FILE = os.path.join(BASE_DIR, "tcp_server_setcom.log")
DB_FILE = os.path.join(BASE_DIR, "tcp_server_outbound.sqlite")

# Timeout for any individual SetCom call (seconds)
SUBPROCESS_TIMEOUT = 60

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8080

FLUSH_INTERVAL = 5
SUPERVISOR_CHECK = 1.0

# Ramp smoothing: "linear" or "cosine"
RAMP_SMOOTHING = "linear"

# Minimum per-step sleep between SetCom calls (seconds).
# Increase to reduce hammering setcom; decrease for higher fidelity (but risk Access Denied).
RAMP_STEP_DELAY_FLOOR = 0.08   # seconds; min sleep between steps

# ----------------------------------------

# logging
logger = logging.getLogger("tcp_server_setcom")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE)
fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(fh)
logger.addHandler(logging.StreamHandler(sys.stdout))

_graceful_shutdown = False

def write_pidfile():
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        try:
            with open(PID_FILE + ".meta", "w") as m:
                m.write(f"pid={os.getpid()} ts={time.time()} cwd={os.getcwd()} sysexec={sys.executable}\n")
        except Exception:
            logger.debug("Failed to write pidfile.meta")
        logger.info("Wrote pidfile %s (pid=%s)", PID_FILE, os.getpid())
    except Exception:
        logger.exception("Failed to write pidfile")

def remove_pidfile(graceful=True):
    try:
        if not graceful:
            logger.warning("Non-graceful shutdown: leaving pidfile in place for debugging: %s", PID_FILE)
            return
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            logger.info("Removed pidfile")
        try:
            if os.path.exists(PID_FILE + ".meta"):
                os.remove(PID_FILE + ".meta")
        except Exception:
            pass
    except Exception:
        logger.exception("Failed removing pidfile")

# resolver
def resolve_executable(preferred):
    logger.info("Resolving EXEC_PATH from configured: %s", preferred)
    candidates = [preferred]
    try:
        if os.path.exists(preferred) and os.path.isfile(preferred):
            return os.path.abspath(preferred)
    except Exception:
        pass
    base = preferred
    for ext in (".exe", ".bat", ".cmd"):
        p = base + ext
        candidates.append(p)
        try:
            if os.path.exists(p) and os.path.isfile(p):
                return os.path.abspath(p)
        except Exception:
            pass
    base_dir = os.path.dirname(preferred) or EXEC_CWD or ""
    basename = os.path.basename(preferred).lower()
    logger.info("Scanning directory for candidates: %s (basename=%s)", base_dir, basename)
    try:
        for fname in sorted(os.listdir(base_dir)):
            if fname.lower().startswith(basename):
                p = os.path.join(base_dir, fname)
                candidates.append(p)
                if os.path.isfile(p):
                    logger.info("Found candidate via dir-scan: %s", p)
                    return os.path.abspath(p)
    except Exception as e:
        logger.debug("Directory scan failed: %s", e)
    try:
        import shutil
        which = shutil.which(os.path.basename(preferred))
        if which:
            candidates.append(which)
            if os.path.isfile(which):
                return os.path.abspath(which)
    except Exception:
        pass
    logger.warning("Could not resolve executable. Candidates tried (first 10): %s", candidates[:10])
    return None

RESOLVED_EXEC = resolve_executable(EXEC_PATH)
if RESOLVED_EXEC:
    logger.info("Resolved executable: %s", RESOLVED_EXEC)
else:
    logger.error("Failed to resolve executable from configured EXEC_PATH: %s", EXEC_PATH)
    logger.error("Check that the file exists (e.g. SetCom.exe) and restart the server after fixing.")

# ---------- persistent queue (SQLite) ----------
class OutboundDB:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        return conn

    def _init_db(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cmd TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        sent_at INTEGER
                    )""")
        conn.commit()
        conn.close()

    def enqueue(self, cmd_text):
        ts = int(time.time())
        with self.lock:
            conn = self._connect()
            c = conn.cursor()
            c.execute("INSERT INTO queue (cmd, created_at) VALUES (?, ?)", (cmd_text, ts))
            conn.commit()
            last_id = c.lastrowid
            conn.close()
        logger.info("Enqueued cmd id=%s: %s", last_id, cmd_text)
        return last_id

    def get_unsent(self, limit=100):
        with self.lock:
            conn = self._connect()
            c = conn.cursor()
            c.execute("SELECT id, cmd FROM queue WHERE sent_at IS NULL ORDER BY id ASC LIMIT ?", (limit,))
            rows = c.fetchall()
            conn.close()
            return rows

    def mark_sent(self, row_id):
        ts = int(time.time())
        with self.lock:
            conn = self._connect()
            c = conn.cursor()
            c.execute("UPDATE queue SET sent_at = ? WHERE id = ?", (ts, row_id))
            conn.commit()
            conn.close()
        logger.info("Marked cmd id=%s sent", row_id)

db = OutboundDB(DB_FILE)

# ---------- runtime last-known state ----------
last_known_voltage_lock = threading.Lock()
last_known_voltage = None  # integer or None

def _update_last_known_voltage_from_value(value):
    global last_known_voltage
    try:
        v = int(value)
    except Exception:
        return
    with last_known_voltage_lock:
        last_known_voltage = v
    logger.debug("Updated last_known_voltage -> %s", v)

# parse 'volt' from SetCom stdout (best-effort)
_vol_regex = re.compile(r"volt\s*[:=]?\s*(-?\d+)", re.IGNORECASE)

# ---------- shared active subprocess handle ----------
active_proc_lock = threading.Lock()
active_proc = None  # subprocess.Popen or None

def _set_active_proc(proc):
    global active_proc
    with active_proc_lock:
        active_proc = proc

def _clear_active_proc():
    global active_proc
    with active_proc_lock:
        active_proc = None

def kill_active_proc(timeout=1.0):
    """Kill the active subprocess (if any) and wait up to timeout for it to exit."""
    global active_proc
    with active_proc_lock:
        proc = active_proc
    if not proc:
        return False
    try:
        logger.info("Killing active SetCom proc pid=%s", getattr(proc, "pid", "<unknown>"))
        try:
            proc.terminate()
        except Exception:
            logger.exception("proc.terminate() failed; attempting kill()")
            try:
                proc.kill()
            except Exception:
                logger.exception("proc.kill() also failed")
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Active proc did not exit after terminate; sending kill()")
            try:
                proc.kill()
                proc.wait(timeout=timeout)
            except Exception:
                logger.exception("Failed to kill active proc")
        logger.info("Active proc killed")
    except Exception:
        logger.exception("Exception while killing active proc")
    finally:
        _clear_active_proc()
    return True

# ---------- process start + wait helper (interruptible) ----------
def _start_proc_and_wait(cmd_tokens, timeout=SUBPROCESS_TIMEOUT):
    """
    Start subprocess.Popen and wait for completion with timeout.
    Stores proc in active_proc so callers can kill it (preemption).
    Returns (rc, stdout, stderr)
    Also updates last_known_voltage when command contains an explicit voltage or when
    stdout contains a volt line.
    """
    global last_known_voltage

    if not RESOLVED_EXEC or not os.path.exists(RESOLVED_EXEC):
        msg = f"EXEC_PATH not found/resolved: {RESOLVED_EXEC}"
        logger.error(msg)
        return 252, "", msg

    cmd = [RESOLVED_EXEC] + [str(t) for t in cmd_tokens]
    logger.info("Starting SetCom: %s", " ".join(shlex.quote(p) for p in cmd))

    # If the command explicitly sets a numeric 3rd token, update last_known_voltage immediately (best-effort).
    if len(cmd_tokens) >= 3:
        try:
            maybe_v = int(cmd_tokens[2])
            with last_known_voltage_lock:
                last_known_voltage = maybe_v
            logger.debug("Pre-update last_known_voltage from explicit token -> %s", maybe_v)
        except Exception:
            pass

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(RESOLVED_EXEC) or EXEC_CWD,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    except Exception as e:
        logger.exception("Failed to Popen SetCom: %s", e)
        return 254, "", str(e)

    _set_active_proc(proc)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            rc = proc.returncode
            # best-effort parse for 'volt' in stdout
            try:
                txt = (stdout or "") + "\n" + (stderr or "")
                m = _vol_regex.search(txt)
                if m:
                    v = int(m.group(1))
                    with last_known_voltage_lock:
                        last_known_voltage = v
                    logger.debug("Updated last_known_voltage from SetCom stdout -> %s", v)
            except Exception:
                logger.debug("No voltage parsed from stdout")
            logger.info("SetCom finished pid=%s rc=%s stdout_len=%d stderr_len=%d", proc.pid, rc, len(stdout or ""), len(stderr or ""))
            return rc, (stdout or ""), (stderr or "")
        except subprocess.TimeoutExpired:
            logger.warning("SetCom timed out (pid=%s); killing", proc.pid)
            try:
                proc.kill()
            except Exception:
                logger.exception("Failed to kill timed-out SetCom")
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except Exception:
                stdout, stderr = "", ""
            return 253, (stdout or ""), (stderr or "")
    finally:
        _clear_active_proc()

# ---------- easing & sampling helpers ----------
def _ease_sample_sequence(start_v, end_v, smoothing, max_samples=None):
    """
    Return a list of integer voltages (including start and end) according to smoothing.
    smoothing: "linear" or "cosine"
    max_samples: if provided, downsample to at most max_samples samples (>=2)
    """
    # produce full eased float samples at one-per-integer-step resolution
    total_steps = abs(end_v - start_v)
    if total_steps == 0:
        return [end_v]

    def linear(t): return t
    def cosine(t): return (1 - math.cos(math.pi * t)) / 2

    fn = linear if smoothing == "linear" else cosine

    samples = []
    for i in range(total_steps + 1):
        t = i / float(total_steps)
        eased = fn(t)
        v_float = start_v + (end_v - start_v) * eased
        samples.append(int(round(v_float)))

    # collapse consecutive duplicates
    seq = []
    prev = None
    for v in samples:
        if v != prev:
            seq.append(v)
            prev = v

    # ensure start and end are present
    if seq[0] != start_v:
        seq.insert(0, start_v)
    if seq[-1] != end_v:
        seq.append(end_v)

    # downsample if requested (keep endpoints)
    if max_samples is not None and max_samples >= 2 and len(seq) > max_samples:
        N = max_samples
        out = []
        for j in range(N):
            idx = int(round(j * (len(seq) - 1) / float(N - 1)))
            out.append(seq[idx])
        # remove consecutive duplicates again
        final = []
        prev = None
        for v in out:
            if v != prev:
                final.append(v)
                prev = v
        # ensure endpoints
        if final[0] != start_v:
            final.insert(0, start_v)
        if final[-1] != end_v:
            final.append(end_v)
        seq = final

    return seq

# ---------- ramp control ----------
ramp_lock = threading.Lock()
ramp_thread = None
ramp_cancel_event = threading.Event()

def _ramp_runner(com, addr, start_v, end_v, duration_ms, offset_ms=0):
    """
    Run server-managed ramp. Uses _start_proc_and_wait for each step so active_proc is trackable.
    Checks ramp_cancel_event frequently and aborts promptly (killing any in-flight SetCom).
    Ensures total ramp duration approximates duration_ms by downsampling steps if necessary.
    """
    global ramp_thread, last_known_voltage
    try:
        logger.info("Ramp runner start: com=%s addr=%s start=%s end=%s dur=%sms offset=%sms",
                    com, addr, start_v, end_v, duration_ms, offset_ms)

        # Resolve -1 using last_known_voltage (no SetCom query)
        if start_v == -1:
            with last_known_voltage_lock:
                if last_known_voltage is not None:
                    start_v = last_known_voltage
                    logger.info("Using last_known_voltage for -1 -> %s", start_v)
                else:
                    logger.info("last_known_voltage unknown; defaulting start_v to 0")
                    start_v = 0

        # offset wait
        if offset_ms and offset_ms > 0:
            wait_s = offset_ms / 1000.0
            logger.info("Offset wait %0.3fs", wait_s)
            slept = 0.0
            while slept < wait_s:
                if ramp_cancel_event.is_set():
                    logger.info("Ramp cancelled during offset wait")
                    return
                to_sleep = min(0.1, wait_s - slept)
                time.sleep(to_sleep)
                slept += to_sleep

        # If no change, set final and return
        if end_v == start_v:
            logger.info("No-op ramp, setting final %s", end_v)
            kill_active_proc()
            _start_proc_and_wait([str(com), str(addr), str(end_v)], timeout=SUBPROCESS_TIMEOUT)
            with last_known_voltage_lock:
                last_known_voltage = end_v
            return

        # --- new: build eased sequence and downsample to respect duration & floor ---
        desired_duration_s = max(0.0, duration_ms / 1000.0)
        # maximum number of intervals allowed so interval >= floor
        max_intervals = max(1, int(math.floor(desired_duration_s / RAMP_STEP_DELAY_FLOOR)))
        # Build sequence including start & end. max_samples = max_intervals + 1 (samples = intervals+1)
        seq = _ease_sample_sequence(start_v, end_v, RAMP_SMOOTHING, max_samples=(max_intervals + 1))

        # recompute intervals and per-step interval_s so sum == desired_duration_s
        intervals = max(1, len(seq) - 1)
        # if desired duration is zero (instant), interval_s becomes 0
        interval_s = desired_duration_s / intervals if desired_duration_s > 0 else 0.0

        # As a safety, if interval_s < floor (shouldn't happen due to downsampling), enforce floor
        if interval_s < RAMP_STEP_DELAY_FLOOR and desired_duration_s > 0:
            logger.debug("Computed interval %0.4fs < floor %0.4fs; enforcing floor (actual duration will be longer)",
                         interval_s, RAMP_STEP_DELAY_FLOOR)
            interval_s = RAMP_STEP_DELAY_FLOOR

        logger.info("Planned ramp: %d distinct steps interval=%0.3fs requested=%0.3fs",
                    len(seq), interval_s, desired_duration_s)

        # ensure no in-flight proc
        kill_active_proc()
        # baseline: set start value
        rc, out, err = _start_proc_and_wait([str(com), str(addr), str(seq[0])], timeout=min(5, SUBPROCESS_TIMEOUT))
        if rc == 0:
            with last_known_voltage_lock:
                last_known_voltage = seq[0]
        else:
            logger.warning("Baseline set failed rc=%s err=%s", rc, err)

        # iterate sequence
        for idx in range(1, len(seq)):
            if ramp_cancel_event.is_set():
                logger.info("Ramp cancelled before step %d/%d", idx, len(seq)-1)
                return
            v = seq[idx]
            # adapt per-step timeout to expected pace (give some headroom)
            per_step_timeout = max(10.0, interval_s * 2.0) if interval_s > 0 else max(10.0, SUBPROCESS_TIMEOUT)
            rc, out, err = _start_proc_and_wait([str(com), str(addr), str(v)], timeout=min(per_step_timeout, SUBPROCESS_TIMEOUT))
            logger.info("Ramp step %d/%d -> %s rc=%s", idx, len(seq)-1, v, rc)
            if rc == 0:
                with last_known_voltage_lock:
                    last_known_voltage = v

            # sleep for interval_s but check cancel event frequently
            slept = 0.0
            while slept < interval_s:
                if ramp_cancel_event.is_set():
                    logger.info("Ramp cancelled during sleep after value %s", v)
                    kill_active_proc()
                    return
                to_sleep = min(0.1, interval_s - slept)
                time.sleep(to_sleep)
                slept += to_sleep

        # final set to ensure exact end value (if last sample wasn't exactly end)
        if seq[-1] != end_v:
            kill_active_proc()
            rc, out, err = _start_proc_and_wait([str(com), str(addr), str(end_v)], timeout=SUBPROCESS_TIMEOUT)
            if rc == 0:
                with last_known_voltage_lock:
                    last_known_voltage = end_v

        logger.info("Ramp completed to %s", end_v)

    except Exception:
        logger.exception("Exception in ramp runner")
    finally:
        with ramp_lock:
            ramp_thread = None
            ramp_cancel_event.clear()

def run_setcom(tokens):
    """
    Central policy: new commands preempt running ramps & in-flight SetCom processes.
    - Commands must be either:
        - instant: 3 tokens -> <com> <addr> <voltage>
        - ramp:    4 tokens -> <com> <addr> <end_voltage> <duration_ms>
    - For ramps the start value will be resolved from `last_known_voltage` (-1 marker).

    This version enforces the simpler protocol (single voltage or end+duration) and
    returns explicit errors for invalid input while keeping aggressive preemption.
    """
    global ramp_thread, ramp_cancel_event, last_known_voltage

    tokens = [str(t) for t in tokens]
    logger.info("run_setcom tokens: %s", tokens)

    # Accept only 3 (instant) or 4 (ramp) tokens
    if len(tokens) not in (3, 4):
        msg = f"Invalid command format: expected 3 tokens (instant) or 4 tokens (ramp); got {len(tokens)}"
        logger.warning(msg)
        return 252, "", msg

    # Expect the first two tokens to be 'com3' and '1' (case-insensitive for COM)
    if tokens[0].lower() != "com3" or tokens[1] != "1":
        msg = "Invalid command prefix: expected first two tokens 'com3 1'"
        logger.warning(msg + f" (got: {tokens[0]} {tokens[1]})")
        return 253, "", msg

    # PREEMPT: aggressively cancel running ramp and kill any in-flight SetCom
    with ramp_lock:
        if ramp_thread and ramp_thread.is_alive():
            logger.info("Preempting existing ramp: signalling cancel")
            ramp_cancel_event.set()

            waited = 0.0
            wait_total = 1.0
            interval = 0.05
            while ramp_thread.is_alive() and waited < wait_total:
                kill_active_proc(timeout=0.2)
                time.sleep(interval)
                waited += interval

            try:
                ramp_thread.join(timeout=0.2)
            except Exception:
                pass

            if ramp_thread and ramp_thread.is_alive():
                logger.warning("Ramp thread didn't stop promptly after preemption (waited %.2fs); proceeding anyway", waited)
            else:
                logger.info("Ramp thread stopped after preemption (waited %.2fs)", waited)

        ramp_cancel_event.clear()
        kill_active_proc(timeout=0.1)

    # Instant command: <com> <addr> <voltage>
    if len(tokens) == 3:
        try:
            v = int(tokens[2])
        except Exception:
            msg = f"Invalid voltage value: {tokens[2]}"
            logger.warning(msg)
            return 254, "", msg
        # update last known voltage and execute immediately
        with last_known_voltage_lock:
            last_known_voltage = v
        logger.info("Executing instant command (preempt): %s %s %s", tokens[0], tokens[1], v)
        rc, out, err = _start_proc_and_wait(tokens, timeout=SUBPROCESS_TIMEOUT)
        logger.info("Instant completed rc=%s", rc)
        return rc, out or "", err or ""

    # Ramp command: <com> <addr> <end_voltage> <duration_ms>
    try:
        end_v = int(tokens[2])
        duration_ms = int(tokens[3])
    except Exception:
        msg = "Invalid ramp arguments: end_voltage and duration_ms must be integers"
        logger.warning(msg)
        return 254, "", msg

    try:
        com_num = int(tokens[0]) if str(tokens[0]).lstrip("+-").isdigit() else tokens[0]
    except Exception:
        com_num = tokens[0]
    addr_str = tokens[1]
    start_v = -1  # use last_known_voltage in runner
    offset_ms = 0

    logger.info("Starting ramp thread com=%s addr=%s start=%s end=%s dur=%sms offset=%sms", com_num, addr_str, start_v, end_v, duration_ms, offset_ms)
    ramp_cancel_event.clear()
    ramp_thread = threading.Thread(target=_ramp_runner, args=(com_num, addr_str, start_v, end_v, duration_ms, offset_ms), daemon=True)
    ramp_thread.start()
    return 0, f"ramp started {start_v}->{end_v} dur={duration_ms} offset={offset_ms}", ""

# ---------- TCP handler for Zoom Room messages ----------
stop_event = threading.Event()

def handle_client(conn, addr):
    try:
        logger.info("Client connected: %s", addr)
        conn.settimeout(1.0)
        buf = b""
        while not stop_event.is_set():
            try:
                data = conn.recv(4096)
                if not data:
                    logger.info("Connection closed by %s", addr)
                    break
                buf += data
                while b'\r' in buf or b'\n' in buf:
                    if b'\r' in buf:
                        line, _, buf = buf.partition(b'\r')
                    else:
                        line, _, buf = buf.partition(b'\n')
                    text = line.decode('utf-8', errors='ignore').strip()
                    if not text:
                        continue
                    logger.info("Received from %s: %s", addr, text)
                    tokens = text.split()
                    rc, out, err = run_setcom(tokens)
                    if rc == 0:
                        reply = f"OK:{rc}\n"
                    else:
                        short = (err or out or "")[:300].replace("\n"," ")
                        reply = f"ERR:{rc}:{short}\n"
                    try:
                        conn.sendall(reply.encode("utf-8"))
                    except Exception as e:
                        logger.warning("Failed to send response to %s: %s", addr, e)
            except socket.timeout:
                continue
            except Exception:
                logger.exception("Receive error from %s", addr)
                break
    finally:
        try:
            conn.close()
        except Exception:
            pass
        logger.info("Client handler exiting for %s", addr)

def server_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(5)
    logger.info("Listening on %s:%d (configured EXEC_PATH=%s) resolved=%s", HOST, PORT, EXEC_PATH, RESOLVED_EXEC)
    try:
        while not stop_event.is_set():
            try:
                s.settimeout(1.0)
                conn, addr = s.accept()
                t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                logger.exception("Accept loop error")
                time.sleep(0.5)
    finally:
        try:
            s.close()
        except Exception:
            pass
        logger.info("Server loop exiting")

# ---------- HTTP control endpoint ----------
class ControlHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.debug("HTTP: " + (fmt % args))

    def _send_json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            if self.path != "/send":
                self._send_json({"error": "not found"}, code=404)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b""
            payload = json.loads(raw.decode("utf-8"))
            cmd = payload.get("cmd") or payload.get("command")
            if not cmd:
                self._send_json({"error": "missing 'cmd' in JSON"}, code=400)
                return
            row_id = db.enqueue(cmd)
            tokens = cmd.split()
            rc, out, err = run_setcom(tokens)
            if rc == 0:
                db.mark_sent(row_id)
                self._send_json({"ok": True, "id": row_id, "rc": rc, "stdout": out})
            else:
                self._send_json({"ok": False, "id": row_id, "rc": rc, "stderr": err}, code=500)
        except Exception:
            logger.exception("HTTP /send handler exception")
            self._send_json({"error": "server-error", "exception": traceback.format_exc()}, code=500)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

def start_http_control(stop_evt):
    while not stop_evt.is_set():
        try:
            logger.info("Starting HTTP control on %s:%d", HTTP_HOST, HTTP_PORT)
            httpd = ThreadedTCPServer((HTTP_HOST, HTTP_PORT), ControlHandler)
            httpd.timeout = 1
            try:
                while not stop_evt.is_set():
                    try:
                        httpd.handle_request()
                    except Exception:
                        logger.exception("HTTP handler crashed; continuing")
            finally:
                try:
                    httpd.server_close()
                except Exception:
                    pass
                logger.info("HTTP control stopped (normal)")
        except Exception:
            logger.exception("HTTP control crashed at top level; restarting in 2s")
            for _ in range(2):
                if stop_evt.is_set():
                    break
                time.sleep(1)

# ---------- Queue flusher thread (robust) ----------
def flush_persisted_queue_loop(stop_evt):
    logger.info("Starting queue flusher thread (interval %ds)", FLUSH_INTERVAL)
    try:
        while not stop_evt.is_set():
            try:
                rows = db.get_unsent(limit=50)
                if rows:
                    logger.info("Found %d queued commands to flush", len(rows))
                for row_id, cmd in rows:
                    try:
                        tokens = cmd.split()
                        rc, out, err = run_setcom(tokens)
                        if rc == 0:
                            db.mark_sent(row_id)
                        else:
                            logger.warning("Queued cmd id=%s failed rc=%s; will retry later: %s", row_id, rc, cmd)
                    except Exception:
                        logger.exception("Exception while flushing queued cmd id=%s", row_id)
                for _ in range(FLUSH_INTERVAL):
                    if stop_evt.is_set():
                        break
                    time.sleep(1)
            except Exception:
                logger.exception("Queue flusher top-level exception; continuing loop")
                for _ in range(2):
                    if stop_evt.is_set():
                        break
                    time.sleep(1)
    finally:
        logger.info("Queue flusher exiting")

# ---------- Supervisor for background threads ----------
def supervise_background_tasks(stop_evt):
    threads = {}
    def start_thread(name, target, *args):
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        threads[name] = t
        logger.info("Started background thread: %s (ident=%s)", name, getattr(t, "ident", None))
        return t

    start_thread("http", start_http_control, stop_evt)
    start_thread("flusher", flush_persisted_queue_loop, stop_evt)

    try:
        while not stop_evt.is_set():
            for name, t in list(threads.items()):
                if not t.is_alive():
                    logger.warning("Background thread '%s' died; restarting", name)
                    if name == "http":
                        start_thread("http", start_http_control, stop_evt)
                    elif name == "flusher":
                        start_thread("flusher", flush_persisted_queue_loop, stop_evt)
            time.sleep(SUPERVISOR_CHECK)
    except Exception:
        logger.exception("Background supervisor exception")
    finally:
        logger.info("Background supervisor exiting")

# ---------- shutdown and signal diagnostics ----------
def _log_signal_debug_info(signum):
    try:
        ppid = os.getppid()
        logger.info("Signal handler invoked: signum=%s pid=%s ppid=%s", signum, os.getpid(), ppid)
        if os.name == "nt":
            try:
                r = subprocess.run(['tasklist', '/FI', f'PID eq {ppid}', '/FO', 'LIST'],
                                   capture_output=True, text=True, timeout=5)
                logger.info("Parent process info:\n%s", r.stdout.strip())
            except Exception:
                logger.exception("Failed to get parent process info via tasklist")
        else:
            try:
                r = subprocess.run(['ps', '-p', str(ppid), '-o', 'pid,ppid,cmd'], capture_output=True, text=True, timeout=5)
                logger.info("Parent process info:\n%s", r.stdout.strip())
            except Exception:
                logger.exception("Failed to get parent process info via ps")
        try:
            stderr_path = os.path.join(BASE_DIR, "server_stderr.log")
            if os.path.exists(stderr_path):
                with open(stderr_path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    pos = f.tell()
                    start = max(0, pos - 16*1024)
                    f.seek(start)
                    tail = f.read().decode(errors='replace')
                logger.info("server_stderr tail on signal:\n%s", tail)
        except Exception:
            logger.exception("Failed to capture server_stderr tail")
    except Exception:
        logger.exception("Failed while logging debug info for signal")

def shutdown(signum=None, frame=None):
    global _graceful_shutdown
    logger.info("Shutdown requested (signal=%s)", signum)
    _log_signal_debug_info(signum)
    _graceful_shutdown = True
    stop_event.set()
    with ramp_lock:
        ramp_cancel_event.set()
    kill_active_proc(timeout=0.5)

# ---------- main ----------
if __name__ == "__main__":
    try:
        signal.signal(signal.SIGINT, shutdown)
        try:
            signal.signal(signal.SIGTERM, shutdown)
        except Exception:
            pass
    except Exception:
        pass

    write_pidfile()

    bg_supervisor = threading.Thread(target=supervise_background_tasks, args=(stop_event,), daemon=True)
    bg_supervisor.start()

    try:
        while not stop_event.is_set():
            try:
                logger.info("Starting server_loop() (supervised cycle)")
                server_loop()
                if not stop_event.is_set():
                    logger.warning("server_loop returned unexpectedly; restarting in 1 second")
                    time.sleep(1)
            except Exception:
                logger.exception("server_loop crashed; restarting in 2 seconds")
                time.sleep(2)
    finally:
        logger.info("Shutting down: waiting for background threads to exit")
        stop_event.set()
        time.sleep(0.5)
        remove_pidfile(graceful=_graceful_shutdown)
        logger.info("Stopped")