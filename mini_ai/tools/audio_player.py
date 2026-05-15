"""
headless_player.py – Improved VLC-based headless audio player.
Plays audio from URL or local file, communicates state via JSON.
Supports loop, pause, stop, volume, seek via command file.
"""

import sys
import time
import json
import tempfile
import os
import signal
import atexit
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, Any, cast

# Try to import yt-dlp for search support
try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

# ----------------------------------------------------------------------
# DLL path setup for Windows (VLC)
# ----------------------------------------------------------------------
def _setup_vlc_paths() -> None:
    if sys.platform != "win32":
        return
    vlc_paths = [
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "VideoLAN", "VLC"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "VideoLAN", "VLC"),
    ]
    for path in vlc_paths:
        dll_path = os.path.join(path, "libvlc.dll")
        if os.path.exists(dll_path):
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(path)
                except (PermissionError, OSError):
                    pass
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
            break

_setup_vlc_paths()

try:
    import vlc
except ImportError as e:
    # Auto-install python-vlc if missing
    print("Installing python-vlc...", file=sys.stderr)
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "python-vlc"], 
                      timeout=60, check=True)
        print("python-vlc installed. Retrying...", file=sys.stderr)
        import vlc
    except subprocess.TimeoutExpired:
        print("ERROR: python-vlc installation timed out.", file=sys.stderr)
        raise
    except subprocess.CalledProcessError:
        print("ERROR: Failed to install python-vlc. Run: pip install python-vlc", file=sys.stderr)
        raise
    except Exception as install_err:
        print(f"ERROR: Failed to install python-vlc: {install_err}", file=sys.stderr)
        raise

    print("✓ VLC module loaded successfully", file=sys.stderr)
# ----------------------------------------------------------------------
# Helper functions for state and command files
# ----------------------------------------------------------------------
def get_state_file() -> Path:
    """Return path to the state JSON file."""
    return Path(tempfile.gettempdir()) / "miniai_player_state.json"

def get_cmd_file() -> Path:
    """Return path to the command JSON file."""
    return Path(tempfile.gettempdir()) / "miniai_player_cmd.json"

def write_state(state_file: Path, state: Dict[str, Any]) -> None:
    """Safely write state dictionary to JSON file."""
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
    except (IOError, OSError, TypeError) as e:
        # Silently fail – avoid crashing the player thread
        print(f"DEBUG: Failed to write state: {e}", file=sys.stderr)

def read_command(cmd_file: Path) -> Optional[Dict[str, Any]]:
    """Read and delete the command file. Return command dict or None."""
    if not cmd_file.exists():
        return None
    try:
        with open(cmd_file, 'r') as f:
            cmd_data = json.load(f)
        os.remove(cmd_file)
        return cmd_data
    except (json.JSONDecodeError, IOError, OSError):
        return None

