"""
TikTok Auto Unrepost - Aplicación de Escritorio (GUI)
Aplicación gráfica independiente con interfaz moderna oscura, control de hilos en tiempo real,
estadísticas en vivo, logs interactivos y comandos de pausa/reinicio.
"""

import os
import sys
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

TIKTOK_URL = "https://www.tiktok.com"

# ==============================================================================
# MOTOR DE AUTOMATIZACIÓN (SELENIUM CORE)
# ==============================================================================

class SeleniumWorker:
    def __init__(self, log_callback, stats_callback, status_callback):
        self.driver = None
        self.log = log_callback
        self.update_stats = stats_callback
        self.update_status = status_callback

        self.is_running = False
        self.is_paused = False
        self.restart_flag = False

        self.deleted_count = 0
        self.skipped_count = 0
        self.video_index = 0
        self.consecutive_fails = 0
        self.batch_size = 35
        self.cooldown_seconds = 18

        self.speed_delay = 0.8  # Segundos entre videos

    def open_browser(self):
        if self.driver:
            try:
                self.driver.current_url
                self.log("Navegador ya está abierto.", "info")
                return
            except Exception:
                self.driver = None

        self.log("Abriendo Google Chrome optimizado...", "info")
        self.update_status("Abriendo navegador...")

        def _launch():
            try:
                options = webdriver.ChromeOptions()
                options.add_argument("--start-maximized")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option("useAutomationExtension", False)

                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                self.driver.get(TIKTOK_URL)

                self.log("Chrome listo. Por favor inicia sesión y abre el primer video en Reposts.", "success")
                self.update_status("Navegador listo")
            except Exception as e:
                self.log(f"Error al iniciar Chrome: {e}", "error")
                self.update_status("Error al abrir navegador")

        threading.Thread(target=_launch, daemon=True).start()

    def start_loop(self):
        if not self.driver:
            messagebox.showwarning("Atención", "Primero debes abrir el navegador con el botón '1. Abrir Navegador'.")
            return

        if self.is_running:
            return

        self.is_running = True
        self.is_paused = False
        self.restart_flag = False
        self.update_status("Ejecutando")
        self.log("🚀 Iniciando limpieza automática continua...", "success")

        threading.Thread(target=self._run_loop, daemon=True).start()

    def toggle_pause(self):
        if not self.is_running:
            return False

        self.is_paused = not self.is_paused
        if self.is_paused:
            self.update_status("En Pausa")
            self.log("⏸ Proceso en pausa. (Puedes moverte en Chrome o esperar).", "warn")
        else:
            self.update_status("Ejecutando")
            self.log("▶ Reanudando proceso...", "success")
        return self.is_paused

    def trigger_restart(self):
        if not self.is_running:
            self.start_loop()
            return

        self.restart_flag = True
        self.is_paused = False
        self.log("🔄 Reiniciando lectura sobre el video actual en pantalla...", "warn")
        self.update_status("Reiniciando ciclo")

    def stop_loop(self):
        self.is_running = False
        self.is_paused = False
        self.update_status("Detenido")
        self.log(f"⏹ Limpieza detenida. Total eliminados: {self.deleted_count}, Omitidos: {self.skipped_count}", "warn")

    def close_all(self):
        self.is_running = False
        self.is_paused = False
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _run_loop(self):
        while self.is_running:
            # Manejo de pausa
            while self.is_paused and self.is_running:
                time.sleep(0.2)

            if not self.is_running:
                break

            if self.restart_flag:
                self.restart_flag = False
                time.sleep(0.5)

            self.video_index += 1
            self.log(f"[#{self.video_index}] Buscando botón amarillo...", "info")

            # 1. Localizar el botón amarillo
            yellow_btn = None
            for _ in range(12):
                if not self.is_running:
                    break
                yellow_btn = self._find_yellow_repost_button()
                if yellow_btn:
                    break
                time.sleep(0.1)

            if not self.is_running:
                break

            # 2. Pulsar botón amarillo si existe
            if yellow_btn:
                # Realizar UN ÚNICO CLIC físico (nunca hacer doble clic para no volver a compartir)
                self._physical_click(yellow_btn)
                time.sleep(0.6)  # Esperar respuesta del servidor de TikTok

                # Confirmación: verificar si el botón amarillo desapareció
                still_yellow = self._find_yellow_repost_button()

                if not still_yellow:
                    self.deleted_count += 1
                    self.consecutive_fails = 0
                    self.log(f"  -> 🟡 ¡CONFIRMADO! Compartido eliminado #{self.deleted_count}", "success")

                    # Pausa de enfriamiento por lote (Anti-Rate Limit)
                    if self.deleted_count % self.batch_size == 0:
                        self._run_cooling_cooldown(self.cooldown_seconds, f"Lote de {self.deleted_count} completado")
                else:
                    self.consecutive_fails += 1
                    self.log("  -> ⚠️ No se desmarcó (TikTok ignoró el clic o lag). Pasando al siguiente...", "warn")
                    if self.consecutive_fails >= 3:
                        self.log("⚠️ 3 rechazos seguidos detectados. TikTok activó freno temporal.", "error")
                        self._run_cooling_cooldown(40, "Pausa de seguridad por Rate Limit")
                        self.consecutive_fails = 0
            else:
                self.skipped_count += 1
                self.log("  -> ⏭️ No tiene botón amarillo (no compartido o ya retirado)", "info")

            self.update_stats(self.deleted_count, self.skipped_count)

            if not self.is_running:
                break

            # 3. Bajar al siguiente video (v)
            moved = self._go_to_next_video()
            if not moved and self.is_running:
                time.sleep(0.5)
                moved = self._go_to_next_video()
                if not moved and self.is_running:
                    self.log("⚠️ No se pudo bajar más (fin de la lista cargada o se trabó).", "warn")
                    self.log("    Entrando en pausa automática para que puedas recargar la página (F5).", "warn")
                    self.is_paused = True
                    self.update_status("En Pausa (Fin de lista)")
                    continue

            # Pausa configurable entre videos
            time.sleep(max(0.3, self.speed_delay))

        self.update_status("Detenido")

    def _run_cooling_cooldown(self, seconds, reason="Lote completado"):
        self.log(f"❄️ {reason}: Pausa de enfriamiento anti-rate limit ({seconds}s)...", "warn")
        for remaining in range(seconds, 0, -1):
            if not self.is_running:
                break
            if self.is_paused:
                break
            self.update_status(f"Enfriando ({remaining}s)")
            time.sleep(1)
        if self.is_running and not self.is_paused:
            self.update_status("Ejecutando")
            self.log("▶ Enfriamiento completado. Continuando con el siguiente lote...", "success")

    def _find_yellow_repost_button(self):
        js = """
        return (function() {
            function isYellowColor(str) {
                if (!str) return false;
                if (/#(face15|f5c344|ffcc00|ffd700|eab308|facc15|f7b500|ffbe00)/i.test(str)) return true;
                const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
                if (m) {
                    const r = parseInt(m[1], 10);
                    const g = parseInt(m[2], 10);
                    const b = parseInt(m[3], 10);
                    if (r > 200 && g > 150 && b < 95) return true;
                }
                return false;
            }

            // 1. Buscar únicamente en botones interactivos de la barra de acciones (excluyendo comentarios)
            const candidates = document.querySelectorAll('button, [role="button"], a');
            for (const btn of candidates) {
                if (btn.closest('[data-e2e="comment-list"], [class*="CommentList"], [class*="comment-list"]')) {
                    continue;
                }
                const rect = btn.getBoundingClientRect();
                if (rect.width < 14 || rect.width > 80 || rect.height < 14 || rect.height > 80) continue;
                if (rect.top < 0 || rect.left < 0) continue;

                const style = window.getComputedStyle(btn);
                if (isYellowColor(style.backgroundColor)) {
                    return btn;
                }

                // Revisar si algún svg, path o círculo interno tiene color amarillo
                const inners = btn.querySelectorAll('svg, path, circle, span, div');
                for (const el of inners) {
                    const s = window.getComputedStyle(el);
                    const fill = el.getAttribute('fill') || s.fill || '';
                    const bg = s.backgroundColor || '';
                    if (isYellowColor(fill) || isYellowColor(bg)) {
                        return btn;
                    }
                }
            }

            // 2. Respaldo por texto explícito de 'Eliminar la publicación compartida'
            const ariaNodes = document.querySelectorAll('[aria-label], [title]');
            for (const el of ariaNodes) {
                if (el.closest('[data-e2e="comment-list"], [class*="CommentList"]')) continue;
                const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '')).toLowerCase();
                if (label.includes('eliminar la publicación compartida') ||
                    label.includes('eliminar la publicacion compartida') ||
                    label.includes('remove repost')) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return el.closest('button, [role="button"]') || el;
                    }
                }
            }

            return null;
        })();
        """
        try:
            return self.driver.execute_script(js)
        except Exception:
            return None

    def _physical_click(self, element):
        try:
            actions = ActionChains(self.driver)
            actions.move_to_element(element).pause(0.12).click().perform()
            return True
        except Exception:
            pass

        try:
            self.driver.execute_script("""
                const el = arguments[0];
                const rect = el.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y };
                el.dispatchEvent(new PointerEvent('pointerdown', opts));
                el.dispatchEvent(new MouseEvent('mousedown', opts));
                el.dispatchEvent(new PointerEvent('pointerup', opts));
                el.dispatchEvent(new MouseEvent('mouseup', opts));
                el.dispatchEvent(new MouseEvent('click', opts));
            """, element)
            return True
        except Exception:
            return False

    def _go_to_next_video(self):
        prev_url = ""
        try:
            prev_url = self.driver.current_url
        except Exception:
            return False

        js_arrow = """
        return (function() {
            const selectors = [
                'button[data-e2e="arrow-right"]',
                'button[data-e2e="arrow-down"]',
                'button[data-e2e="nav-arrow-down"]',
                'button[aria-label*="siguiente" i]',
                'button[aria-label*="next" i]'
            ];
            for (const s of selectors) {
                const btn = document.querySelector(s);
                if (btn && btn.getBoundingClientRect().width > 0 && !btn.disabled) {
                    return btn;
                }
            }
            return null;
        })();
        """
        try:
            down_btn = self.driver.execute_script(js_arrow)
            if down_btn:
                ActionChains(self.driver).move_to_element(down_btn).pause(0.05).click().perform()
                time.sleep(0.4)
                if self.driver.current_url != prev_url:
                    return True
        except Exception:
            pass

        try:
            ActionChains(self.driver).send_keys(Keys.ARROW_DOWN).perform()
            time.sleep(0.4)
            if self.driver.current_url != prev_url:
                return True
        except Exception:
            pass

        return False


