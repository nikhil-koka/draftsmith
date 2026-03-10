import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import os
import sys

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DARK   = "#1a1a1a"
PANEL  = "#242424"
CARD   = "#2d2d2d"
BORDER = "#3a3a3a"
ORANGE = "#C8621A"
BLUE_T = "#4A90D9"
RED_T  = "#D94A4A"
TEXT   = "#cccccc"
DIM    = "#555555"
GREEN  = "#2ECC71"

ROLES = ["top", "jng", "mid", "bot", "sup"]

_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
FONT_REGULAR = os.path.join(_SCRIPT_DIR, "fonts", "IntraNet-Typeface",
                             "IntraNet", "IntraNetRegular.otf")

def _register_font():
    try:
        if os.path.exists(FONT_REGULAR):
            from ctypes import windll
            windll.gdi32.AddFontResourceExW(FONT_REGULAR, 0x10, 0)
            return "IntraNet"
    except Exception:
        pass
    return "Consolas"

# Readable small font for file paths / labels
_SMALL = "Segoe UI"


def _spaced(text, spacing=1):
    """Insert `spacing` spaces between each character."""
    return (" " * spacing).join(text)


def _hs(text):
    """Half-space: insert a thin non-breaking-ish gap using a narrow space char."""
    return "\u2009".join(text)   # thin space between each char


class OutlineText(tk.Canvas):
    """
    Renders text with a colored stroke and transparent fill,
    simulating an outline/hollow font effect.
    bg should match the parent background exactly.
    """
    def __init__(self, parent, text, size, stroke_color, bg,
                 stroke_width=2, letter_spacing=0, **kw):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kw)
        self._text         = _spaced(text, letter_spacing) if letter_spacing > 0 else text
        self._size         = size
        self._stroke_color = stroke_color
        self._bg           = bg
        self._stroke_width = stroke_width
        self._font         = None
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()  or 10
        h = self.winfo_height() or 10
        if self._font is None:
            import tkinter.font as tkf
            self._font = tkf.Font(family=self._ff if hasattr(self, "_ff")
                                  else "Consolas", size=self._size, weight="bold")
        cx, cy = w // 2, h // 2
        sw = self._stroke_width
        # draw text in stroke color at slight offsets to build outline
        for dx in range(-sw, sw+1):
            for dy in range(-sw, sw+1):
                if dx == 0 and dy == 0:
                    continue
                if abs(dx) + abs(dy) <= sw + 1:
                    self.create_text(cx+dx, cy+dy, text=self._text,
                                     font=self._font,
                                     fill=self._stroke_color)
        # draw center in background color to hollow it out
        self.create_text(cx, cy, text=self._text,
                         font=self._font, fill=self._bg)

    def set_font_family(self, family):
        self._ff   = family
        self._font = None
        self._draw()


class VerticalBar(tk.Canvas):
    """Vertical strength gauge. Number is always white on a dark backing."""

    def __init__(self, parent, color, label, **kw):
        super().__init__(parent, bg=DARK, highlightthickness=0,
                         width=110, height=220, **kw)
        self._color = color
        self._label = label
        self._value = 0.5
        self._txt   = "—"
        self.bind("<Configure>", lambda e: self._draw())

    def set_value(self, value, txt):
        self._value = max(0.0, min(1.0, value))
        self._txt   = txt
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()  or 110
        h = self.winfo_height() or 220

        bar_w = max(28, int(w * 0.42))
        bar_h = int(h * 0.58)
        bx    = (w - bar_w) // 2
        label_h = 30  # space reserved for label below
        by    = (h - bar_h - label_h) // 2

        # track
        self.create_rectangle(bx, by, bx+bar_w, by+bar_h,
                               fill="#111111", outline=BORDER, width=1)

        # fill from bottom
        fh = int(bar_h * self._value)
        if fh > 2:
            self.create_rectangle(bx+2, by+bar_h-fh,
                                   bx+bar_w-2, by+bar_h-1,
                                   fill=self._color, outline="")

        # dark pill behind the number so it always reads clearly
        tx = bx + bar_w // 2
        ty = by + bar_h // 2
        pad_x, pad_y = 14, 6
        tw = len(self._txt) * 8 + pad_x
        self.create_rectangle(tx - tw//2, ty - pad_y - 6,
                               tx + tw//2, ty + pad_y + 6,
                               fill="#111111", outline=BORDER, width=1)
        # white number text
        self.create_text(tx, ty, text=self._txt,
                          fill="#ffffff", font=("Consolas", 13, "bold"))

        # colored label below bar — IntraNet
        self.create_text(w // 2, by + bar_h + 22,
                          text=self._label.upper(),
                          fill=self._color,
                          font=("IntraNet", 11, "bold"))


class DraftApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Draftsmith by Nix")
        self.geometry("1280x900")
        self.configure(fg_color=DARK)
        self.resizable(True, True)

        self._ff       = _register_font()
        self._draft    = None
        self._port     = None
        self._password = None
        self._my_role  = None   # detected from LCU localPlayerCellId

        self._build_ui()

    def _f(self, size, bold=True):
        return (self._ff, size, "bold" if bold else "normal")

    def _s(self, text):
        """Thin letter spacing for IntraNet font — uses Unicode thin space."""
        return _hs(text)

    def _outlined_btn(self, parent, text, cmd, bg_parent=None):
        """Button with a permanent orange rectangle outline via a Frame wrapper."""
        bg_parent = bg_parent or PANEL
        border = tk.Frame(parent, bg=ORANGE, padx=1, pady=1)
        btn = tk.Button(border, text=text, font=(_SMALL, 9, "bold"),
                        fg=ORANGE, bg=bg_parent,
                        activebackground=ORANGE, activeforeground=DARK,
                        relief="flat", bd=0, padx=12, pady=5,
                        cursor="hand2", command=cmd)
        btn.pack()
        return border, btn

    def _build_ui(self):
        bar = tk.Frame(self, bg="#111111", height=80)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tf = tk.Frame(bar, bg="#111111")
        tf.pack(side="left", padx=20, pady=10)

        ds = OutlineText(tf, "DRAFTSMITH", 26, ORANGE, "#111111", stroke_width=2,
                         width=320, height=56)
        ds.set_font_family(self._ff)
        ds.pack(side="left")

        bn = OutlineText(tf, "BY NIX", 26, DIM, "#111111", stroke_width=2,
                         width=190, height=56)
        bn.set_font_family(self._ff)
        bn.pack(side="left")

        self._status_lbl = tk.Label(bar, text="NOT INITIALIZED",
                                     font=self._f(10), fg=DIM, bg="#111111")
        self._status_lbl.pack(side="right", padx=20)

        # compact update button in title bar
        upd_f = tk.Frame(bar, bg="#111111")
        upd_f.pack(side="right", padx=(0,12))
        border, self._update_btn = self._outlined_btn(upd_f, "UPDATE", self._do_update_app, bg_parent="#111111")
        border.pack(side="right")

        tk.Frame(self, bg=ORANGE, height=2).pack(fill="x")

        body = tk.Frame(self, bg=DARK)
        body.pack(fill="both", expand=True)
        self._build_left(body)
        self._build_right(body)

    def _build_left(self, parent):
        left = tk.Frame(parent, bg=PANEL, width=296)
        left.pack(side="left", fill="y", padx=(10,0), pady=10)
        left.pack_propagate(False)

        def sep(text):
            tk.Frame(left, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(14,2))
            tk.Label(left, text=self._s(text), font=self._f(9),
                     fg=ORANGE, bg=PANEL, anchor="w").pack(fill="x", padx=12, pady=(2,6))

        sep("LOCKFILE")
        self._lockfile_var = tk.StringVar(
            value=r"C:\Riot Games\League of Legends\lockfile")
        tk.Entry(left, textvariable=self._lockfile_var,
                 font=(_SMALL, 9), fg=TEXT, bg=CARD,
                 insertbackground=TEXT, relief="flat", bd=4
                 ).pack(fill="x", padx=12, pady=(0,4))
        self._mk_btn(left, "BROWSE", self._browse_lf)

        sep("DATASETS")
        self._ranked_var = tk.StringVar(value="ranked_dataset.csv")
        self._pro_var    = tk.StringVar(
            value="2026_LoL_esports_match_data_from_OraclesElixir.csv")
        for lbl, var in [("RANKED CSV", self._ranked_var),
                         ("PRO CSV",    self._pro_var)]:
            tk.Label(left, text=lbl, font=(_SMALL, 8, "bold"),
                     fg=DIM, bg=PANEL, anchor="w").pack(fill="x", padx=12)
            r = tk.Frame(left, bg=PANEL)
            r.pack(fill="x", padx=12, pady=(0,4))
            tk.Entry(r, textvariable=var, font=(_SMALL, 8),
                     fg=TEXT, bg=CARD, insertbackground=TEXT,
                     relief="flat", bd=3).pack(side="left", fill="x",
                                                expand=True, padx=(0,4))
            tk.Button(r, text="…", font=(_SMALL, 10), fg=TEXT, bg=BORDER,
                      activebackground=ORANGE, activeforeground=DARK,
                      relief="flat", bd=0, padx=6,
                      command=lambda v=var: self._browse_csv(v)).pack(side="right")

        self._mk_btn(left, "INITIALIZE & TRAIN MODEL", self._do_init, accent=True, space=False)

        sep("ACTIONS")
        self._fetch_btn   = self._mk_btn(left, "FETCH LOBBY",
                                          self._do_fetch, ret=True)
        self._analyze_btn = self._mk_btn(left, "ANALYZE DRAFT",
                                          self._do_analyze, ret=True)
        self._rec_btn     = self._mk_btn(left, "GET RECOMMENDATIONS",
                                          self._do_recommend, ret=True)
        for b in [self._fetch_btn, self._analyze_btn, self._rec_btn]:
            b.configure(state="disabled", fg=DIM)

        sep("DRAFT STRENGTH")
        bar_outer = tk.Frame(left, bg=PANEL)
        bar_outer.pack(fill="x", padx=8, pady=(0,8))
        bar_inner = tk.Frame(bar_outer, bg=PANEL)
        bar_inner.pack(anchor="center")
        self._blue_bar = VerticalBar(bar_inner, BLUE_T, "Blue")
        self._blue_bar.pack(side="left", padx=6)
        self._red_bar  = VerticalBar(bar_inner, RED_T,  "Red")
        self._red_bar.pack(side="left", padx=6)

    def _mk_btn(self, parent, text, cmd, accent=False, ret=False, space=True):
        bg  = ORANGE if accent else CARD
        fg  = DARK   if accent else TEXT
        abg = "#E07828" if accent else ORANGE
        label = self._s(text) if space else "\u200A".join(text)
        b   = tk.Button(parent, text=label, font=self._f(9),
                         fg=fg, bg=bg,
                         activebackground=abg, activeforeground=DARK,
                         relief="flat", bd=0, pady=7,
                         command=cmd, cursor="hand2",
                         disabledforeground=DIM)
        b.pack(fill="x", padx=12, pady=(0,4))
        if ret:
            return b

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=DARK)
        right.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        hf = tk.Frame(right, bg=DARK)
        hf.pack(fill="x", pady=(0,6))

        bt_canvas = OutlineText(hf, "BLUE TEAM", 16, BLUE_T, DARK,
                                 stroke_width=2, width=200, height=36)
        bt_canvas.set_font_family(self._ff)
        bt_canvas.pack(side="left", expand=True)

        rt_canvas = OutlineText(hf, "RED TEAM", 16, RED_T, DARK,
                                 stroke_width=2, width=200, height=36)
        rt_canvas.set_font_family(self._ff)
        rt_canvas.pack(side="left", expand=True)

        pf = tk.Frame(right, bg=DARK)
        pf.pack(fill="x", pady=(0,8))
        bc = tk.Frame(pf, bg=DARK)
        bc.pack(side="left", fill="both", expand=True, padx=(0,5))
        rc = tk.Frame(pf, bg=DARK)
        rc.pack(side="left", fill="both", expand=True, padx=(5,0))

        self._blue_pick_labels = {}
        self._red_pick_labels  = {}
        for role in ROLES:
            self._blue_pick_labels[role] = self._pick_card(bc, role, BLUE_T)
            self._red_pick_labels[role]  = self._pick_card(rc, role, RED_T)

        ban_f = tk.Frame(right, bg=PANEL)
        ban_f.pack(fill="x", pady=(0,8))
        tk.Label(ban_f, text=self._s("BANS"), font=self._f(10),
                 fg=ORANGE, bg=PANEL).pack(anchor="center", pady=(8,4))
        bg_inner = tk.Frame(ban_f, bg=PANEL)
        bg_inner.pack(fill="x", padx=12, pady=(0,10))
        self._blue_ban_lbls = []
        self._red_ban_lbls  = []
        tk.Label(bg_inner, text=self._s("BLUE"), font=self._f(9),
                 fg=BLUE_T, bg=PANEL, width=5).grid(row=0, column=0, padx=(0,6))
        tk.Label(bg_inner, text=self._s("RED"),  font=self._f(9),
                 fg=RED_T,  bg=PANEL, width=5).grid(row=1, column=0, padx=(0,6))
        for i in range(5):
            bg_inner.columnconfigure(i+1, weight=1)
            bl = tk.Label(bg_inner, text=self._s("—"), font=self._f(10),
                          fg=DIM, bg=CARD, pady=5, relief="flat",
                          width=10, anchor="center")
            bl.grid(row=0, column=i+1, padx=3, pady=2, sticky="ew")
            self._blue_ban_lbls.append(bl)
            rl = tk.Label(bg_inner, text=self._s("—"), font=self._f(10),
                          fg=DIM, bg=CARD, pady=5, relief="flat",
                          width=10, anchor="center")
            rl.grid(row=1, column=i+1, padx=3, pady=2, sticky="ew")
            self._red_ban_lbls.append(rl)

        bottom_f = tk.Frame(right, bg=DARK)
        bottom_f.pack(fill="both", expand=True)

        rec_f = tk.Frame(bottom_f, bg=PANEL)
        rec_f.place(relx=0, rely=0, relwidth=0.625, relheight=1.0)

        rec_top = tk.Frame(rec_f, bg=PANEL)
        rec_top.pack(fill="x", pady=(8,4))
        tk.Label(rec_top, text=self._s("RECOMMENDATIONS"), font=self._f(10),
                 fg=ORANGE, bg=PANEL).pack(side="left", padx=12)

        # toggle: all roles vs my role only
        self._my_role_only = tk.BooleanVar(value=False)
        role_border, self._role_toggle = self._outlined_btn(
            rec_top, "MY ROLE ONLY", self._toggle_role_filter, bg_parent=PANEL)
        role_border.pack(side="right", padx=12)
        self._my_role_lbl = tk.Label(rec_top, text="", font=(_SMALL, 8),
                                      fg=DIM, bg=PANEL)
        self._my_role_lbl.pack(side="right", padx=(0,4))

        # header row — same font as data rows so widths match exactly
        col_hdr = tk.Frame(rec_f, bg=PANEL)
        col_hdr.pack(fill="x", padx=12)
        tk.Label(col_hdr, text="CHAMPION", font=(_SMALL, 9, "bold"),
                 fg=DIM, bg=PANEL, width=20, anchor="w").pack(side="left")
        tk.Label(col_hdr, text="ROLE", font=(_SMALL, 9, "bold"),
                 fg=DIM, bg=PANEL, width=8, anchor="w").pack(side="left")
        tk.Label(col_hdr, text="STRENGTH", font=(_SMALL, 9, "bold"),
                 fg=DIM, bg=PANEL, width=10, anchor="w").pack(side="left")
        tk.Frame(rec_f, bg=ORANGE, height=1).pack(fill="x", padx=12, pady=(3,4))

        # scrollable container for rows
        rec_scroll_outer = tk.Frame(rec_f, bg=PANEL)
        rec_scroll_outer.pack(fill="both", expand=True, padx=12, pady=(0,10))

        canvas = tk.Canvas(rec_scroll_outer, bg=PANEL,
                           highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(rec_scroll_outer, orient="vertical",
                                  command=canvas.yview)
        self._rec_inner = tk.Frame(canvas, bg=PANEL)
        self._rec_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._rec_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # bind to the top-level window only while mouse is over the canvas
        canvas.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

        self._rec_canvas = canvas

        # placeholder
        self._rec_placeholder = tk.Label(
            self._rec_inner,
            text="Press 'GET RECOMMENDATIONS' to see suggested picks.",
            font=(_SMALL, 11), fg=DIM, bg=PANEL, anchor="w")
        self._rec_placeholder.pack(fill="x", pady=4)

        # ── CHAMP POOL PANEL ──────────────────────────────────────────────────
        pool_f = tk.Frame(bottom_f, bg=PANEL)
        pool_f.place(relx=0.630, rely=0, relwidth=0.370, relheight=1.0)

        pool_top = tk.Frame(pool_f, bg=PANEL)
        pool_top.pack(fill="x", pady=(8,4))
        tk.Label(pool_top, text=self._s("CHAMP POOL"), font=self._f(10),
                 fg=ORANGE, bg=PANEL).pack(side="left", padx=12)

        # toggle: filter recs to pool only
        self._pool_only = tk.BooleanVar(value=False)
        pool_border, self._pool_toggle = self._outlined_btn(
            pool_top, "ON", self._toggle_pool_filter, bg_parent=PANEL)
        pool_border.pack(side="right", padx=12)

        tk.Frame(pool_f, bg=ORANGE, height=1).pack(fill="x", padx=12, pady=(0,6))

        # text entry for champs
        tk.Label(pool_f, text="One champion per line",
                 font=(_SMALL, 8), fg=DIM, bg=PANEL, anchor="w"
                 ).pack(fill="x", padx=12)
        self._pool_text = tk.Text(
            pool_f, font=(_SMALL, 10),
            fg=TEXT, bg=CARD,
            insertbackground=TEXT, relief="flat",
            bd=4, highlightthickness=0,
            wrap="none")
        self._pool_text.pack(fill="both", expand=True, padx=12, pady=(4,10))

        # auto-save on edit with 1s debounce
        self._pool_save_job = None
        self._pool_text.bind("<<Modified>>", self._on_pool_edit)

        # load saved pool on startup
        self._load_pool()

    def _pick_card(self, parent, role, color):
        card = tk.Frame(parent, bg=CARD, height=74)
        card.pack(fill="x", pady=3)
        card.pack_propagate(False)
        tk.Label(card, text=self._s(role.upper()), font=self._f(11),
                 fg=color, bg=CARD, width=5).pack(side="left", padx=12)
        tk.Frame(card, bg=BORDER, width=1).pack(side="left", fill="y", pady=10)
        lbl = tk.Label(card, text=self._s("—"), font=self._f(13),
                        fg=DIM, bg=CARD, anchor="w")
        lbl.pack(side="left", padx=14, fill="both", expand=True)
        return lbl

    def _browse_lf(self):
        p = filedialog.askopenfilename(
            title="Select lockfile",
            filetypes=[("lockfile","lockfile"),("All","*.*")])
        if p:
            self._lockfile_var.set(p)

    def _browse_csv(self, var):
        p = filedialog.askopenfilename(title="Select CSV",
                                        filetypes=[("CSV","*.csv")])
        if p:
            var.set(p)

    def _set_status(self, msg, color=TEXT):
        self._status_lbl.configure(text=msg, fg=color)

    def _do_update_app(self):
        self._set_status("UPDATING...", ORANGE)

        def run():
            try:
                import urllib.request, zipfile, shutil, subprocess

                repo_zip_url = "https://github.com/nikhil-koka/draftsmith/archive/refs/heads/main.zip"
                exe_dir      = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
                               else os.path.dirname(os.path.abspath(__file__))
                zip_path     = os.path.join(exe_dir, "repo_update.zip")
                extract_path = os.path.join(exe_dir, "repo_update_tmp")

                # download full repo zip
                req = urllib.request.Request(repo_zip_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out:
                    out.write(resp.read())

                # extract
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(extract_path)
                os.remove(zip_path)

                # repo extracts into "draftsmith-main/"
                inner = os.path.join(extract_path, "draftsmith-main")

                # always update data files and draft_core
                for f in ["ranked_dataset.csv",
                          "2026_LoL_esports_match_data_from_OraclesElixir.csv",
                          "draft_core.py"]:
                    src = os.path.join(inner, f)
                    dst = os.path.join(exe_dir, f)
                    if os.path.exists(src):
                        shutil.copy2(src, dst)

                # update app itself
                if getattr(sys, "frozen", False):
                    src_exe = os.path.join(inner, "draftsmith.exe")
                    if os.path.exists(src_exe):
                        tmp_path = sys.executable + ".new"
                        bat_path = os.path.join(exe_dir, "update.bat")
                        shutil.copy2(src_exe, tmp_path)
                        with open(bat_path, "w") as f:
                            f.write(
                                f'@echo off\n'
                                f'timeout /t 2 /nobreak\n'
                                f'move /y "{tmp_path}" "{sys.executable}"\n'
                                f'start "" "{sys.executable}"\n'
                                f'del "%~f0"\n')
                        shutil.rmtree(extract_path, ignore_errors=True)
                        subprocess.Popen(bat_path, shell=True)
                        self.after(0, self.destroy)
                        return
                else:
                    src_py = os.path.join(inner, "draftsmith.py")
                    dst_py = os.path.abspath(__file__)
                    if os.path.exists(src_py):
                        shutil.copy2(src_py, dst_py)
                    shutil.rmtree(extract_path, ignore_errors=True)
                    subprocess.Popen([sys.executable, dst_py])
                    self.after(0, self.destroy)
                    return

                shutil.rmtree(extract_path, ignore_errors=True)
                self.after(0, self._set_status, "UPDATED — RE-INITIALIZE", GREEN)

            except Exception as e:
                self.after(0, self._set_status, f"UPDATE FAILED: {e}", "#FF4444")

        threading.Thread(target=run, daemon=True).start()

    def _do_init(self):
        ranked = self._ranked_var.get()
        pro    = self._pro_var.get()
        if not os.path.exists(ranked):
            messagebox.showerror("Missing file", f"Ranked CSV not found:\n{ranked}")
            return
        if not os.path.exists(pro):
            messagebox.showerror("Missing file", f"Pro CSV not found:\n{pro}")
            return
        self._set_status("INITIALIZING...", ORANGE)

        def run():
            try:
                import draft_core as dc
                dc.initialize(ranked, pro,
                              status_cb=lambda m: self.after(
                                  0, self._set_status, m.upper(), ORANGE))
                self.after(0, self._on_init_done)
            except Exception as e:
                self.after(0, self._set_status, f"ERROR: {e}", "#FF4444")
                self.after(0, lambda: messagebox.showerror("Init Error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_init_done(self):
        self._set_status("MODEL READY", GREEN)
        self._fetch_btn.configure(state="normal", fg=TEXT)

    def _do_fetch(self):
        lf = self._lockfile_var.get()
        if not os.path.exists(lf):
            messagebox.showerror("Lockfile not found",
                                  f"Could not find:\n{lf}\n\nMake sure League is running.")
            return
        self._set_status("FETCHING LOBBY...", ORANGE)

        def run():
            try:
                import draft_core as dc
                port, password = dc.read_lockfile(lf)
                self._port     = port
                self._password = password
                data           = dc.fetch_session(port, password)
                draft          = dc.parse_session(data, port, password)
                self._draft    = draft

                # detect local player role
                norm = {"bottom":"bot","utility":"sup","middle":"mid","jungle":"jng","top":"top"}
                my_cell = data.get("localPlayerCellId", -1)
                self._my_role = None
                for player in data.get("myTeam", []):
                    if player.get("cellId") == my_cell:
                        self._my_role = norm.get(player.get("assignedPosition",""), None)
                        break

                self.after(0, self._refresh_draft, draft)
                self.after(0, self._set_status, "LOBBY LOADED", GREEN)
                self.after(0, lambda: self._analyze_btn.configure(state="normal", fg=TEXT))
                self.after(0, lambda: self._rec_btn.configure(state="normal", fg=TEXT))
                role_txt = f"({self._my_role.upper()})" if self._my_role else ""
                self.after(0, lambda: self._my_role_lbl.configure(text=role_txt, fg=ORANGE))
            except Exception as e:
                self.after(0, self._set_status, f"ERROR: {e}", "#FF4444")
                self.after(0, lambda: messagebox.showerror("Fetch Error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _do_analyze(self):
        if not self._draft:
            messagebox.showinfo("No draft", "Fetch a lobby first.")
            return
        self._set_status("ANALYZING...", ORANGE)

        def run():
            try:
                import draft_core as dc
                t1, t2 = dc.evaluate_draft(self._draft)
                self.after(0, self._update_strength, t1, t2)
                self.after(0, self._set_status, "ANALYSIS COMPLETE", GREEN)
            except Exception as e:
                self.after(0, self._set_status, f"ERROR: {e}", "#FF4444")
                self.after(0, lambda: messagebox.showerror("Analyze Error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_pool_edit(self, event=None):
        # reset the Modified flag so we get future events
        self._pool_text.edit_modified(False)
        # cancel any pending save and reschedule 1s later
        if self._pool_save_job:
            self.after_cancel(self._pool_save_job)
        self._pool_save_job = self.after(1000, self._save_pool)

    def _pool_file(self):
        return os.path.join(_SCRIPT_DIR, "champ_pool.json")

    def _save_pool(self):
        import json
        entries = [l.strip() for l in self._pool_text.get("1.0", "end").splitlines() if l.strip()]
        try:
            with open(self._pool_file(), "w") as f:
                json.dump(entries, f)
        except Exception:
            pass

    def _load_pool(self):
        import json
        try:
            with open(self._pool_file()) as f:
                entries = json.load(f)
            self._pool_text.delete("1.0", "end")
            self._pool_text.insert("end", "\n".join(entries))
            self._pool_text.edit_modified(False)
        except Exception:
            pass

    def _toggle_pool_filter(self):
        self._pool_only.set(not self._pool_only.get())
        if self._pool_only.get():
            self._pool_toggle.configure(fg=DARK, bg=ORANGE)
            if not self._my_role_only.get():
                self._my_role_only.set(True)
                self._role_toggle.configure(fg=DARK, bg=ORANGE)
        else:
            self._pool_toggle.configure(fg=ORANGE, bg=PANEL)
        if self._draft:
            self._do_recommend()

    def _toggle_role_filter(self):
        self._my_role_only.set(not self._my_role_only.get())
        if self._my_role_only.get():
            self._role_toggle.configure(fg=DARK, bg=ORANGE)
        else:
            self._role_toggle.configure(fg=ORANGE, bg=PANEL)
        if self._draft:
            self._do_recommend()

    def _do_recommend(self):
        if not self._draft:
            messagebox.showinfo("No draft", "Fetch a lobby first.")
            return
        self._set_status("GENERATING RECOMMENDATIONS...", ORANGE)

        def run():
            try:
                import draft_core as dc
                role_filter = self._my_role if self._my_role_only.get() else None
                pool_filter = None
                if self._pool_only.get():
                    pool_filter = [l.strip() for l in self._pool_text.get("1.0", "end").splitlines() if l.strip()]
                df = dc.get_recommendations(self._draft, role_filter=role_filter, pool_filter=pool_filter)
                self.after(0, self._show_recs, df)
                self.after(0, self._set_status, "RECOMMENDATIONS READY", GREEN)
            except Exception as e:
                self.after(0, self._set_status, f"ERROR: {e}", "#FF4444")
                self.after(0, lambda: messagebox.showerror("Recommend Error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _refresh_draft(self, draft):
        # map actual side → UI label dicts
        blue_picks = self._blue_pick_labels
        red_picks  = self._red_pick_labels
        blue_bans  = self._blue_ban_lbls
        red_bans   = self._red_ban_lbls

        for tkey in ["team1", "team2"]:
            side        = draft[tkey]["side"]
            pick_labels = blue_picks if side == "Blue" else red_picks
            ban_labels  = blue_bans  if side == "Blue" else red_bans

            for role in ROLES:
                p = draft[tkey]["Picks"].get(role)
                pick_labels[role].configure(
                    text=self._s(p.upper()) if p else "—",
                    fg=TEXT if p else DIM)

            for i, lbl in enumerate(ban_labels):
                b    = draft[tkey]["Bans"][i] if i < len(draft[tkey]["Bans"]) else None
                txt  = self._s(b.upper()) if b else "—"
                size = 8 if b and len(b) > 9 else 10
                lbl.configure(text=txt, fg="#FF6B6B" if b else DIM,
                              font=self._f(size))

    def _update_strength(self, t1, t2):
        self._blue_bar.set_value(max(0, min(1, t1/100)), f"{t1:.1f}")
        self._red_bar.set_value( max(0, min(1, t2/100)), f"{t2:.1f}")

    def _show_recs(self, df):
        # clear old rows
        for widget in self._rec_inner.winfo_children():
            widget.destroy()

        if df.empty:
            tk.Label(self._rec_inner,
                     text="No recommendations — all roles filled or no matchup data.",
                     font=(_SMALL, 11), fg=DIM, bg=PANEL, anchor="w"
                     ).pack(fill="x", pady=4)
            return

        for _, row in df.iterrows():
            champ    = row["Champion"]
            role     = row["Role"].upper()
            strength = f"{row['Strength']:>+.2f}"

            # shrink font for long champion names
            font_size = 11 if len(champ) <= 12 else 9

            r = tk.Frame(self._rec_inner, bg=PANEL)
            r.pack(fill="x", pady=1)

            tk.Label(r, text=champ, font=(_SMALL, font_size),
                     fg=TEXT, bg=PANEL, width=20, anchor="w").pack(side="left")
            tk.Label(r, text=role, font=(_SMALL, 11),
                     fg=DIM, bg=PANEL, width=8, anchor="w").pack(side="left")
            color = GREEN if row["Strength"] >= 0 else "#FF4444"
            tk.Label(r, text=strength, font=(_SMALL, 11),
                     fg=color, bg=PANEL, width=10, anchor="w").pack(side="left")


if __name__ == "__main__":
    app = DraftApp()
    app.mainloop()
