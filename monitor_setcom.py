# monitor_setcom.py  (drop-in with live stdout/stderr streaming)
"""
Reliable monitor for tcp_server_setcom.py with live streaming of the server's stdout/stderr.

Edit the three absolute-path variables below before running:
 - PYTHON_EXE: full path to python.exe you want to use
 - SCRIPT: full path to tcp_server_setcom.py (this monitor must run the server script, not SetCom.exe)
 - PID_FILE: full path to the pid file the server writes (must match server's PID_FILE)

Run:
    python monitor_setcom.py
"""
import os
import sys
import time
import subprocess
import logging
import signal
import threading
from typing import Optional, IO

# ---- EDIT THESE TO ABSOLUTE PATHS ----
# Path to python interpreter to run the server script with
PYTHON_EXE = sys.executable
# Path to the Python server script (this monitor must run the server script, not SetCom.exe)
SCRIPT = r"C:\MIT\program\Scratch - Titone\tcp_server_setcom.py"
# Path to the PID file the server will write (server writes this path by default)
PID_FILE = r"C:\MIT\program\Scratch - Titone\tcp_server_setcom.pid"
# -------------------------------------

LOG_FILE = r"C:\MIT\program\Scratch - Titone\monitor_setcom.log"
SERVER_STDOUT = r"C:\MIT\program\Scratch - Titone\server_stdout.log"
SERVER_STDERR = r"C:\MIT\program\Scratch - Titone\server_stderr.log"

CHECK_INTERVAL = 5          # seconds between alive checks
PID_WAIT_SECONDS = 12       # how long to wait for pidfile after start
START_GRACE = 2             # seconds to wait then check if process died quickly
MAX_BACKOFF = 300           # max backoff between failed starts (seconds)

# logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("monitor_setcom")
logger.addHandler(logging.StreamHandler(sys.stdout))

stop_requested = False

def handle_sigint(sig, frame):
    global stop_requested
    logger.info("Signal received: %s; shutting down monitor", sig)
    stop_requested = True

signal.signal(signal.SIGINT, handle_sigint)
try:
    signal.signal(signal.SIGTERM, handle_sigint)
except Exception:
    pass

def read_pidfile() -> Optional[int]:
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as f:
                data = f.read().strip()
                if data:
                    return int(data)
    except Exception as e:
        logger.debug("read_pidfile error: %s", e)
    return None

