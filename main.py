"""VY Glow — управление BLE LED-лентой (BJ_LED_M). PySide6 + Bleak."""
import asyncio
import sys
import threading

from bleak import BleakClient
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget, QFrame,
    QMenu, QSystemTrayIcon,
)

ADDRESS = "4FE2675F-A6FE-8861-15D2-18EC1C593597"
UUID = "0000ee02-0000-1000-8000-00805f9b34fb"

CMD_ON = bytes.fromhex("69 96 06 01 01")    # проверено на устройстве
CMD_OFF = bytes.fromhex("69 96 02 01 00")   # описана в протоколе семейства BJ_LED
GAMMA = 2.0   # кривая яркости: больше -> ползунок темнее в нижней половине
MAX_MODE = 21  # эффекты: байт режима 0x00..0x15


def color_packet(r: int, g: int, b: int) -> bytes:
    """69 96 05 02 RR GG BB (красный проверен, остальное — гипотеза)."""
    return bytes([0x69, 0x96, 0x05, 0x02, r, g, b])


def mode_packet(mode: int, param: int) -> bytes:
    """ЭКСПЕРИМЕНТ: 69 96 03 03 <режим> <параметр> (по описанию семейства BJ_LED)."""
    return bytes([0x69, 0x96, 0x03, 0x03, mode, param])


PRESETS = [
    ("Красный", (255, 0, 0)), ("Зелёный", (0, 255, 0)), ("Синий", (0, 0, 255)), ("Фиолетовый", (150, 0, 255)),
    ("Белый", (255, 255, 255)), ("Жёлтый", (255, 255, 0)), ("Голубой", (0, 255, 255)),
    ("Пурпурный", (255, 0, 255)),
]


def dot_icon(rgb, ring=False):
    """Круглая иконка для строки меню и пунктов меню (кольцо = лента выключена)."""
    pm = QPixmap(44, 44)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if ring:
        p.setPen(QPen(QColor(150, 150, 155), 4))
        p.setBrush(Qt.NoBrush)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*rgb))
    p.drawEllipse(6, 6, 32, 32)
    p.end()
    return QIcon(pm)