# ----------------------------------------------------------------------
# Main player class (improved)
# ----------------------------------------------------------------------
class VLCPlayer:
    def __init__(self, url: str, title: str, state_file: Path, loop: bool = False):
        self.url = url
        self.title = title
        self.state_file = state_file
        self.loop = loop
        self.is_playing = False
        self.elapsed = 0.0
        self.duration = 0.0
        self.status = "buffering"
        self.volume = 100          # 0-100
        self.autoplay = False      # Auto-play relevant tracks
        self.queue = []            # List of {"url": ..., "title": ...}
        self.history = []          # History of played tracks
        self.played_ids = set()    # Set of played video IDs to avoid loops
        self.current_id = None     # Store current track ID
        
        self._stop_requested = False
        self._last_state_write = 0.0
        self._player = None        # vlc.MediaPlayer
        self._instance = None

    def _create_instance(self) -> vlc.Instance:
        """Create VLC instance with sensible options."""
        options = [
            '--no-xlib',           # disable X11 (for headless)
            '--no-video',          # disable video output
            '--quiet',             # reduce VLC log noise
            '--network-caching=5000',
            '--file-caching=3000',
            '--no-video-title-show',
            '--no-snapshot-preview',
            '--http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '--http-referrer=https://www.youtube.com/',
        ]
        instance = vlc.Instance(*options)
        if not instance:
            # Fallback to no options if some are unsupported
            instance = vlc.Instance()
        return instance

    def _setup_media(self, instance: vlc.Instance) -> vlc.Media:
        """Create media object with appropriate options."""
        media = instance.media_new(self.url)
        # Add network caching and disable video
        media.add_option('network-caching=5000')
        media.add_option('no-video')
        # CRITICAL: YouTube streams require proper HTTP headers or they get rejected
        media.add_option(':http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        media.add_option(':http-referrer=https://www.youtube.com/')
        # For local files, we can also add file-caching if needed
        return media

    def _wait_for_playing(self, timeout: float = 15.0) -> bool:
        """Wait until VLC state becomes PLAYING or ERROR, return True if playing."""
        start = time.time()
        while time.time() - start < timeout and not self._stop_requested:
            try:
                state = self._player.get_state()
            except Exception:
                return False

            if state == vlc.State.Playing:
                return True
            if state in (vlc.State.Error, vlc.State.Stopped):
                return False
            time.sleep(0.1)

        try:
            return self._player.get_state() == vlc.State.Playing
        except Exception:
            return False

    def _update_state(self) -> None:
        """Read current player state and write to JSON file only when necessary."""
        if not self._player:
            return

        now = time.time()
        vlc_state = self._player.get_state()
        
        # Determine status string
        if vlc_state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
            self.is_playing = False
            self.status = "stopped" if vlc_state != vlc.State.Error else "error"
        elif vlc_state == vlc.State.Paused:
            self.is_playing = False
            self.status = "paused"
        elif vlc_state == vlc.State.Buffering:
            self.is_playing = True
            self.status = "buffering"
        elif vlc_state == vlc.State.Playing:
            self.is_playing = True
            self.status = "playing"

        # Get duration and elapsed
        duration_ms = self._player.get_length()
        new_duration = duration_ms / 1000.0 if duration_ms > 0 else 0.0
        time_ms = self._player.get_time()
        new_elapsed = time_ms / 1000.0 if time_ms >= 0 else 0.0

        # Optimization: Only write if something significant changed or 1 second passed
        # We track the last written values to detect changes
        if not hasattr(self, '_last_written_data'):
            self._last_written_data = {}

        current_data = {
            "pid": os.getpid(),
            "title": self.title,
            "playing": self.is_playing,
            "elapsed": int(new_elapsed),
            "duration": new_duration,
            "status": self.status,
            "error": self.title if self.status == "error" else None,
            "loop": self.loop,
            "autoplay": self.autoplay,
            "volume": self.volume,
            "queue": self.queue,
        }

        # Check for significant changes
        changed = (
            current_data["status"] != self._last_written_data.get("status") or
            current_data["title"] != self._last_written_data.get("title") or
            len(current_data["queue"]) != len(self._last_written_data.get("queue", [])) or
            abs(new_elapsed - self._last_written_data.get("full_elapsed", 0)) >= 1.0 or
            now - self._last_state_write > 2.0 # Heartbeat every 2s
        )

        if changed:
            self.elapsed = new_elapsed
            self.duration = new_duration
            self._last_state_write = now
            self._last_written_data = current_data
            self._last_written_data["full_elapsed"] = new_elapsed # Keep high precision for comparison
            write_state(self.state_file, current_data)

    def _apply_command(self, cmd: Dict[str, Any]) -> None:
        """Execute a command from the command file."""
        cmd_type = cmd.get("command")
        if not self._player:
            return

        if cmd_type == "pause":
            self._player.pause()
        elif cmd_type == "stop":
            self._stop_requested = True
            self._player.stop()
        elif cmd_type == "volume":
            vol = cmd.get("volume", 50)
            # Clamp to 0-100
            vol = max(0, min(100, int(vol)))
            self.volume = vol
            self._player.audio_set_volume(vol)
        elif cmd_type == "seek":
            pos = cmd.get("position")
            if pos is not None:
                # pos can be seconds (float) or percent (0-100)
                if isinstance(pos, (int, float)):
                    if 0 <= pos <= 100 and pos > 1.0:
                        # Assume percent if value > 1 and <= 100
                        if self.duration > 0:
                            pos_sec = (pos / 100.0) * self.duration
                        else:
                            pos_sec = 0
                    else:
                        pos_sec = float(pos)
                    self._player.set_time(int(pos_sec * 1000))
        elif cmd_type == "skip":
            self._player.stop() # Main loop will catch this and play next
        elif cmd_type == "toggle_autoplay":
            self.autoplay = not self.autoplay
            self._last_written_data = {} # Force write
        elif cmd_type == "enqueue":
            query = cmd.get("query")
            if query and HAS_YTDLP:
                threading.Thread(target=self._resolve_and_enqueue, args=(query,), daemon=True).start()
        elif cmd_type == "play":
            query = cmd.get("query")
            if query and HAS_YTDLP:
                self.status = "buffering"
                self.title = f"Searching: {query}..."
                self._last_written_data = {}
                # Stop current immediately so user sees responsiveness
                self._player.stop()
                threading.Thread(target=self._resolve_and_play, args=(query,), daemon=True).start()

    def _resolve_and_enqueue(self, query: str):
        try:
            info = self._resolve_query(query)
            if info:
                self.queue.append({
                    "url": info["url"], 
                    "title": info["title"],
                    "id": info.get("id")
                })
                self._update_state() # Trigger immediate UI update
            else:
                # Just reset title if enqueuing failed to not confuse user
                if "Searching:" in self.title:
                    self._update_state() # Will pick up original title
        except Exception:
            pass

    def _resolve_and_play(self, query: str):
        try:
            info = self._resolve_query(query)
            if info:
                self.url = info["url"]
                self.title = info["title"]
                self.current_id = info.get("id")
                self._start_new_media()
            else:
                self.status = "error"
                self.title = f"No results found: {query}"
        except Exception as e:
            self.status = "error"
            self.title = f"Search failed: {e}"

    def _resolve_query(self, query: str) -> Optional[Dict[str, str]]:
        # Use ytsearch1 prefix for non-URLs to ensure consistent behavior
        search_query = query if query.startswith("http") else f"ytsearch1:{query}"
        
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 12,
            "noplaylist": True,
            "extract_flat": False,
        }
        try:
            with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if not info: return None
                
                # If it's a search result, it will have 'entries'
                if "entries" in info:
                    if not info["entries"]: return None
                    info = info["entries"][0]
                
                if not info or "url" not in info:
                    return None
                    
                return {
                    "url": info["url"], 
                    "title": info.get("title", "Unknown Track"),
                    "id": info.get("id")
                }
        except Exception as e:
            print(f"DEBUG: yt-dlp error for {query}: {e}", file=sys.stderr)
            return None

    def _get_recommendation(self) -> Optional[Dict[str, str]]:
        """Fetch a relevant track using YouTube's Mix feature with fallback."""
        if not self.current_id:
            # Fallback to similarity search if we don't have a YouTube ID
            clean_title = self.title
            for term in ["(Official Video)", "(Official Audio)", "Lyric Video", "Lyrics", "HD", "4K"]:
                clean_title = clean_title.replace(term, "")
            # Just do a generic search but add a music twist
            return self._resolve_query(f"song similar to {clean_title} official audio")
            
        mix_url = f"https://www.youtube.com/watch?v={self.current_id}&list=RD{self.current_id}"
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "playlist_items": "2-15", # Skip the first one
        }
        try:
            with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                info = ydl.extract_info(mix_url, download=False)
                if not info or "entries" not in info:
                    return None
                
                for entry in info["entries"]:
                    if not entry: continue
                    vid = entry.get("id")
                    if vid and vid not in self.played_ids:
                        return self._resolve_query(f"https://www.youtube.com/watch?v={vid}")
        except Exception:
            pass
        return None

    def _start_new_media(self):
        if not self._player: return
        if self.current_id:
            self.played_ids.add(self.current_id)
        # Store clean history
        self.history.append({"url": self.url, "title": self.title})
        if len(self.history) > 50: self.history.pop(0) # Cap history
        
        self._player.stop()
        new_media = self._setup_media(self._instance)
        self._player.set_media(new_media)
        self._player.play()
        self._last_written_data = {} # Force state write
        # You can add more commands (e.g., "set_loop") if needed

    def play(self) -> None:
        """Start playback and monitor until stopped or finished."""
        # Clean up any previous player
        if self._player:
            self._player.stop()
            self._player.release()

        self._instance = self._create_instance()
        self._player = self._instance.media_player_new()
        media = self._setup_media(self._instance)
        self._player.set_media(media)
        self._player.audio_set_volume(self.volume)

        # Start playback
        self._player.play()
        # Log initial play call
        try:
            with open(Path(tempfile.gettempdir()) / "miniai_audio_debug.log", 'a') as f:
                f.write(f"[{time.ctime()}] play() called for: {self.title}\n")
        except Exception:
            pass

        if not self._wait_for_playing(timeout=20.0):
            try:
                with open(Path(tempfile.gettempdir()) / "miniai_audio_debug.log", 'a') as f:
                    f.write(f"[{time.ctime()}] Failed to reach PLAYING state for: {self.title}\n")
            except Exception:
                pass
            write_state(self.state_file, {
                "pid": os.getpid(),
                "title": self.title,
                "status": "error",
                "error": "Failed to start playback"
            })
            return

        self._stop_requested = False
        cmd_file = get_cmd_file()

        # Main control loop
        while not self._stop_requested:
            # Process any incoming commands
            cmd_data = read_command(cmd_file)
            if cmd_data:
                self._apply_command(cmd_data)

            # Check VLC state
            try:
                state = self._player.get_state()
            except Exception as e:
                break

            # Handle loop: if ended and loop is True, restart
            if state == vlc.State.Ended and self.loop and not self._stop_requested:
                self._player.stop()
                time.sleep(0.2)
                self._player.play()
                # Wait briefly for playing state
                self._wait_for_playing(3.0)
                continue

            # Exit if stopped/ended/error and not looping
            if state in (vlc.State.Stopped, vlc.State.Ended, vlc.State.Error):
                # If we have something in the queue, play it
                if self.queue and not self._stop_requested:
                    next_item = self.queue.pop(0)
                    self.url = next_item["url"]
                    self.title = next_item["title"]
                    self.current_id = next_item.get("id")
                    self._start_new_media()
                    self._wait_for_playing(5.0)
                    continue
                
                # If autoplay is on, find relevant next track
                if self.autoplay and not self._stop_requested and HAS_YTDLP:
                    self.status = "buffering"
                    self.title = f"Finding next track (autoplay)..."
                    self._update_state()
                    try:
                        info = self._get_recommendation()
                        if info:
                            self.url = info["url"]
                            self.title = info["title"]
                            self.current_id = info.get("id")
                            self._start_new_media()
                            self._wait_for_playing(10.0)
                            continue
                    except Exception:
                        pass
                
                # If we reach here, it's actually stopped, but we stay alive to listen for commands
                self.status = "stopped"
                self.is_playing = False
                # No break here! We wait for commands.

            # Update state file
            self._update_state()

            # Sleep a bit to avoid busy-looping
            time.sleep(0.25)

        # Clean termination
        self._player.stop()
        self._player.release()
        self._instance.release()
        write_state(self.state_file, {
            "pid": os.getpid(),
            "title": self.title,
            "status": "stopped",
            "playing": False
        })