# ==============================================================================
# INTERFAZ GRÁFICA DE USUARIO (TKINTER GUI - DARK MODERN THEME)
# ==============================================================================

class TikTokUnrepostApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TikTok Auto Unrepost - App de Escritorio")
        self.root.geometry("640x720")
        self.root.minsize(560, 620)
        self.root.configure(bg="#121212")

        # Paleta de colores
        self.c_bg = "#121212"
        self.c_card = "#1E1E1E"
        self.c_card_border = "#2A2A2A"
        self.c_cyan = "#25F4EE"
        self.c_pink = "#FE2C55"
        self.c_yellow = "#FACE15"
        self.c_text = "#FFFFFF"
        self.c_text_muted = "#A0A0A0"

        self.msg_queue = queue.Queue()

        # Inicializar Selenium Worker
        self.worker = SeleniumWorker(
            log_callback=self.enqueue_log,
            stats_callback=self.enqueue_stats,
            status_callback=self.enqueue_status
        )

        self._build_ui()
        self.root.after(100, self._process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Header superior
        header_frame = tk.Frame(self.root, bg=self.c_card, highlightthickness=1, highlightbackground=self.c_card_border)
        header_frame.pack(fill="x", padx=16, pady=(16, 10))

        title_box = tk.Frame(header_frame, bg=self.c_card)
        title_box.pack(fill="x", padx=16, pady=12)

        icon_label = tk.Label(title_box, text="⚡", font=("Segoe UI", 16, "bold"), fg=self.c_cyan, bg=self.c_card)
        icon_label.pack(side="left", padx=(0, 8))

        title_label = tk.Label(title_box, text="TikTok Auto Unrepost Pro", font=("Segoe UI", 14, "bold"), fg=self.c_text, bg=self.c_card)
        title_label.pack(side="left")

        self.status_badge = tk.Label(title_box, text="DETENIDO", font=("Segoe UI", 9, "bold"), fg="#FF4444", bg="#2A1B1E", padx=8, pady=3)
        self.status_badge.pack(side="right")

        # Tarjetas de Estadísticas
        stats_frame = tk.Frame(self.root, bg=self.c_bg)
        stats_frame.pack(fill="x", padx=16, pady=6)
        stats_frame.columnconfigure(0, weight=1)
        stats_frame.columnconfigure(1, weight=1)

        # Card Eliminados
        card_del = tk.Frame(stats_frame, bg=self.c_card, highlightthickness=1, highlightbackground=self.c_card_border)
        card_del.grid(row=0, column=0, padx=(0, 6), sticky="nsew")

        self.lbl_deleted_num = tk.Label(card_del, text="0", font=("Segoe UI", 26, "bold"), fg=self.c_cyan, bg=self.c_card)
        self.lbl_deleted_num.pack(pady=(10, 0))

        lbl_del_txt = tk.Label(card_del, text="COMPARTIDOS ELIMINADOS", font=("Segoe UI", 9, "bold"), fg=self.c_text_muted, bg=self.c_card)
        lbl_del_txt.pack(pady=(0, 10))

        # Card Omitidos
        card_skip = tk.Frame(stats_frame, bg=self.c_card, highlightthickness=1, highlightbackground=self.c_card_border)
        card_skip.grid(row=0, column=1, padx=(6, 0), sticky="nsew")

        self.lbl_skipped_num = tk.Label(card_skip, text="0", font=("Segoe UI", 26, "bold"), fg=self.c_text_muted, bg=self.c_card)
        self.lbl_skipped_num.pack(pady=(10, 0))

        lbl_skip_txt = tk.Label(card_skip, text="VIDEOS OMITIDOS / YA QUITADOS", font=("Segoe UI", 9, "bold"), fg=self.c_text_muted, bg=self.c_card)
        lbl_skip_txt.pack(pady=(0, 10))

        # Panel de Controles
        ctrl_frame = tk.Frame(self.root, bg=self.c_card, highlightthickness=1, highlightbackground=self.c_card_border)
        ctrl_frame.pack(fill="x", padx=16, pady=8)

        # Paso 1: Abrir navegador
        step1_box = tk.Frame(ctrl_frame, bg=self.c_card)
        step1_box.pack(fill="x", padx=14, pady=(12, 6))

        lbl_step1 = tk.Label(step1_box, text="Paso 1: Inicia sesión en TikTok y abre el 1er video en Reposts", font=("Segoe UI", 9), fg=self.c_text_muted, bg=self.c_card)
        lbl_step1.pack(side="left")

        btn_open = tk.Button(step1_box, text="🌐 1. Abrir Navegador", font=("Segoe UI", 9, "bold"), bg="#2A2A2A", fg=self.c_cyan, activebackground="#333333", activeforeground=self.c_cyan, bd=0, padx=12, pady=6, cursor="hand2", command=self.worker.open_browser)
        btn_open.pack(side="right")

        # Separador sutil
        sep = tk.Frame(ctrl_frame, height=1, bg=self.c_card_border)
        sep.pack(fill="x", padx=14, pady=6)

        # Paso 2: Botones principales de acción
        action_box = tk.Frame(ctrl_frame, bg=self.c_card)
        action_box.pack(fill="x", padx=14, pady=(4, 12))
        action_box.columnconfigure(0, weight=2)
        action_box.columnconfigure(1, weight=1)
        action_box.columnconfigure(2, weight=1)
        action_box.columnconfigure(3, weight=1)

        self.btn_start = tk.Button(action_box, text="▶ Iniciar", font=("Segoe UI", 10, "bold"), bg=self.c_cyan, fg="#000000", activebackground="#1ED0CA", activeforeground="#000000", bd=0, pady=8, cursor="hand2", command=self.worker.start_loop)
        self.btn_start.grid(row=0, column=0, padx=(0, 4), sticky="nsew")

        self.btn_pause = tk.Button(action_box, text="⏸ Pausar [P]", font=("Segoe UI", 9, "bold"), bg="#333333", fg=self.c_text, activebackground="#444444", activeforeground=self.c_text, bd=0, pady=8, cursor="hand2", command=self._on_pause_click)
        self.btn_pause.grid(row=0, column=1, padx=4, sticky="nsew")

        self.btn_restart = tk.Button(action_box, text="🔄 Reiniciar [R]", font=("Segoe UI", 9, "bold"), bg="#333333", fg=self.c_yellow, activebackground="#444444", activeforeground=self.c_yellow, bd=0, pady=8, cursor="hand2", command=self.worker.trigger_restart)
        self.btn_restart.grid(row=0, column=2, padx=4, sticky="nsew")

        self.btn_stop = tk.Button(action_box, text="⏹ Detener", font=("Segoe UI", 9, "bold"), bg="#333333", fg=self.c_pink, activebackground="#444444", activeforeground=self.c_pink, bd=0, pady=8, cursor="hand2", command=self.worker.stop_loop)
        self.btn_stop.grid(row=0, column=3, padx=(4, 0), sticky="nsew")

        # Control de Velocidad
        speed_frame = tk.Frame(self.root, bg=self.c_card, highlightthickness=1, highlightbackground=self.c_card_border)
        speed_frame.pack(fill="x", padx=16, pady=4)

        speed_inner = tk.Frame(speed_frame, bg=self.c_card)
        speed_inner.pack(fill="x", padx=14, pady=8)

        lbl_speed_title = tk.Label(speed_inner, text="Velocidad / Pausa entre videos:", font=("Segoe UI", 9), fg=self.c_text_muted, bg=self.c_card)
        lbl_speed_title.pack(side="left")

        self.speed_var = tk.DoubleVar(value=0.8)
        self.lbl_speed_val = tk.Label(speed_inner, text="0.8s (Turbo)", font=("Segoe UI", 9, "bold"), fg=self.c_cyan, bg=self.c_card)
        self.lbl_speed_val.pack(side="right")

        slider = ttk.Scale(speed_frame, from_=0.4, to=3.0, variable=self.speed_var, command=self._on_slider_change)
        slider.pack(fill="x", padx=14, pady=(0, 10))

        # Consola / Log en Tiempo Real
        log_frame = tk.Frame(self.root, bg=self.c_card, highlightthickness=1, highlightbackground=self.c_card_border)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(6, 12))

        log_header = tk.Frame(log_frame, bg=self.c_card)
        log_header.pack(fill="x", padx=12, pady=(8, 4))

        lbl_log_title = tk.Label(log_header, text="REGISTRO DE ACTIVIDAD EN VIVO", font=("Segoe UI", 8, "bold"), fg=self.c_text_muted, bg=self.c_card)
        lbl_log_title.pack(side="left")

        btn_clear = tk.Label(log_header, text="Limpiar log", font=("Segoe UI", 8, "underline"), fg=self.c_text_muted, bg=self.c_card, cursor="hand2")
        btn_clear.pack(side="right")
        btn_clear.bind("<Button-1>", lambda e: self.log_box.delete("1.0", tk.END))

        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            bg="#0D0D0D",
            fg="#E0E0E0",
            insertbackground="#FFFFFF",
            font=("Consolas", 9),
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Configurar tags de color para el log
        self.log_box.tag_configure("success", foreground=self.c_cyan)
        self.log_box.tag_configure("warn", foreground=self.c_yellow)
        self.log_box.tag_configure("error", foreground=self.c_pink)
        self.log_box.tag_configure("info", foreground="#A0A0A0")
        self.log_box.tag_configure("time", foreground="#555555")

        self.log("Aplicación lista. Haz clic en '1. Abrir Navegador' para comenzar.", "info")

        # Shortcuts globales de teclado en la ventana
        self.root.bind("<p>", lambda e: self._on_pause_click())
        self.root.bind("<P>", lambda e: self._on_pause_click())
        self.root.bind("<r>", lambda e: self.worker.trigger_restart())
        self.root.bind("<R>", lambda e: self.worker.trigger_restart())
        self.root.bind("<space>", lambda e: self._on_pause_click())

    def _on_slider_change(self, val):
        sec = round(float(val), 1)
        self.worker.speed_delay = sec
        label = f"{sec:.1f}s"
        if sec <= 0.8:
            label += " (Turbo)"
        elif sec <= 1.5:
            label += " (Rápido)"
        else:
            label += " (Seguro)"
        self.lbl_speed_val.config(text=label)

    def _on_pause_click(self):
        is_paused = self.worker.toggle_pause()
        if is_paused:
            self.btn_pause.config(text="▶ Reanudar [P]", fg=self.c_cyan)
        else:
            self.btn_pause.config(text="⏸ Pausar [P]", fg=self.c_text)

    # Métodos de cola para llamadas thread-safe
    def enqueue_log(self, text, tag="info"):
        self.msg_queue.put(("log", text, tag))

    def enqueue_stats(self, deleted, skipped):
        self.msg_queue.put(("stats", deleted, skipped))

    def enqueue_status(self, status):
        self.msg_queue.put(("status", status))

    def _process_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                mtype = msg[0]

                if mtype == "log":
                    tstr = time.strftime("[%H:%M:%S] ")
                    self.log_box.insert(tk.END, tstr, "time")
                    self.log_box.insert(tk.END, msg[1] + "\n", msg[2])
                    self.log_box.see(tk.END)

                elif mtype == "stats":
                    self.lbl_deleted_num.config(text=str(msg[1]))
                    self.lbl_skipped_num.config(text=str(msg[2]))

                elif mtype == "status":
                    status = msg[1]
                    self.status_badge.config(text=status.upper())
                    if "ejecutando" in status.lower():
                        self.status_badge.config(fg=self.c_cyan, bg="#122B2A")
                    elif "pausa" in status.lower():
                        self.status_badge.config(fg=self.c_yellow, bg="#2B2812")
                    elif "error" in status.lower():
                        self.status_badge.config(fg=self.c_pink, bg="#2B1216")
                    else:
                        self.status_badge.config(fg="#888888", bg="#222222")

        except queue.Empty:
            pass

        self.root.after(80, self._process_queue)

    def log(self, text, tag="info"):
        self.enqueue_log(text, tag)

    def _on_close(self):
        if messagebox.askokcancel("Salir", "¿Deseas cerrar la aplicación y el navegador?"):
            self.worker.close_all()
            self.root.destroy()

def main():
    root = tk.Tk()
    # Icono si es posible
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    app = TikTokUnrepostApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
