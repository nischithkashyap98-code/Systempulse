# system_pulse.py
import tkinter as tk
from tkinter import ttk
import psutil
import threading
import time
import platform
from datetime import datetime
import collections
import os

# Matplotlib for embedded real-time graphs
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# ==========================
# ⚡ System Pulse – Real-time System Monitor (with graphs)
# ==========================

HISTORY_LEN = 60  # seconds of history

class SystemPulse:
    def __init__(self, root):
        self.root = root
        self.root.title("System Pulse ⚡")
        self.root.geometry("840x560")
        self.root.resizable(False, False)
        self.root.configure(bg="#0a0f1a")

        # Styling
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TProgressbar",
                             troughcolor="#1a1f2b",
                             bordercolor="#00E0B8",
                             background="#00E0B8",
                             lightcolor="#00E0B8",
                             darkcolor="#00E0B8")

        # Title
        title = tk.Label(root, text="System Pulse", fg="#00E0B8", bg="#0a0f1a",
                         font=("Poppins", 22, "bold"))
        title.pack(pady=10)

        # Top layout: left metrics, right graphs
        top_frame = tk.Frame(root, bg="#0a0f1a")
        top_frame.pack(fill="both", expand=False, padx=12)

        metrics_frame = tk.Frame(top_frame, bg="#0a0f1a")
        metrics_frame.pack(side="left", fill="y", padx=(0,12))

        graphs_frame = tk.Frame(top_frame, bg="#0a0f1a")
        graphs_frame.pack(side="right", fill="both", expand=True)

        # Metrics (progress bars)
        self.labels = {}
        metric_names = ["CPU Usage", "Memory Usage", "Disk Usage", "Network Speed", "Battery"]
        for text in metric_names:
            frame = tk.Frame(metrics_frame, bg="#0a0f1a")
            frame.pack(fill="x", pady=6)
            label = tk.Label(frame, text=text, fg="white", bg="#0a0f1a", anchor="w", font=("Open Sans", 11))
            label.pack(side="left", padx=6)
            bar = ttk.Progressbar(frame, length=260, mode="determinate", style="TProgressbar")
            bar.pack(side="right", padx=6)
            self.labels[text] = bar

        # Info label
        self.info_label = tk.Label(root, text="", fg="#9be8da", bg="#0a0f1a", font=("Open Sans", 10))
        self.info_label.pack(pady=6)

        # --- Matplotlib figure with 3 subplots (CPU, MEM, NET) ---
        self.fig = Figure(figsize=(6.5, 3.0), dpi=100, facecolor="#0a0f1a")
        # set subplot background colors/text color to blend
        self.ax_cpu = self.fig.add_subplot(311)
        self.ax_mem = self.fig.add_subplot(312)
        self.ax_net = self.fig.add_subplot(313)

        for ax in (self.ax_cpu, self.ax_mem, self.ax_net):
            ax.set_facecolor("#071028")
            ax.tick_params(axis='x', colors='#cfeeff')
            ax.tick_params(axis='y', colors='#cfeeff')
            for spine in ax.spines.values():
                spine.set_color('#223447')

        self.ax_cpu.set_ylabel("CPU %", color='#cfeeff')
        self.ax_mem.set_ylabel("Mem %", color='#cfeeff')
        self.ax_net.set_ylabel("KB/s", color='#cfeeff')
        self.ax_net.set_xlabel("Seconds", color='#cfeeff')

        self.line_cpu, = self.ax_cpu.plot([], [], color="#00E0B8", lw=1.8)
        self.line_mem, = self.ax_mem.plot([], [], color="#45ffd6", lw=1.8)
        self.line_net, = self.ax_net.plot([], [], color="#80ffd6", lw=1.8)

        self.canvas = FigureCanvasTkAgg(self.fig, master=graphs_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Data history deques
        self.history_cpu = collections.deque([0]*HISTORY_LEN, maxlen=HISTORY_LEN)
        self.history_mem = collections.deque([0]*HISTORY_LEN, maxlen=HISTORY_LEN)
        self.history_net = collections.deque([0]*HISTORY_LEN, maxlen=HISTORY_LEN)
        self.time_idx = collections.deque(list(range(-HISTORY_LEN+1, 1)), maxlen=HISTORY_LEN)

        # Start data collection thread
        self.collecting = True
        threading.Thread(target=self._collect_loop, daemon=True).start()

        # Start plot refresh (in main Tk thread)
        self._schedule_plot_update()

    # ---------------------------
    # Data collection thread
    # ---------------------------
    def _collect_loop(self):
        # initialize a net snapshot
        prev_net = psutil.net_io_counters()
        while self.collecting:
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory().percent

            # disk average across partitions (cross-platform)
            try:
                partitions = psutil.disk_partitions(all=False)
                usage_list = []
                for p in partitions:
                    try:
                        u = psutil.disk_usage(p.mountpoint)
                        usage_list.append(u.percent)
                    except Exception:
                        continue
                disk = round(sum(usage_list) / len(usage_list), 1) if usage_list else 0
            except Exception:
                disk = 0
                partitions = []

            # network speed KB/s using previous snapshot
            net_now = psutil.net_io_counters()
            bytes_diff = (net_now.bytes_sent + net_now.bytes_recv) - (prev_net.bytes_sent + prev_net.bytes_recv)
            prev_net = net_now
            net_kbs = bytes_diff / 1024.0  # KB per 1 second

            # battery
            try:
                battery = psutil.sensors_battery()
                if battery:
                    bat_text = f"{battery.percent}% {'(Charging)' if battery.power_plugged else ''}"
                    bat_value = battery.percent
                else:
                    bat_text = "N/A"
                    bat_value = 0
            except Exception:
                bat_text = "N/A"
                bat_value = 0

            # Append to history (thread-safe for deques)
            self.history_cpu.append(cpu)
            self.history_mem.append(mem)
            self.history_net.append(net_kbs)

            # Update progress bars via tk's thread-safe method: use after with lambda
            self.root.after(0, lambda c=cpu, m=mem, d=disk, n=net_kbs, b=bat_value, p=len(partitions), bt=bat_text: self._update_ui(c, m, d, n, b, p, bt))

    # ---------------------------
    # UI update (progress bars & info)
    # ---------------------------
    def _update_ui(self, cpu, mem, disk, net_kbs, bat_value, partitions_count, bat_text):
        # set bars
        self._update_bar("CPU Usage", cpu)
        self._update_bar("Memory Usage", mem)
        self._update_bar("Disk Usage", disk, color_dynamic=True)
        # network scale: map KB/s to 0-100 range (heuristic)
        self._update_bar("Network Speed", min(net_kbs / 10.0, 100))
        self._update_bar("Battery", bat_value)

        # info line
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        sysinfo = (
            f"{platform.system()} {platform.release()} | "
            f"Drives: {partitions_count} | "
            f"Uptime: {uptime.days}d {uptime.seconds//3600}h | "
            f"Battery: {bat_text}"
        )
        self.info_label.config(text=sysinfo)

    # ---------------------------
    # Update single progress bar and optionally change color
    # ---------------------------
    def _update_bar(self, name, value, color_dynamic=False):
        bar = self.labels.get(name)
        if not bar:
            return
        bar["value"] = value
        if color_dynamic:
            if value < 50:
                color = "#00E0B8"  # aqua
            elif value < 75:
                color = "#FFD700"  # yellow
            else:
                color = "#FF3B3B"  # red
            self.style.configure("TProgressbar", background=color, lightcolor=color, darkcolor=color)
        else:
            self.style.configure("TProgressbar", background="#00E0B8", lightcolor="#00E0B8", darkcolor="#00E0B8")

    # ---------------------------
    # Schedule periodic plot update (in main thread)
    # ---------------------------
    def _schedule_plot_update(self):
        self._refresh_plots()
        self.root.after(1000, self._schedule_plot_update)

    # ---------------------------
    # Refresh matplotlib plots using history deques
    # ---------------------------
    def _refresh_plots(self):
        x = list(range(-len(self.history_cpu)+1, 1))  # last N seconds

        y_cpu = list(self.history_cpu)
        y_mem = list(self.history_mem)
        y_net = list(self.history_net)

        # Update lines
        self.line_cpu.set_data(x, y_cpu)
        self.line_mem.set_data(x, y_mem)
        self.line_net.set_data(x, y_net)

        # Update axes limits
        self.ax_cpu.set_xlim(min(x), max(x) if x else 0)
        self.ax_cpu.set_ylim(0, 100)
        self.ax_mem.set_xlim(min(x), max(x) if x else 0)
        self.ax_mem.set_ylim(0, 100)

        # For network we set dynamic ylim based on max observed
        max_net = max(y_net) if y_net else 10
        self.ax_net.set_xlim(min(x), max(x) if x else 0)
        self.ax_net.set_ylim(0, max(10, max_net*1.4))

        # Tidy up ticks and grid
        for ax in (self.ax_cpu, self.ax_mem, self.ax_net):
            ax.relim()
            ax.autoscale_view()

        # Draw lightweight: use draw_idle for responsiveness
        try:
            self.canvas.draw_idle()
        except Exception:
            # fallback to draw
            self.canvas.draw()

# ==========================
# Run
# ==========================
if __name__ == "__main__":
    root = tk.Tk()
    app = SystemPulse(root)
    root.mainloop()