# ----------------------------------------------------------------------
# Public entry point (same signature as original)
# ----------------------------------------------------------------------
def play_audio_headless(url: str, title: str, loop: bool = False) -> None:
    """
    Headless audio player that plays audio using VLC.
    Called as a subprocess - communicates playback state via JSON file.
    """
    state_file = get_state_file()
    log_file = Path(tempfile.gettempdir()) / "miniai_audio_debug.log"
    try:
        with open(log_file, 'a') as f:
            f.write(f"[{time.ctime()}] Starting playback: {title} (URL: {url})\n")
        player = VLCPlayer(url, title, state_file, loop=loop)
        player.play()
    except Exception as e:
        import traceback
        with open(log_file, 'a') as f:
            f.write(f"[{time.ctime()}] ERROR: {e}\n")
            f.write(traceback.format_exc() + "\n")
        # Write error to state file so the parent process can know
        write_state(state_file, {
            "title": title,
            "status": "error",
            "error": str(e)
        })
        raise


# ----------------------------------------------------------------------
# Command-line entry point (unchanged from original)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Headless VLC audio player")
    parser.add_argument("url", help="Audio URL or file path")
    parser.add_argument("title", nargs="?", default="Unknown Track", help="Track title for state")
    parser.add_argument("--loop", action="store_true", help="Loop playback")
    args = parser.parse_args()

    play_audio_headless(args.url, args.title, loop=args.loop)