def pid_is_running(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        # On Windows os.kill(pid, 0) raises OSError if not running
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def _stream_reader_thread(stream: IO[str], out_fd: Optional[IO[bytes]], dest_name: str):
    """
    Read lines from stream (text mode) and write them to both sys.stdout/sys.stderr and to out_fd (binary).
    Stops when stream.read() returns empty (EOF).
    """
    try:
        while True:
            line = stream.readline()
            if line == "":
                break
            try:
                # Print to monitor console with prefix so it's clear which stream it is
                if dest_name == "STDOUT":
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    sys.stderr.write(line)
                    sys.stderr.flush()
            except Exception:
                pass
            if out_fd:
                try:
                    out_fd.write(line.encode("utf-8", errors="replace"))
                    out_fd.flush()
                except Exception:
                    # if log file cannot be written, ignore but don't crash reader
                    pass
    except Exception:
        logger.exception("Exception in stream reader for %s", dest_name)

def start_server_process():
    """
    Launch the server script using PYTHON_EXE and SCRIPT.
    Captures stdout/stderr, writes to SERVER_STDOUT/SERVER_STDERR, and streams them live to console.
    Returns (Popen, stdout_file_handle, stderr_file_handle, thread_stdout, thread_stderr)
    """
    if not os.path.isfile(SCRIPT):
        logger.error("Server script not found: %s", SCRIPT)
        return None, None, None, None, None

    logger.info("Starting server script: %s", SCRIPT)
    cmd = [PYTHON_EXE, SCRIPT]

    # open log files in append-binary mode
    out_fd = None
    err_fd = None
    try:
        out_fd = open(SERVER_STDOUT, "ab")
    except Exception as e:
        logger.exception("Failed to open SERVER_STDOUT '%s': %s", SERVER_STDOUT, e)
        out_fd = None
    try:
        err_fd = open(SERVER_STDERR, "ab")
    except Exception as e:
        logger.exception("Failed to open SERVER_STDERR '%s': %s", SERVER_STDERR, e)
        err_fd = None

    try:
        # Text mode pipes so we can readline easily
        # On Windows do not set close_fds=True (it is not supported the same way)
        popen_kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if os.name == "nt":
            # Avoid CREATE_NEW_CONSOLE here; piping is fine and we want to capture output.
            p = subprocess.Popen(cmd, **popen_kwargs)
        else:
            p = subprocess.Popen(cmd, close_fds=True, **popen_kwargs)
        logger.info("Launched process pid=%s", p.pid)
    except Exception as e:
        logger.exception("Failed to launch server: %s", e)
        if out_fd:
            out_fd.close()
        if err_fd:
            err_fd.close()
        return None, None, None, None, None

    # Start reader threads to stream child's stdout/stderr to monitor console + log files
    t_out = None
    t_err = None
    try:
        if p.stdout:
            t_out = threading.Thread(target=_stream_reader_thread, args=(p.stdout, out_fd, "STDOUT"), daemon=True)
            t_out.start()
        if p.stderr:
            t_err = threading.Thread(target=_stream_reader_thread, args=(p.stderr, err_fd, "STDERR"), daemon=True)
            t_err.start()
    except Exception:
        logger.exception("Failed starting stream reader threads")

    return p, out_fd, err_fd, t_out, t_err

def _close_handles_and_join(popen, out_fd, err_fd, t_out, t_err):
    # join reader threads (they exit when pipes close), close log files
    try:
        if t_out and t_out.is_alive():
            t_out.join(timeout=0.5)
    except Exception:
        pass
    try:
        if t_err and t_err.is_alive():
            t_err.join(timeout=0.5)
    except Exception:
        pass
    try:
        if out_fd:
            out_fd.close()
    except Exception:
        pass
    try:
        if err_fd:
            err_fd.close()
    except Exception:
        pass
    # ensure we don't leave zombie
    try:
        if popen and popen.poll() is None:
            # do not kill here; caller decides
            pass
    except Exception:
        pass

def monitor_loop():
    backoff = 1
    while not stop_requested:
        pid = read_pidfile()
        if pid and pid_is_running(pid):
            logger.info("Server appears running (pid=%s). Next check in %ds", pid, CHECK_INTERVAL)
            time.sleep(CHECK_INTERVAL)
            backoff = 1
            continue

        logger.warning("Server not running. Attempting to start it.")
        popen, out_fd, err_fd, t_out, t_err = start_server_process()
        if not popen:
            logger.error("Failed to spawn process; backing off %ds", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        # small grace to catch immediate failures
        time.sleep(START_GRACE)
        if popen.poll() is not None:
            logger.warning("Server process exited immediately (rc=%s). Check server stderr/stdout logs.", popen.returncode)
            _close_handles_and_join(popen, out_fd, err_fd, t_out, t_err)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue

        # wait for pidfile to appear
        deadline = time.time() + PID_WAIT_SECONDS
        pid_from_file = None
        while time.time() < deadline and not stop_requested:
            pid_from_file = read_pidfile()
            if pid_from_file:
                logger.info("Found pidfile pid=%s", pid_from_file)
                break
            # check if process died
            if popen.poll() is not None:
                logger.warning("Server process terminated before writing pidfile (rc=%s).", popen.returncode)
                break
            time.sleep(0.5)

        if not pid_from_file:
            # fallback to popen.pid if still running
            if popen.poll() is None:
                pid_from_file = popen.pid
                logger.info("Using fallback popen.pid=%s (pidfile not created in time)", pid_from_file)
            else:
                logger.warning("Server process not running after start attempt; will retry with backoff")
                _close_handles_and_join(popen, out_fd, err_fd, t_out, t_err)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

        # monitor process until it dies; stream readers continue running
        logger.info("Monitoring server pid=%s", pid_from_file)
        backoff = 1
        try:
            while not stop_requested:
                # If process exited, break and try restart
                if popen.poll() is not None:
                    logger.warning("Server process pid %s exited with rc=%s", pid_from_file, popen.returncode)
                    break
                time.sleep(CHECK_INTERVAL)
        except Exception:
            logger.exception("Exception in monitor loop while monitoring process")
        finally:
            # if stopping monitor, try to terminate child gracefully
            if stop_requested:
                try:
                    if popen.poll() is None:
                        logger.info("Monitor stopping: terminating child pid=%s", popen.pid)
                        try:
                            popen.terminate()
                        except Exception:
                            pass
                        try:
                            popen.wait(timeout=2)
                        except Exception:
                            try:
                                popen.kill()
                            except Exception:
                                pass
                except Exception:
                    pass

        # close file handles and join readers
        _close_handles_and_join(popen, out_fd, err_fd, t_out, t_err)
        # small delay before restart
        time.sleep(1)

    logger.info("Monitor exiting loop")

if __name__ == "__main__":
    logger.info("Monitor starting; watching script=%s pidfile=%s", SCRIPT, PID_FILE)
    try:
        monitor_loop()
    except KeyboardInterrupt:
        logger.info("Monitor interrupted by keyboard")
    except Exception:
        logger.exception("Monitor crashed unexpectedly")
    logger.info("Monitor exiting")