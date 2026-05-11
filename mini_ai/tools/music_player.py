"""
music_player.py – Floating music player GUI for Mini AI.
Improved with pygame audio, playlist, volume, and progress bar.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Optional, List

try:
    import pygame
except ImportError:
    # Auto-install pygame if missing
    print("Installing pygame...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pygame"], 
                      timeout=60, check=True)
        print("pygame installed.")
        import pygame
    except Exception as e:
        print(f"ERROR: Failed to install pygame: {e}")
        raise

# Initialize pygame mixer
pygame.mixer.init()


class FloatingMusicPlayer:
    def __init__(self):
        self.root: Optional[tk.Tk] = None
        self.is_visible = False
        self.playlist: List[str] = []          # List of file paths
        self.current_index: int = 0
        self.current_track = "No track playing"
        self.is_playing = False
        self.total_length = 0                  # in seconds
        self.update_id = None
        self.volume = 0.5                      # 0.0 to 1.0

    def create_window(self):
        if self.root:
            return

        self.root = tk.Tk()
        self.root.title("Mini AI Music Player")
        self.root.geometry("350x220")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.overrideredirect(True)      # Remove window borders

        # Make draggable
        self.root.bind("<Button-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.do_move)

        # Main frame
        frame = ttk.Frame(self.root, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        # Track info
        self.track_label = ttk.Label(frame, text=self.current_track, wraplength=320)
        self.track_label.pack(pady=(0, 5))

        # Progress bar + time
        progress_frame = ttk.Frame(frame)
        progress_frame.pack(fill=tk.X, pady=5)

        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Scale(progress_frame, variable=self.progress_var,
                                  from_=0, to=100, orient=tk.HORIZONTAL,
                                  command=self.seek)
        self.progress.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0, 5))

        self.time_label = ttk.Label(progress_frame, text="0:00 / 0:00", width=12)
        self.time_label.pack(side=tk.RIGHT)

        # Control buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)

        self.prev_btn = ttk.Button(btn_frame, text="⏮", command=self.previous, width=3)
        self.prev_btn.pack(side=tk.LEFT, padx=2)

        self.play_pause_btn = ttk.Button(btn_frame, text="▶", command=self.play_pause, width=3)
        self.play_pause_btn.pack(side=tk.LEFT, padx=2)

        self.next_btn = ttk.Button(btn_frame, text="⏭", command=self.next, width=3)
        self.next_btn.pack(side=tk.LEFT, padx=2)

        self.add_btn = ttk.Button(btn_frame, text="+", command=self.add_songs, width=3)
        self.add_btn.pack(side=tk.LEFT, padx=2)

        self.close_btn = ttk.Button(btn_frame, text="✕", command=self.hide, width=3)
        self.close_btn.pack(side=tk.LEFT, padx=10)

        # Volume slider
        vol_frame = ttk.Frame(frame)
        vol_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(vol_frame, text="Volume").pack(side=tk.LEFT, padx=(0, 5))

        self.volume_slider = ttk.Scale(vol_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                                       command=self.set_volume)
        self.volume_slider.set(50)
        self.volume_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Initial position
        self.root.geometry("+100+100")

        # Handle window close via escape or close button
        self.root.bind("<Escape>", lambda e: self.hide())

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def show(self):
        if not self.root:
            self.create_window()
        self.root.deiconify()
        self.is_visible = True

    def hide(self):
        if self.root:
            self.root.withdraw()
            self.stop_progress_update()
        self.is_visible = False

    def add_songs(self):
        """Open file dialog to add MP3 files to playlist."""
        files = filedialog.askopenfilenames(
            title="Add songs",
            filetypes=[("Audio files", "*.mp3 *.wav"), ("All files", "*.*")]
        )
        if files:
            self.playlist.extend(files)
            if not pygame.mixer.music.get_busy() and self.current_track == "No track playing":
                self.current_index = max(0, len(self.playlist) - len(files))
                self.play_current()

    def update_track_label(self):
        """Update the track label and window title."""
        if 0 <= self.current_index < len(self.playlist):
            name = os.path.basename(self.playlist[self.current_index])
            self.current_track = name
        else:
            self.current_track = "No track playing"
        if self.track_label:
            self.track_label.config(text=self.current_track)
        if self.root:
            self.root.title(f"Mini AI Music Player - {self.current_track}")

    def play_current(self):
        """Load and play current track from playlist."""
        if not self.playlist or self.current_index >= len(self.playlist):
            return

        try:
            pygame.mixer.music.load(self.playlist[self.current_index])
            pygame.mixer.music.play()
            pygame.mixer.music.set_volume(self.volume)
            self.is_playing = True
            self.play_pause_btn.config(text="⏸")
            self.update_track_label()
            self.get_track_length()
            self.start_progress_update()
        except Exception as e:
            print(f"Error playing track: {e}")
            self.is_playing = False

    def get_track_length(self):
        """Get total length of current track in seconds (if available)."""
        try:
            # Use pygame's mixer.Sound to get length (not all formats support it)
            sound = pygame.mixer.Sound(self.playlist[self.current_index])
            self.total_length = sound.get_length()
        except:
            self.total_length = 0

    def start_progress_update(self):
        """Start periodic UI updates for progress bar."""
        if self.update_id:
            self.root.after_cancel(self.update_id)
        self.update_progress()

    def update_progress(self):
        """Update progress bar and time labels."""
        if not self.is_playing or not self.root:
            return

        if pygame.mixer.music.get_busy() and self.total_length > 0:
            current_pos = pygame.mixer.music.get_pos() / 1000.0  # ms to seconds
            percent = (current_pos / self.total_length) * 100
            self.progress_var.set(percent)

            # Update time labels
            current_str = self.format_time(current_pos)
            total_str = self.format_time(self.total_length)
            self.time_label.config(text=f"{current_str} / {total_str}")

            self.update_id = self.root.after(500, self.update_progress)
        elif not pygame.mixer.music.get_busy() and self.total_length > 0:
            # Track finished, auto-play next
            self.next()

    def stop_progress_update(self):
        if self.update_id:
            self.root.after_cancel(self.update_id)
            self.update_id = None

    def seek(self, value):
        """Seek to position in track."""
        if not self.is_playing or self.total_length == 0:
            return
        try:
            percent = float(value) / 100.0
            new_pos = percent * self.total_length
            pygame.mixer.music.play(start=new_pos)
            # If it was paused, we need to keep pause state? Simpler: resume playing.
            self.is_playing = True
            self.play_pause_btn.config(text="⏸")
            self.start_progress_update()
        except:
            pass

    def play_pause(self):
        if not self.playlist:
            self.add_songs()
            return
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.is_playing = False
            self.play_pause_btn.config(text="▶")
            self.stop_progress_update()
        else:
            pygame.mixer.music.unpause()
            self.is_playing = True
            self.play_pause_btn.config(text="⏸")
            self.start_progress_update()

    def previous(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self.play_current()

    def next(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self.play_current()

    def set_volume(self, value):
        self.volume = float(value) / 100.0
        pygame.mixer.music.set_volume(self.volume)

    @staticmethod
    def format_time(seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def run(self):
        """Start the Tkinter main loop (MUST run in main thread)."""
        if self.root:
            self.root.mainloop()


# Global instance
_player = FloatingMusicPlayer()


def show_music_player():
    """Show the floating music player. 
    NOTE: Tkinter must run in the main thread. Call run_player_in_main_thread() first.
    """
    _player.show()


def run_player_in_main_thread():
    """Call this from the main thread to start the music player's event loop."""
    if not _player.root:
        _player.create_window()
    _player.run()


def detect_music_playback():
    """
    Background thread to detect if any system audio is playing.
    Placeholder - for real detection use pycaw or Windows API.
    """
    while True:
        # Simple stub: check every 10 seconds if player is hidden and maybe auto-show
        # Real implementation would detect active audio sessions.
        time.sleep(10)
        # For demonstration, we do nothing.
        # You could add: if not _player.is_visible and some_audio_active(): show_music_player()


if __name__ == "__main__":
    # When run directly, start the player in the main thread.
    run_player_in_main_thread()