class BleController(QObject):
    """Своя asyncio-петля в отдельном потоке; одно соединение, команды по очереди."""
    log = Signal(str)
    connected_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self.lock = None  # создаётся внутри петли

    def run(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        fut.add_done_callback(self._done)

    def _done(self, fut):
        exc = fut.exception()
        if exc:
            self.log.emit(f"ОШИБКА: {exc!r}")

    async def _lock(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        return self.lock

    async def _ensure(self):
        if self.client and self.client.is_connected:
            return
        self.log.emit(f"Подключение к {ADDRESS} ...")
        self.client = BleakClient(ADDRESS, timeout=20,
                                  disconnected_callback=self._on_disc)
        await self.client.connect()
        self.log.emit("Подключено")
        self.connected_changed.emit(True)

    def _on_disc(self, _client):
        self.log.emit("Соединение разорвано")
        self.connected_changed.emit(False)

    async def connect(self):
        async with await self._lock():
            await self._ensure()

    async def disconnect(self):
        async with await self._lock():
            if self.client and self.client.is_connected:
                await self.client.disconnect()

    async def send(self, packets, delay=0.5):
        """Отправить пакеты одним блоком в одном соединении, с паузой между ними."""
        async with await self._lock():
            await self._ensure()
            for i, p in enumerate(packets):
                if i:
                    await asyncio.sleep(delay)
                await self.client.write_gatt_char(UUID, p, response=False)
                self.log.emit(f"-> ee02: {p.hex(' ').upper()}")


STYLE = """
QWidget#root { background: #1c1c1e; }
QWidget { color: #f5f5f7; font-size: 14px; }
QLabel { background: transparent; }
QLabel#title { font-size: 24px; font-weight: 600; }
QLabel#muted { color: #8e8e93; }
QLabel#section { color: #8e8e93; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QFrame#card { background: #2c2c2e; border: none; border-radius: 14px; }
QPushButton { background: #3a3a3c; border: none; border-radius: 10px; padding: 9px 14px; }
QPushButton:hover { background: #48484a; }
QPushButton:pressed { background: #545456; }
QPushButton#on, QPushButton#accent { background: #0a84ff; color: #ffffff; font-weight: 500; }
QPushButton#on:hover, QPushButton#accent:hover { background: #3395ff; }
QPushButton#off { color: #ff453a; font-weight: 500; }
QPushButton#link { background: transparent; color: #8e8e93; text-align: left; padding: 4px; }
QPushButton#link:hover { color: #f5f5f7; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #48484a; }
QSlider::sub-page:horizontal { border-radius: 2px; background: #0a84ff; }
QSlider::handle:horizontal { width: 22px; height: 22px; margin: -9px 0; border-radius: 11px; background: #ffffff; }
QSpinBox, QLineEdit, QPlainTextEdit { background: #3a3a3c; border: none; border-radius: 8px; padding: 6px; color: #f5f5f7; }
"""


def card():
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(10)
    return f, lay


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("VY Glow")
        self.setStyleSheet(STYLE)
        self.ble = BleController()
        self.ble.log.connect(self.append_log)
        self.ble.connected_changed.connect(self.on_connected)
        self.rgb = (255, 0, 0)
        self.powered_off = False
        self.mode = 0
        self.sleep_left = 0
        self.really_quit = False
        self.debounce = QTimer(self, singleShot=True, interval=150)
        self.debounce.timeout.connect(self.apply_color)
        self.tick = QTimer(self, interval=1000)
        self.tick.timeout.connect(self.on_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # шапка
        title = QLabel("VY Glow")
        title.setObjectName("title")
        self.status = QLabel("● не подключено")
        self.status.setObjectName("muted")
        self.btn_conn = QPushButton("Подключить")
        self.btn_conn.clicked.connect(self.toggle_connection)
        top = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(title)
        box.addWidget(self.status)
        top.addLayout(box, 1)
        top.addWidget(self.btn_conn)
        root.addLayout(top)

        # основная карточка: превью, питание, цвета, яркость
        c1, l1 = card()
        self.preview = QFrame()
        self.preview.setFixedSize(88, 88)
        prow = QHBoxLayout()
        prow.addStretch()
        prow.addWidget(self.preview)
        prow.addStretch()
        l1.addLayout(prow)

        b_on, b_off = QPushButton("Включить"), QPushButton("Выключить")
        b_on.setObjectName("on")
        b_off.setObjectName("off")
        b_on.clicked.connect(self.power_on)
        b_off.clicked.connect(self.power_off)
        row = QHBoxLayout()
        row.addWidget(b_on)
        row.addWidget(b_off)
        l1.addLayout(row)

        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.swatches = []
        for name, rgb in PRESETS:
            b = QPushButton()
            b.setFixedSize(32, 32)
            b.setToolTip(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=rgb: self.set_color(c))
            self.swatches.append((b, rgb))
            prow.addWidget(b)
        l1.addLayout(prow)

        pick = QPushButton("Свой цвет…")
        pick.clicked.connect(self.pick_color)
        l1.addWidget(pick)

        self.bright_label = QLabel("Яркость 100%")
        self.bright_label.setObjectName("muted")
        self.bright = QSlider(Qt.Horizontal)
        self.bright.setRange(1, 100)
        self.bright.setValue(100)
        self.bright.valueChanged.connect(self.on_bright)
        l1.addWidget(self.bright_label)
        l1.addWidget(self.bright)
        root.addWidget(c1)

        # эффекты (эксперимент)
        c2, l2 = card()
        h = QLabel("ЭФФЕКТЫ (ЭКСПЕРИМЕНТ)")
        h.setObjectName("section")
        l2.addWidget(h)
        er = QHBoxLayout()
        b_prev, b_next = QPushButton("‹"), QPushButton("›")
        b_prev.setFixedWidth(46)
        b_next.setFixedWidth(46)
        self.mode_label = QLabel("Режим 0")
        self.mode_label.setAlignment(Qt.AlignCenter)
        b_prev.clicked.connect(lambda: self.step_mode(-1))
        b_next.clicked.connect(lambda: self.step_mode(1))
        er.addWidget(b_prev)
        er.addWidget(self.mode_label, 1)
        er.addWidget(b_next)
        l2.addLayout(er)
        pr = QHBoxLayout()
        pl = QLabel("Параметр (скорость?)")
        pl.setObjectName("muted")
        self.param = QSpinBox()
        self.param.setButtonSymbols(QSpinBox.NoButtons)
        self.param.setAlignment(Qt.AlignCenter)
        self.param.setFixedWidth(56)
        self.param.setRange(0, 255)
        self.param.setValue(1)
        b_play = QPushButton("Запустить")
        b_play.setObjectName("accent")
        b_play.clicked.connect(self.send_mode)
        pr.addWidget(pl, 1)
        pr.addWidget(self.param)
        pr.addWidget(b_play)
        l2.addLayout(pr)
        hint = QLabel("Смена цвета или яркости останавливает эффект.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        l2.addWidget(hint)
        root.addWidget(c2)

        # таймер отключения
        c3, l3 = card()
        h = QLabel("ТАЙМЕР ОТКЛЮЧЕНИЯ")
        h.setObjectName("section")
        l3.addWidget(h)
        chips = QHBoxLayout()
        self.minutes = QSpinBox()
        self.minutes.setButtonSymbols(QSpinBox.NoButtons)
        self.minutes.setAlignment(Qt.AlignCenter)
        self.minutes.setFixedWidth(84)
        self.minutes.setRange(1, 720)
        self.minutes.setValue(30)
        self.minutes.setSuffix(" мин")
        for label, m in (("15м", 15), ("30м", 30), ("1ч", 60), ("2ч", 120)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, v=m: self.minutes.setValue(v))
            chips.addWidget(b)
        chips.addWidget(self.minutes)
        l3.addLayout(chips)
        tr = QHBoxLayout()
        self.timer_label = QLabel("Таймер не запущен")
        self.timer_label.setObjectName("muted")
        self.btn_timer = QPushButton("Запустить")
        self.btn_timer.setObjectName("accent")
        self.btn_timer.clicked.connect(self.toggle_timer)
        tr.addWidget(self.timer_label, 1)
        tr.addWidget(self.btn_timer)
        l3.addLayout(tr)
        root.addWidget(c3)

        # отладка (свёрнута)
        self.dbg_btn = QPushButton("Отладка ▸")
        self.dbg_btn.setObjectName("link")
        self.dbg_btn.setCheckable(True)
        self.dbg_btn.toggled.connect(self.toggle_debug)
        root.addWidget(self.dbg_btn)

        self.dbg = QWidget()
        dl = QVBoxLayout(self.dbg)
        dl.setContentsMargins(0, 0, 0, 0)
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("hex, напр. 69 96 05 02 00 FF 00")
        b_raw = QPushButton("Отправить")
        b_raw.clicked.connect(self.send_raw)
        rr = QHBoxLayout()
        rr.addWidget(self.raw, 1)
        rr.addWidget(b_raw)
        dl.addLayout(rr)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setFixedHeight(110)
        dl.addWidget(self.logbox)
        self.dbg.hide()
        root.addWidget(self.dbg)

        self.setFixedWidth(420)
        self.setup_tray()
        self.update_preview()

    # --- питание ---
    def power_on(self):
        self.powered_off = False
        self.update_tray()
        self.ble.run(self.ble.send([CMD_ON]))

    def power_off(self):
        self.powered_off = True
        self.update_tray()
        self.ble.run(self.ble.send([CMD_OFF]))

    def _with_on(self, packet):
        """Если ленту выключали мы, сначала включаем."""
        if self.powered_off:
            self.powered_off = False
            self.update_tray()
            return [CMD_ON, packet]
        return [packet]

    # --- цвет и яркость ---
    def scaled(self):
        k = (self.bright.value() / 100) ** GAMMA
        return tuple(round(v * k) for v in self.rgb)

    def update_preview(self):
        r, g, b = self.scaled()
        self.preview.setStyleSheet(
            f"background: rgb({r},{g},{b}); border-radius: 44px;")
        for btn, rgb in self.swatches:
            btn.setStyleSheet(self.swatch_style(rgb, tuple(rgb) == tuple(self.rgb)))
        self.update_tray()

    @staticmethod
    def swatch_style(rgb, selected):
        ring = "#ffffff" if selected else "rgba(255,255,255,0.14)"
        w = 3 if selected else 1
        return (f"QPushButton {{ background: rgb{tuple(rgb)}; border: {w}px solid {ring};"
                " border-radius: 16px; padding: 0; }"
                "QPushButton:hover { border: 2px solid rgba(255,255,255,0.7); }")

    def on_bright(self, v):
        self.bright_label.setText(f"Яркость {v}%")
        self.update_preview()
        self.debounce.start()

    def apply_color(self):
        self.ble.run(self.ble.send(self._with_on(color_packet(*self.scaled()))))

    def set_color(self, rgb):
        self.rgb = tuple(rgb)
        self.update_preview()
        self.apply_color()

    def pick_color(self):
        c = QColorDialog.getColor(QColor(*self.rgb), self, "Выберите цвет")
        if c.isValid():
            self.set_color((c.red(), c.green(), c.blue()))

    # --- эффекты ---
    def step_mode(self, d):
        self.mode = (self.mode + d) % (MAX_MODE + 1)
        self.send_mode()

    def send_mode(self):
        self.mode_label.setText(f"Режим {self.mode}")
        self.ble.run(self.ble.send(self._with_on(mode_packet(self.mode, self.param.value()))))

    # --- таймер ---
    def toggle_timer(self):
        if self.tick.isActive():
            self.tick.stop()
            self.timer_label.setText("Таймер отменён")
            self.btn_timer.setText("Запустить")
        else:
            self.sleep_left = self.minutes.value() * 60
            self.tick.start()
            self.btn_timer.setText("Отменить")
            self.show_left()

    def show_left(self):
        m, s = divmod(self.sleep_left, 60)
        h, m = divmod(m, 60)
        self.timer_label.setText(f"Выключится через {h}:{m:02d}:{s:02d}")

    def on_tick(self):
        self.sleep_left -= 1
        if self.sleep_left <= 0:
            self.tick.stop()
            self.btn_timer.setText("Запустить")
            self.timer_label.setText("Лента выключена по таймеру")
            self.power_off()
        else:
            self.show_left()

    # --- иконка в строке меню ---
    def setup_tray(self):
        self.tray = QSystemTrayIcon(dot_icon(self.rgb), self)
        self.tray.setToolTip("VY Glow")
        menu = QMenu()
        menu.addAction("Открыть VY Glow").triggered.connect(lambda _=False: self.show_window())
        menu.addSeparator()
        menu.addAction("Включить").triggered.connect(lambda _=False: self.power_on())
        menu.addAction("Выключить").triggered.connect(lambda _=False: self.power_off())
        menu.addSeparator()
        for name, rgb in PRESETS:
            act = menu.addAction(dot_icon(rgb), name)
            act.triggered.connect(lambda _=False, c=rgb: self.set_color(c))
        menu.addSeparator()
        menu.addAction("Выйти").triggered.connect(lambda _=False: self.quit_app())
        self._tray_menu = menu  # держим ссылку, иначе меню удалится
        self.tray.setContextMenu(menu)
        self.tray.show()

    def update_tray(self):
        if hasattr(self, "tray"):
            self.tray.setIcon(dot_icon(self.rgb, ring=self.powered_off))

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.really_quit = True
        self.close()
        QApplication.quit()

    # --- прочее ---
    def toggle_debug(self, on):
        self.dbg.setVisible(on)
        self.dbg_btn.setText("Отладка ▾" if on else "Отладка ▸")
        self.adjustSize()

    def append_log(self, text):
        self.logbox.appendPlainText(text)

    def on_connected(self, ok):
        dot_color = "#30d158" if ok else "#8e8e93"
        self.status.setText("● подключено" if ok else "● не подключено")
        self.status.setStyleSheet(f"color: {dot_color};")
        self.btn_conn.setText("Отключить" if ok else "Подключить")

    def toggle_connection(self):
        c = self.ble.client
        if c and c.is_connected:
            self.ble.run(self.ble.disconnect())
        else:
            self.ble.run(self.ble.connect())

    def send_raw(self):
        try:
            data = bytes.fromhex(self.raw.text())
        except ValueError:
            self.append_log("Некорректный hex")
            return
        if data:
            self.ble.run(self.ble.send([data]))

    def closeEvent(self, event):
        if not self.really_quit:
            event.ignore()
            self.hide()   # окно прячется, приложение живёт в строке меню
            return
        c = self.ble.client
        if c and c.is_connected:
            fut = asyncio.run_coroutine_threadsafe(self.ble.disconnect(), self.ble.loop)
            try:
                fut.result(timeout=3)
            except Exception:
                pass
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()