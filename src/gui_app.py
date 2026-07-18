"""
Standalone Windows GUI for the O Checklist online report tool.

Lets the user configure the FTP connection and report settings through a
window instead of editing config.yaml by hand, run a report generation on
demand, or let the app poll the FTP server on a fixed interval in the
background - no Python install or Windows Task Scheduler entry required.
"""

import os
import queue
import sys
import threading
import webbrowser
from datetime import datetime

import yaml
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from process_ochecklist_report import (
    download_file_from_ftp,
    process_downloaded_yaml,
    generate_html_report,
    upload_file_to_ftp,
)

APP_TITLE = "O Checklist online report"
DEFAULT_INTERVAL_MINUTES = 5


def get_app_data_dir():
    """
    Per-user, always-writable location for config.yaml and generated
    reports, independent of where the .exe itself is installed (which may
    be a read-only Program Files folder).
    """
    base = os.getenv('APPDATA') or os.path.expanduser('~')
    app_dir = os.path.join(base, 'OChecklistReport')
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def default_config():
    app_dir = get_app_data_dir()
    return {
        'ftp_server_credentials': {
            'server': '',
            'login': '',
            'password': '',
            'subfolder': '/',
        },
        'html_config': {
            'report_name': 'online-report',
            'output_dir': os.path.join(app_dir, 'reports'),
            'ftp_upload': False,
            'subfolder': '/',
            'schedule_interval_minutes': DEFAULT_INTERVAL_MINUTES,
        },
    }


def load_config(path):
    cfg = default_config()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            loaded = yaml.safe_load(f) or {}
        cfg['ftp_server_credentials'].update(loaded.get('ftp_server_credentials') or {})
        cfg['html_config'].update(loaded.get('html_config') or {})
    return cfg


def save_config(path, cfg):
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


class ReportApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.minsize(560, 520)

        self.config_path = os.path.join(get_app_data_dir(), 'config.yaml')
        self.cfg = load_config(self.config_path)

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.scheduler_thread = None
        self.last_report_path = None

        self._build_widgets()
        self._load_fields_from_cfg()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._poll_log_queue)

    # -- UI construction ---------------------------------------------------

    def _build_widgets(self):
        pad = {'padx': 8, 'pady': 4}

        ftp_frame = ttk.LabelFrame(self.root, text="FTP připojení")
        ftp_frame.pack(fill='x', **pad)

        self.var_server = tk.StringVar()
        self.var_login = tk.StringVar()
        self.var_password = tk.StringVar()
        self.var_download_subfolder = tk.StringVar()

        self._labeled_entry(ftp_frame, "Server:", self.var_server, 0)
        self._labeled_entry(ftp_frame, "Uživatel:", self.var_login, 1)
        self._labeled_entry(ftp_frame, "Heslo:", self.var_password, 2, show='*')
        self._labeled_entry(ftp_frame, "Složka se staženými soubory:", self.var_download_subfolder, 3)
        ftp_frame.columnconfigure(1, weight=1)

        report_frame = ttk.LabelFrame(self.root, text="Report")
        report_frame.pack(fill='x', **pad)

        self.var_report_name = tk.StringVar()
        self.var_output_dir = tk.StringVar()
        self.var_ftp_upload = tk.BooleanVar()
        self.var_upload_subfolder = tk.StringVar()
        self.var_interval = tk.IntVar(value=DEFAULT_INTERVAL_MINUTES)

        self._labeled_entry(report_frame, "Název reportu:", self.var_report_name, 0)

        ttk.Label(report_frame, text="Výstupní složka:").grid(row=1, column=0, sticky='w', padx=6, pady=4)
        output_row = ttk.Frame(report_frame)
        output_row.grid(row=1, column=1, sticky='ew', padx=6, pady=4)
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.var_output_dir).grid(row=0, column=0, sticky='ew')
        ttk.Button(output_row, text="Vybrat...", command=self._browse_output_dir).grid(row=0, column=1, padx=(6, 0))

        ttk.Checkbutton(
            report_frame, text="Nahrávat report zpět na FTP server", variable=self.var_ftp_upload
        ).grid(row=2, column=0, columnspan=2, sticky='w', padx=6, pady=4)

        self._labeled_entry(report_frame, "Cílová složka na FTP:", self.var_upload_subfolder, 3)

        ttk.Label(report_frame, text="Interval automatické aktualizace (min):").grid(
            row=4, column=0, sticky='w', padx=6, pady=4
        )
        self.interval_spin = ttk.Spinbox(
            report_frame, from_=1, to=1440, textvariable=self.var_interval, width=6
        )
        self.interval_spin.grid(row=4, column=1, sticky='w', padx=6, pady=4)
        report_frame.columnconfigure(1, weight=1)

        button_row = ttk.Frame(self.root)
        button_row.pack(fill='x', **pad)

        ttk.Button(button_row, text="Uložit nastavení", command=self._save_settings).pack(side='left')
        ttk.Button(button_row, text="Spustit nyní", command=self._run_once_clicked).pack(side='left', padx=6)
        self.schedule_button = ttk.Button(
            button_row, text="Spustit automatické plánování", command=self._toggle_scheduler
        )
        self.schedule_button.pack(side='left', padx=6)
        self.open_report_button = ttk.Button(
            button_row, text="Otevřít report", command=self._open_report, state='disabled'
        )
        self.open_report_button.pack(side='left', padx=6)

        self.status_var = tk.StringVar(value="Připraveno.")
        ttk.Label(self.root, textvariable=self.status_var).pack(fill='x', padx=8)

        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill='both', expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=12, state='disabled', wrap='word')
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side='right', fill='y')
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _labeled_entry(self, parent, label, var, row, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=4)
        entry = ttk.Entry(parent, textvariable=var, show=show)
        entry.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        return entry

    def _browse_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.var_output_dir.get() or os.getcwd())
        if chosen:
            self.var_output_dir.set(chosen)

    # -- config <-> fields ---------------------------------------------------

    def _load_fields_from_cfg(self):
        ftp = self.cfg['ftp_server_credentials']
        html_cfg = self.cfg['html_config']
        self.var_server.set(ftp.get('server', ''))
        self.var_login.set(ftp.get('login', ''))
        self.var_password.set(ftp.get('password', ''))
        self.var_download_subfolder.set(ftp.get('subfolder', '/'))
        self.var_report_name.set(html_cfg.get('report_name', 'online-report'))
        self.var_output_dir.set(html_cfg.get('output_dir', os.path.join(get_app_data_dir(), 'reports')))
        self.var_ftp_upload.set(bool(html_cfg.get('ftp_upload', False)))
        self.var_upload_subfolder.set(html_cfg.get('subfolder', '/'))
        self.var_interval.set(int(html_cfg.get('schedule_interval_minutes', DEFAULT_INTERVAL_MINUTES)))

    def _cfg_from_fields(self):
        return {
            'ftp_server_credentials': {
                'server': self.var_server.get().strip(),
                'login': self.var_login.get().strip(),
                'password': self.var_password.get(),
                'subfolder': self.var_download_subfolder.get().strip() or '/',
            },
            'html_config': {
                'report_name': self.var_report_name.get().strip() or 'online-report',
                'output_dir': self.var_output_dir.get().strip() or get_app_data_dir(),
                'ftp_upload': self.var_ftp_upload.get(),
                'subfolder': self.var_upload_subfolder.get().strip() or '/',
                'schedule_interval_minutes': max(1, int(self.var_interval.get() or DEFAULT_INTERVAL_MINUTES)),
            },
        }

    def _save_settings(self, silent=False):
        self.cfg = self._cfg_from_fields()
        try:
            save_config(self.config_path, self.cfg)
        except Exception as exc:
            self._log(f"Nepodařilo se uložit nastavení: {exc}")
            if not silent:
                messagebox.showerror(APP_TITLE, f"Nepodařilo se uložit nastavení:\n{exc}")
            return False
        self._log("Nastavení uloženo.")
        if not silent:
            messagebox.showinfo(APP_TITLE, "Nastavení bylo uloženo.")
        return True

    # -- logging (thread-safe) ---------------------------------------------

    def _log(self, message):
        self.log_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def _poll_log_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state='normal')
            self.log_text.insert('end', message + '\n')
            self.log_text.see('end')
            self.log_text.configure(state='disabled')
        self.root.after(200, self._poll_log_queue)

    # -- report generation ---------------------------------------------------

    def _run_once_clicked(self):
        if not self._save_settings(silent=True):
            return
        threading.Thread(target=self._run_report, daemon=True).start()

    def _run_report(self):
        cfg = self.cfg
        ftp = cfg['ftp_server_credentials']
        html_cfg = cfg['html_config']
        if not ftp.get('server') or not ftp.get('login'):
            self._log("Chybí FTP server nebo přihlašovací jméno - nastavení nejsou kompletní.")
            return
        try:
            self._log("Stahuji data z FTP serveru...")
            downloaded = download_file_from_ftp(
                ftp['server'], ftp['login'], ftp['password'], ftp.get('subfolder', '/')
            )
            self._log(f"Staženo souborů: {len(downloaded)}. Zpracovávám...")
            changes = process_downloaded_yaml(downloaded)
            generate_html_report(changes, html_cfg['report_name'], html_cfg['output_dir'])
            report_path = os.path.join(html_cfg['output_dir'], html_cfg['report_name'] + '.html')
            self.last_report_path = report_path
            self.open_report_button.configure(state='normal')

            if html_cfg.get('ftp_upload'):
                upload_file_to_ftp(
                    ftp['server'], ftp['login'], ftp['password'],
                    html_cfg.get('subfolder', '/'), html_cfg['report_name'], html_cfg['output_dir']
                )
                self._log("Report vygenerován a nahrán na FTP server.")
            else:
                self._log(f"Report vygenerován: {report_path}")

            self.status_var.set(f"Poslední aktualizace: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        except Exception as exc:
            self._log(f"Chyba při generování reportu: {exc}")

    def _open_report(self):
        if self.last_report_path and os.path.exists(self.last_report_path):
            webbrowser.open(f"file://{self.last_report_path}")
        else:
            messagebox.showinfo(APP_TITLE, "Report zatím nebyl vygenerován.")

    # -- scheduling ---------------------------------------------------------

    def _toggle_scheduler(self):
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self._stop_scheduler()
        else:
            self._start_scheduler()

    def _start_scheduler(self):
        if not self._save_settings(silent=True):
            return
        self.stop_event.clear()
        interval_minutes = self.cfg['html_config']['schedule_interval_minutes']
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop, args=(interval_minutes,), daemon=True
        )
        self.scheduler_thread.start()
        self.schedule_button.configure(text="Zastavit plánování")
        self.interval_spin.configure(state='disabled')
        self._log(f"Automatické plánování spuštěno (interval {interval_minutes} min).")

    def _stop_scheduler(self):
        self.stop_event.set()
        self.schedule_button.configure(text="Spustit automatické plánování")
        self.interval_spin.configure(state='normal')
        self._log("Automatické plánování zastaveno.")

    def _scheduler_loop(self, interval_minutes):
        while not self.stop_event.is_set():
            self._run_report()
            self.stop_event.wait(interval_minutes * 60)

    def _on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    ReportApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
