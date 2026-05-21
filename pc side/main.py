import sys, csv, time, math, os, subprocess, platform, json
import numpy as np
import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QCheckBox, QGroupBox, QGridLayout,
    QSplitter, QStatusBar, QFileDialog, QAction, QMessageBox, QDialog,
    QTextBrowser, QLineEdit, QFormLayout, QDialogButtonBox,
    QRadioButton, QButtonGroup, QFrame
)
import serial, serial.tools.list_ports

# ---------- Константы ----------
LEAN_THRESHOLD_DEFAULT = 200
RICH_THRESHOLD_DEFAULT = 800
CALIBRATION_FILE = "calibration.json"

# ---------- Всплывающее уведомление ----------
class Notification(QFrame):
    def __init__(self, parent, text, file_path=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setStyleSheet(
            "background: #333; color: #eee; border: 1px solid #555; "
            "border-radius: 6px; padding: 8px; font-size: 10pt;"
        )
        layout = QVBoxLayout(self)
        self.label = QLabel(text)
        if file_path:
            self.path_label = QLabel(f"<small>{file_path}</small>")
            self.path_label.setStyleSheet("color: #aaa; font-size: 8pt;")
            layout.addWidget(self.label)
            layout.addWidget(self.path_label)
        else:
            layout.addWidget(self.label)
        self.adjustSize()
        if parent:
            p = parent.geometry().topRight()
            self.move(p.x() - self.width() - 20, p.y() + 50)
        self.show()
        QTimer.singleShot(5000, self.close)
        self.setAttribute(Qt.WA_Hover)

    def mousePressEvent(self, event):
        if self.file_path:
            self.open_file_location()
        event.accept()

    def open_file_location(self):
        try:
            if platform.system() == 'Windows':
                os.startfile(os.path.dirname(self.file_path))
            elif platform.system() == 'Darwin':
                subprocess.run(['open', '--reveal', self.file_path])
            else:
                subprocess.run(['xdg-open', os.path.dirname(self.file_path)])
        except Exception:
            pass

# ---------- Диалог калибровки (полный, как в предыдущем финальном коде) ----------
class CalibrationDialog(QDialog):
    # (код без изменений, для экономии места напомню, что он берётся из предыдущего полного ответа)
    def __init__(self, parent, sensor_name, sensor_key):
        super().__init__(parent)
        self.parent = parent
        self.sensor_name = sensor_name
        self.sensor_key = sensor_key
        self.is_mq2 = sensor_key == "mq2"
        self.setWindowTitle(f"Калибровка {sensor_name}")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)

        self.value_label = QLabel("Текущее значение: ---")
        self.state_label = QLabel("Состояние: ---")
        layout.addWidget(self.value_label)
        layout.addWidget(self.state_label)

        self.method_group = QButtonGroup(self)
        self.manual_radio = QRadioButton("Ручная установка порогов")
        self.air_radio = QRadioButton("Калибровка по чистому воздуху")
        if self.is_mq2:
            self.gas_radio = QRadioButton("Калибровка по углеводородам (HC)")
        else:
            self.gas_radio = QRadioButton("Калибровка по эталонному CO")
        self.manual_radio.setChecked(True)
        self.method_group.addButton(self.manual_radio)
        self.method_group.addButton(self.air_radio)
        self.method_group.addButton(self.gas_radio)
        layout.addWidget(self.manual_radio)
        layout.addWidget(self.air_radio)
        layout.addWidget(self.gas_radio)

        self.manual_widget = QWidget()
        man_layout = QFormLayout(self.manual_widget)
        self.min_edit = QLineEdit(str(LEAN_THRESHOLD_DEFAULT))
        self.max_edit = QLineEdit(str(RICH_THRESHOLD_DEFAULT))
        man_layout.addRow("Порог бедной смеси (мин.):", self.min_edit)
        man_layout.addRow("Порог богатой смеси (макс.):", self.max_edit)
        man_layout.addRow(QLabel("<i>Вводите скорректированные значения (см. главную панель)</i>"))
        layout.addWidget(self.manual_widget)

        self.air_widget = QWidget()
        air_layout = QFormLayout(self.air_widget)
        self.air_adc_edit = QLineEdit()
        get_adc_btn = QPushButton("Взять текущее показание")
        get_adc_btn.clicked.connect(self.capture_current_adc)
        air_layout.addRow("АЦП на чистом воздухе:", self.air_adc_edit)
        air_layout.addRow("", get_adc_btn)
        self.sens_edit = QLineEdit("200")
        air_layout.addRow("Чувствительность (изменение АЦП на 1% газа):", self.sens_edit)
        self.air_widget.setVisible(False)
        layout.addWidget(self.air_widget)

        self.gas_widget = QWidget()
        gas_layout = QFormLayout(self.gas_widget)
        if self.is_mq2:
            gas_layout.addRow(QLabel("<b>Используйте баллон с пропаном/бутаном (зажигалку) как источник HC</b>"))
            self.adc_edit = QLineEdit()
            self.conc_edit = QLineEdit()
            gas_layout.addRow("АЦП при контакте с газом:", self.adc_edit)
            gas_layout.addRow("Примерная концентрация HC в % (например, 2%):", self.conc_edit)
        else:
            gas_layout.addRow(QLabel("<b>Используйте баллон с известной концентрацией CO</b>"))
            self.adc_edit = QLineEdit()
            self.conc_edit = QLineEdit()
            gas_layout.addRow("Значение АЦП при известном CO:", self.adc_edit)
            gas_layout.addRow("Концентрация CO (%):", self.conc_edit)
        self.gas_widget.setVisible(False)
        layout.addWidget(self.gas_widget)

        self.method_group.buttonClicked.connect(self.toggle_cal_method)

        self.instr_btn = QPushButton("Показать инструкцию")
        self.instr_btn.clicked.connect(self.show_calibration_help)
        layout.addWidget(self.instr_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_values)
        self.timer.start(200)

    def capture_current_adc(self):
        if hasattr(self.parent, 'current_values') and self.sensor_key in self.parent.current_values:
            val = self.parent.current_values[self.sensor_key]
            self.air_adc_edit.setText(str(val))

    def toggle_cal_method(self, btn):
        self.manual_widget.setVisible(btn == self.manual_radio)
        self.air_widget.setVisible(btn == self.air_radio)
        self.gas_widget.setVisible(btn == self.gas_radio)

    def update_values(self):
        if hasattr(self.parent, 'current_values') and self.sensor_key in self.parent.current_values:
            val = self.parent.current_values[self.sensor_key]
            self.value_label.setText(f"Текущее значение: {val}")
            if 'mq7' in self.sensor_key:
                idx = '1' if '1' in self.sensor_key else '2'
                state_label = getattr(self.parent, f'label_state{idx}', None)
                if state_label:
                    self.state_label.setText(f"Состояние: {state_label.text()}")
                else:
                    self.state_label.setText("Состояние: ---")
            else:
                self.state_label.setText("Состояние: постоянно включён")
        else:
            self.value_label.setText("Текущее значение: ---")
            self.state_label.setText("Состояние: ---")

    def save_and_accept(self):
        if self.manual_radio.isChecked():
            try:
                min_val = float(self.min_edit.text())
                max_val = float(self.max_edit.text())
                if min_val >= max_val:
                    QMessageBox.warning(self, "Ошибка", "Мин. порог должен быть меньше макс.")
                    return
                self.parent.calibrations[self.sensor_key] = (min_val, max_val)
                self.parent.save_calibrations_to_file()
                self.accept()
            except ValueError:
                QMessageBox.warning(self, "Ошибка", "Введите числовые значения.")
        elif self.air_radio.isChecked():
            try:
                air_adc = float(self.air_adc_edit.text())
                sens = float(self.sens_edit.text())
                if sens <= 0:
                    QMessageBox.warning(self, "Ошибка", "Чувствительность должна быть положительной.")
                    return
                lean_adc = air_adc + sens * 1.0
                rich_adc = air_adc + sens * 4.0
                if lean_adc >= rich_adc:
                    QMessageBox.warning(self, "Ошибка", "Пороги инвертированы (проверьте чувствительность).")
                    return
                self.parent.calibrations[self.sensor_key] = (lean_adc, rich_adc)
                self.parent.save_calibrations_to_file()
                self.accept()
            except ValueError:
                QMessageBox.warning(self, "Ошибка", "Введите числовые значения.")
        elif self.gas_radio.isChecked():
            try:
                adc = float(self.adc_edit.text())
                conc = float(self.conc_edit.text())
                if conc == 0:
                    QMessageBox.warning(self, "Ошибка", "Концентрация не должна быть нулевой.")
                    return
                adc_air = 50 if not self.is_mq2 else 100
                k = (adc - adc_air) / conc
                lean_adc = adc_air + k * 1.0
                rich_adc = adc_air + k * 4.0
                if lean_adc >= rich_adc:
                    QMessageBox.warning(self, "Ошибка", "Получены некорректные пороги (проверьте данные).")
                    return
                self.parent.calibrations[self.sensor_key] = (lean_adc, rich_adc)
                self.parent.save_calibrations_to_file()
                self.accept()
            except ValueError:
                QMessageBox.warning(self, "Ошибка", "Введите числовые значения.")

    def show_calibration_help(self):
        if self.is_mq2:
            text = """<h2>Калибровка MQ‑2 (углеводороды)</h2>..."""  # полный текст как раньше
        else:
            text = """<h2>Калибровка MQ‑7 (CO)</h2>..."""
        QMessageBox.information(self, "Инструкция по калибровке", text)


# ---------- Главное окно ----------
class SensorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Газоанализатор смеси")
        self.setGeometry(100, 100, 1400, 850)

        self.serial_port = None
        self.port_name = ""
        self.is_frozen = False
        self.is_recording = False
        self.recorded_data = []
        self.current_values = {"mq2": 0, "mq7_1": 0, "mq7_2": 0, "rpm": 0,
                               "temp": float('nan'), "hum": float('nan'), "press": float('nan')}
        self.graph_curves = {}
        self.demo_mode = False
        self.demo_time = 0.0
        self.mode_realtime = True
        self.playback_data = {"timestamps": [], "mq2": [], "mq7_1": [], "mq7_2": [],
                              "rpm": [], "temp": [], "hum": [], "press": []}
        self.playback_manual_select = False
        self.start_time = None

        self.calibrations = {
            "mq2": (LEAN_THRESHOLD_DEFAULT, RICH_THRESHOLD_DEFAULT),
            "mq7_1": (LEAN_THRESHOLD_DEFAULT, RICH_THRESHOLD_DEFAULT),
            "mq7_2": (LEAN_THRESHOLD_DEFAULT, RICH_THRESHOLD_DEFAULT)
        }
        self.load_calibrations_from_file()

        self.apply_style()
        self.init_ui()
        self.setup_status_indicators()

        self.timer = QTimer()
        self.timer.timeout.connect(self.data_poll)
        self.timer.start(50)

    # ---------- Стили ----------
    def apply_style(self):
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #dddddd; font-family: "Segoe UI"; font-size: 10pt; }
            QGroupBox { font-weight: bold; border: 1px solid #555; border-radius: 5px; margin-top: 1ex; padding-top: 10px; color: #ddd; background-color: #2b2b2b; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; color: #eee; }
            QPushButton { background-color: #3c3c3c; border: 1px solid #555; border-radius: 4px; padding: 4px 12px; color: white; }
            QPushButton:hover { background-color: #505050; }
            QPushButton:pressed { background-color: #2a2a2a; }
            QPushButton#record_active { background-color: #aa3333; border-color: #ff5555; }
            QLabel { color: #ddd; background-color: transparent; }
            QSlider::groove:horizontal { border: 1px solid #999; height: 8px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 blue, stop:0.5 green, stop:1 red); border-radius: 4px; }
            QSlider::handle:horizontal { background: #ccc; border: 1px solid #555; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; }
            QSlider::sub-page:horizontal { background: transparent; }
            QCheckBox { color: #ddd; }
            QStatusBar { background: #212121; color: #aaa; }
            QSplitter::handle { background: #555; width: 2px; }
        """)

    def setup_status_indicators(self):
        self.status_indicators = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(8)

        self.recording_indicator = QLabel("● запись")
        self.recording_indicator.setToolTip("Идёт запись")
        self.recording_indicator.setStyleSheet("color: red; font-weight: bold;")
        self.recording_indicator.hide()
        layout.addWidget(self.recording_indicator)

        self.connection_indicator = QLabel("● соединение")
        self.connection_indicator.setToolTip("Статус подключения")
        self.connection_indicator.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(self.connection_indicator)

        self.demo_indicator = QLabel("● демо")
        self.demo_indicator.setToolTip("Демо‑режим")
        self.demo_indicator.setStyleSheet("color: orange; font-weight: bold;")
        self.demo_indicator.hide()
        layout.addWidget(self.demo_indicator)

        self.mode_indicator = QLabel("RT")
        self.mode_indicator.setToolTip("RT – реальное время, PB – просмотр, WARM – прогрев")
        self.mode_indicator.setStyleSheet("color: #00ccff; font-weight: bold;")
        layout.addWidget(self.mode_indicator)

        # Индикатор прогрева
        self.warmup_indicator = QLabel("⏳ прогрев")
        self.warmup_indicator.setToolTip("Идёт прогрев датчиков")
        self.warmup_indicator.setStyleSheet("color: #ffaa00; font-weight: bold;")
        self.warmup_indicator.hide()
        layout.addWidget(self.warmup_indicator)

        self.status_indicators.setLayout(layout)
        self.statusBar().addPermanentWidget(self.status_indicators)

    def init_ui(self):
        menubar = self.menuBar()
        mode_menu = menubar.addMenu("Режим")
        self.action_realtime = QAction("Режим реального времени", self, checkable=True)
        self.action_realtime.setChecked(True)
        self.action_realtime.triggered.connect(self.toggle_view_mode)
        mode_menu.addAction(self.action_realtime)
        self.action_playback = QAction("Режим просмотра", self, checkable=True)
        self.action_playback.triggered.connect(self.toggle_view_mode)
        mode_menu.addAction(self.action_playback)
        demo_action = QAction("Демо‑режим", self, checkable=True)
        demo_action.triggered.connect(self.toggle_demo_mode)
        mode_menu.addAction(demo_action)

        conn_menu = menubar.addMenu("Подключение")
        refresh_action = QAction("Обновить список портов", self)
        refresh_action.triggered.connect(self.refresh_ports)
        conn_menu.addAction(refresh_action)
        self.port_actions = []
        conn_menu.addSeparator()
        self.conn_menu = conn_menu

        cal_menu = menubar.addMenu("Калибровка")
        for name, key in [("MQ-2", "mq2"), ("MQ-7 №1", "mq7_1"), ("MQ-7 №2", "mq7_2")]:
            action = QAction(f"Калибровка {name}", self)
            action.triggered.connect(lambda checked, k=key, n=name: self.open_calibration_dialog(n, k))
            cal_menu.addAction(action)

        help_menu = menubar.addMenu("Помощь")
        help_menu.addAction("Расчёт оборотов", self.show_rpm_instructions)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)

        self.dashboard_widget = QWidget()
        self.setup_dashboard_panel()
        splitter.addWidget(self.dashboard_widget)

        self.graph_widget = QWidget()
        self.setup_graph_panel()
        splitter.addWidget(self.graph_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Выберите порт в меню «Подключение»")
        self.refresh_ports()

    def setup_dashboard_panel(self):
        layout = QVBoxLayout(self.dashboard_widget)
        values_group = QGroupBox("Текущие значения")
        v_layout = QGridLayout(values_group)
        self.labels = {}
        sensors = [("mq2", "MQ-2"), ("mq7_1", "MQ-7 №1"), ("mq7_2", "MQ-7 №2"),
                   ("rpm", "Обороты"), ("temp", "Температура (°C)"),
                   ("hum", "Влажность (%)"), ("press", "Давление (hPa)")]
        for i, (k, n) in enumerate(sensors):
            v_layout.addWidget(QLabel(f"{n}:"), i, 0)
            self.labels[k] = QLabel("0")
            v_layout.addWidget(self.labels[k], i, 1)
        v_layout.addWidget(QLabel("Статус MQ-7 №1:"), 7, 0)
        self.label_state1 = QLabel("–")
        v_layout.addWidget(self.label_state1, 7, 1)
        v_layout.addWidget(QLabel("Статус MQ-7 №2:"), 8, 0)
        self.label_state2 = QLabel("–")
        v_layout.addWidget(self.label_state2, 8, 1)
        layout.addWidget(values_group)

        mix_group = QGroupBox("Качество смеси")
        mix_layout = QVBoxLayout(mix_group)
        self.mix_label = QLabel("Ожидание данных...")
        mix_layout.addWidget(self.mix_label)
        self.mix_slider = QSlider(Qt.Horizontal)
        self.mix_slider.setRange(0, 100)
        self.mix_slider.setEnabled(False)
        mix_layout.addWidget(self.mix_slider)
        mix_labels = QHBoxLayout()
        mix_labels.addWidget(QLabel("Богатая"))
        mix_labels.addWidget(QLabel("Норма"))
        mix_labels.addWidget(QLabel("Бедная"))
        mix_labels.setAlignment(Qt.AlignCenter)
        mix_layout.addLayout(mix_labels)
        layout.addWidget(mix_group)

        ctrl = QGroupBox("Управление")
        cl = QVBoxLayout(ctrl)
        self.freeze_btn = QPushButton("Заморозить")
        self.freeze_btn.clicked.connect(self.toggle_freeze)
        cl.addWidget(self.freeze_btn)
        self.record_btn = QPushButton("Начать запись (на диск)")
        self.record_btn.clicked.connect(self.toggle_recording)
        cl.addWidget(self.record_btn)
        self.save_btn = QPushButton("Сохранить записанное")
        self.save_btn.clicked.connect(self.save_to_file)
        cl.addWidget(self.save_btn)
        self.load_btn = QPushButton("Загрузить из файла")
        self.load_btn.clicked.connect(self.load_from_file)
        cl.addWidget(self.load_btn)
        self.download_btn = QPushButton("Скачать данные с Arduino")
        self.download_btn.clicked.connect(self.download_data)
        cl.addWidget(self.download_btn)
        self.clear_graph_btn = QPushButton("Стереть график")
        self.clear_graph_btn.clicked.connect(self.clear_graph)
        cl.addWidget(self.clear_graph_btn)
        layout.addWidget(ctrl)

    def setup_graph_panel(self):
        layout = QVBoxLayout(self.graph_widget)
        ctr_layout = QHBoxLayout()
        ctr_layout.addWidget(QLabel("Показать:"))
        self.graph_checkboxes = {}
        graph_items = [("mq2","MQ-2"), ("mq7_1","MQ-7 №1"), ("mq7_2","MQ-7 №2"),
                       ("rpm","Обороты"), ("mix","Качество смеси"),
                       ("temp","Температура"), ("hum","Влажность"), ("press","Давление")]
        for k, n in graph_items:
            cb = QCheckBox(n)
            cb.setChecked(True)
            cb.stateChanged.connect(self.update_graph_visibility)
            self.graph_checkboxes[k] = cb
            ctr_layout.addWidget(cb)
        ctr_layout.addStretch()
        layout.addLayout(ctr_layout)

        btn_layout = QHBoxLayout()
        save_png_btn = QPushButton("Сохранить график (PNG)")
        save_png_btn.clicked.connect(self.save_graph_as_image)
        btn_layout.addWidget(save_png_btn)
        save_csv_btn = QPushButton("Сохранить данные графика (CSV)")
        save_csv_btn.clicked.connect(self.save_graph_data_csv)
        btn_layout.addWidget(save_csv_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.graph_view = pg.GraphicsLayoutWidget()
        layout.addWidget(self.graph_view)
        self.plot = self.graph_view.addPlot(title="Данные")
        self.plot.setLabel('bottom', 'Время', units='с')
        self.plot.setLabel('left', 'Значения')
        self.plot.addLegend()
        self.plot.showGrid(x=True, y=True, alpha=0.3)

        colors = {'mq2':'r','mq7_1':'g','mq7_2':'b','rpm':'y','mix':'w',
                  'temp':'#ff7f0e','hum':'#2ca02c','press':'#9467bd'}
        for k, n in graph_items:
            curve = self.plot.plot(pen=colors[k], name=n)
            curve.setData([], [])
            self.graph_curves[k] = curve

        self.plot.scene().sigMouseClicked.connect(self.graph_clicked)

    # ---------- Сохранение/загрузка калибровок ----------
    def load_calibrations_from_file(self):
        try:
            with open(CALIBRATION_FILE, 'r') as f:
                data = json.load(f)
                for key in self.calibrations:
                    if key in data:
                        self.calibrations[key] = tuple(data[key])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_calibrations_to_file(self):
        with open(CALIBRATION_FILE, 'w') as f:
            json.dump(self.calibrations, f)

    def show_notification(self, message, file_path=None):
        notif = Notification(self, message, file_path)
        if not hasattr(self, '_notifications'):
            self._notifications = []
        self._notifications.append(notif)

    # ---------- Подключение ----------
    def refresh_ports(self):
        for action in self.port_actions:
            self.conn_menu.removeAction(action)
        self.port_actions.clear()
        ports = serial.tools.list_ports.comports()
        if not ports:
            action = QAction("Нет доступных портов", self)
            action.setEnabled(False)
            self.conn_menu.addAction(action)
            self.port_actions.append(action)
        else:
            for p in ports:
                action = QAction(f"{p.device} - {p.description}", self)
                action.triggered.connect(lambda checked, port=p.device: self.connect_to_port(port))
                self.conn_menu.addAction(action)
                self.port_actions.append(action)

    def connect_to_port(self, port_name):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        try:
            self.serial_port = serial.Serial(port_name, 115200, timeout=1, dsrdtr=False)
            self.port_name = port_name
            self.start_time = time.time()
            self.demo_mode = False
            self.demo_indicator.hide()
            self.status_bar.showMessage(f"Подключено к {port_name}")
            self.update_connection_indicator(True)
            self.warmup_indicator.hide()
            self.mode_indicator.setText("RT")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть порт {port_name}:\n{e}")
            self.update_connection_indicator(False)

    def update_connection_indicator(self, connected):
        color = "green" if connected else "red"
        self.connection_indicator.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.connection_indicator.setText("● соединение" if connected else "● нет соед.")

    # ---------- Режимы ----------
    def toggle_view_mode(self):
        if self.sender() == self.action_realtime:
            self.mode_realtime = True
            self.action_realtime.setChecked(True)
            self.action_playback.setChecked(False)
            self.mode_indicator.setText("RT")
            self.status_bar.showMessage("Режим реального времени")
            self.playback_manual_select = False
        else:
            self.mode_realtime = False
            self.action_realtime.setChecked(False)
            self.action_playback.setChecked(True)
            self.mode_indicator.setText("PB")
            self.status_bar.showMessage("Режим просмотра данных")
            if self.playback_data["timestamps"]:
                t_min = self.playback_data["timestamps"][0]
                self.plot.setXRange(t_min, t_min+60, padding=0)

    def toggle_demo_mode(self, checked):
        if self.serial_port and self.serial_port.is_open:
            QMessageBox.information(self, "Демо", "Отключите Arduino для демо‑режима.")
            return
        self.demo_mode = checked
        if self.demo_mode:
            self.demo_indicator.show()
            self.demo_time = 0.0
            self.start_time = None
            self.status_bar.showMessage("Демо‑режим активирован")
        else:
            self.demo_indicator.hide()
            self.status_bar.showMessage("Демо‑режим выключен")

    # ---------- Коррекция ----------
    def correct_mq(self, raw_val, sensor_type, temp, hum):
        if math.isnan(temp) or math.isnan(hum):
            return raw_val
        T_ref = 20.0
        H_ref = 65.0
        if sensor_type == 'mq7':
            k_temp = 1.0 + 0.005 * (temp - T_ref)
            k_hum = 1.0 + 0.01 * (hum - H_ref)
        else:
            k_temp = 1.0 + 0.006 * (temp - T_ref)
            k_hum = 1.0 + 0.008 * (hum - H_ref)
        return raw_val / (k_temp * k_hum)

    # ---------- Опрос данных ----------
    def data_poll(self):
        if self.demo_mode:
            self.generate_demo_data()
        elif self.serial_port and self.serial_port.is_open:
            self.read_serial_data()
        if not self.mode_realtime and self.playback_data["timestamps"] and not self.playback_manual_select:
            self.update_playback_dashboard()

    def generate_demo_data(self):
        self.demo_time += 0.05
        t = self.demo_time
        mq2_raw = int(500 + 200 * math.sin(t * 0.5))
        mq7_1_raw = int(600 + 150 * math.sin(t * 0.7 + 1))
        mq7_2_raw = int(580 + 150 * math.cos(t * 0.7))
        rpm = 2000 + 500 * math.sin(t * 0.3)
        temp = 25 + 5 * math.sin(t * 0.1)
        hum = 50 + 10 * math.sin(t * 0.2)
        press = 1013 + 2 * math.sin(t * 0.05)

        mq2 = self.correct_mq(mq2_raw, 'mq2', temp, hum)
        mq7_1 = self.correct_mq(mq7_1_raw, 'mq7', temp, hum)
        mq7_2 = self.correct_mq(mq7_2_raw, 'mq7', temp, hum)

        cycle = (t % 8.0) / 8.0
        if cycle < 0.5: s1, s2 = 'C', 'M'
        elif cycle < 0.5625: s1, s2 = 'O', 'M'
        else: s1, s2 = 'M', 'C'
        self.current_values = {"mq2": mq2, "mq7_1": mq7_1, "mq7_2": mq7_2, "rpm": rpm,
                               "temp": temp, "hum": hum, "press": press}
        self.update_dashboard(mq2, mq7_1, mq7_2, rpm, temp, hum, press)
        self.update_graphs(t, mq2, mq7_1, mq7_2, rpm, temp, hum, press)
        self.label_state1.setText("Очистка" if s1 == 'C' else ("Остывание" if s1 == 'O' else "Измерение"))
        self.label_state2.setText("Очистка" if s2 == 'C' else ("Остывание" if s2 == 'O' else "Измерение"))
        if self.is_recording:
            self.recorded_data.append({"timestamp": t, "mq2": mq2, "mq7_1": mq7_1,
                                       "mq7_2": mq7_2, "rpm": rpm,
                                       "temp": temp, "hum": hum, "press": press})

    def read_serial_data(self):
        try:
            while self.serial_port.in_waiting:
                line = self.serial_port.readline().decode(errors='ignore').strip()
                if not line:
                    continue

                # --- Обработка статуса прогрева ---
                if line.startswith("WARMUP "):
                    try:
                        remaining = int(line.split()[1])
                        self.status_bar.showMessage(f"Прогрев датчиков: осталось ~{remaining} сек")
                        self.warmup_indicator.show()
                        self.mode_indicator.setText("WARM")
                    except (IndexError, ValueError):
                        pass
                    continue

                parts = line.split(',')
                if len(parts) >= 9:
                    mq2_raw = int(parts[0]); mq7_1_raw = int(parts[1]); mq7_2_raw = int(parts[2])
                    rpm = float(parts[3]); state1 = parts[4]; state2 = parts[5]
                    temp = float(parts[6]) if parts[6] != "nan" else float('nan')
                    hum = float(parts[7]) if parts[7] != "nan" else float('nan')
                    press = float(parts[8]) if parts[8] != "nan" else float('nan')

                    mq2 = self.correct_mq(mq2_raw, 'mq2', temp, hum)
                    mq7_1 = self.correct_mq(mq7_1_raw, 'mq7', temp, hum)
                    mq7_2 = self.correct_mq(mq7_2_raw, 'mq7', temp, hum)

                    now = time.time()
                    if self.start_time is None:
                        self.start_time = now
                    rel_time = now - self.start_time
                    self.current_values = {"mq2": mq2, "mq7_1": mq7_1, "mq7_2": mq7_2, "rpm": rpm,
                                           "temp": temp, "hum": hum, "press": press}
                    QTimer.singleShot(0, lambda: self.update_dashboard(mq2, mq7_1, mq7_2, rpm, temp, hum, press))
                    QTimer.singleShot(0, lambda: self.update_graphs(rel_time, mq2, mq7_1, mq7_2, rpm, temp, hum, press))
                    state_map = {'M':'Измерение', 'O':'Остывание', 'C':'Очистка'}
                    self.label_state1.setText(state_map.get(state1, '–'))
                    self.label_state2.setText(state_map.get(state2, '–'))

                    # Прячем индикатор прогрева и возвращаем RT
                    self.warmup_indicator.hide()
                    if self.mode_realtime:
                        self.mode_indicator.setText("RT")
                    else:
                        self.mode_indicator.setText("PB")

                    if self.is_recording:
                        self.recorded_data.append({"timestamp": rel_time, "mq2": mq2, "mq7_1": mq7_1,
                                                   "mq7_2": mq7_2, "rpm": rpm,
                                                   "temp": temp, "hum": hum, "press": press})
        except (ValueError, IndexError):
            pass

    def update_dashboard(self, mq2, mq7_1, mq7_2, rpm, temp, hum, press):
        if not self.is_frozen:
            self.labels["mq2"].setText(f"{mq2:.0f}")
            self.labels["mq7_1"].setText(f"{mq7_1:.0f}")
            self.labels["mq7_2"].setText(f"{mq7_2:.0f}")
            self.labels["rpm"].setText(f"{rpm:.1f}")
            self.labels["temp"].setText(f"{temp:.1f}" if not math.isnan(temp) else "—")
            self.labels["hum"].setText(f"{hum:.1f}" if not math.isnan(hum) else "—")
            self.labels["press"].setText(f"{press:.1f}" if not math.isnan(press) else "—")
            self.update_mixture_quality(mq7_1, mq7_2)

    def update_mixture_quality(self, mq7_1, mq7_2):
        avg = (mq7_1 + mq7_2) / 2
        cal = self.calibrations.get("mq7_1", (LEAN_THRESHOLD_DEFAULT, RICH_THRESHOLD_DEFAULT))
        low, high = cal
        slider_val = np.interp(avg, [low, high], [0, 100])
        slider_val = np.clip(slider_val, 0, 100)
        self.mix_slider.setValue(int(slider_val))
        self.mix_label.setText(f"Качество смеси: {avg:.1f} (ползунок {slider_val:.1f}%)")

    def update_graphs(self, rel_time, mq2, mq7_1, mq7_2, rpm, temp, hum, press):
        if self.is_frozen or not self.mode_realtime:
            return
        data_map = {"mq2": mq2, "mq7_1": mq7_1, "mq7_2": mq7_2, "rpm": rpm,
                    "temp": temp, "hum": hum, "press": press,
                    "mix": (mq7_1 + mq7_2) / 2}
        for key, val in data_map.items():
            if key in self.graph_curves:
                curve = self.graph_curves[key]
                x, y = curve.getData()
                if x is None: x, y = np.array([]), np.array([])
                x = np.append(x, rel_time)
                y = np.append(y, val)
                mask = x > (rel_time - 60)
                curve.setData(x[mask], y[mask])
        self.plot.setXRange(max(0, rel_time-60), max(60, rel_time), padding=0)

    def update_graph_visibility(self):
        for k, curve in self.graph_curves.items():
            if k in self.graph_checkboxes:
                curve.setVisible(self.graph_checkboxes[k].isChecked())

    # ---------- Сброс графика ----------
    def clear_graph(self):
        for curve in self.graph_curves.values():
            curve.setData([], [])
        self.start_time = time.time() if not self.demo_mode else None
        self.demo_time = 0.0
        self.recorded_data.clear()
        self.status_bar.showMessage("График очищен, отсчёт начат заново")

    # ---------- Режим просмотра ----------
    def load_playback_data(self, timestamps, mq2, mq7_1, mq7_2, rpm, temp, hum, press):
        if timestamps and timestamps[0] != 0:
            base = timestamps[0]
            timestamps = [t - base for t in timestamps]
        self.playback_data = {"timestamps": timestamps, "mq2": mq2, "mq7_1": mq7_1,
                              "mq7_2": mq7_2, "rpm": rpm, "temp": temp, "hum": hum, "press": press}
        for key, vals in [("mq2", mq2), ("mq7_1", mq7_1), ("mq7_2", mq7_2),
                          ("rpm", rpm), ("temp", temp), ("hum", hum), ("press", press),
                          ("mix", (np.array(mq7_1)+np.array(mq7_2))/2)]:
            if key in self.graph_curves:
                self.graph_curves[key].setData(timestamps, vals)
        if self.mode_realtime:
            self.toggle_view_mode()
        if timestamps:
            t_min = timestamps[0]
            self.plot.setXRange(t_min, t_min+60, padding=0)
            self.update_dashboard(mq2[0], mq7_1[0], mq7_2[0], rpm[0],
                                  temp[0] if temp else float('nan'),
                                  hum[0] if hum else float('nan'),
                                  press[0] if press else float('nan'))
            self.playback_manual_select = False

    def update_playback_dashboard(self):
        x_range = self.plot.viewRange()[0]
        center = (x_range[0] + x_range[1]) / 2
        times = self.playback_data["timestamps"]
        if not times: return
        idx = (np.abs(np.array(times) - center)).argmin()
        self.update_dashboard(self.playback_data["mq2"][idx],
                              self.playback_data["mq7_1"][idx],
                              self.playback_data["mq7_2"][idx],
                              self.playback_data["rpm"][idx],
                              self.playback_data["temp"][idx],
                              self.playback_data["hum"][idx],
                              self.playback_data["press"][idx])

    def graph_clicked(self, event):
        if not self.mode_realtime and self.playback_data["timestamps"]:
            pos = event.scenePos()
            mouse_point = self.plot.vb.mapSceneToView(pos)
            click_time = mouse_point.x()
            times = self.playback_data["timestamps"]
            if not times: return
            idx = (np.abs(np.array(times) - click_time)).argmin()
            self.update_dashboard(self.playback_data["mq2"][idx],
                                  self.playback_data["mq7_1"][idx],
                                  self.playback_data["mq7_2"][idx],
                                  self.playback_data["rpm"][idx],
                                  self.playback_data["temp"][idx],
                                  self.playback_data["hum"][idx],
                                  self.playback_data["press"][idx])
            self.playback_manual_select = True

    # ---------- Скачивание с SD ----------
    def download_data(self):
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "Ошибка", "Нет подключения к Arduino.")
            return
        self.status_bar.showMessage("Скачивание данных...")
        self.serial_port.write(b'DOWNLOAD\n')
        lines = []
        in_data = False
        try:
            while True:
                line = self.serial_port.readline().decode(errors='ignore').rstrip()
                if line == "DATA_START":
                    in_data = True
                    continue
                if line == "DATA_END":
                    break
                if in_data:
                    lines.append(line)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки: {e}")
            return

        timestamps, mq2, mq7_1, mq7_2, rpm, temp, hum, press = [], [], [], [], [], [], [], []
        header_found = False
        for i, line in enumerate(lines):
            parts = line.split(',')
            if not header_found and parts[0] == "Mq2":
                header_found = True
                continue
            if len(parts) >= 7:
                try:
                    timestamps.append(i * 0.05)   # относительное время
                    mq2.append(int(parts[0])); mq7_1.append(int(parts[1])); mq7_2.append(int(parts[2]))
                    rpm.append(float(parts[3]))
                    temp.append(float(parts[4]) if parts[4] != "nan" else float('nan'))
                    hum.append(float(parts[5]) if parts[5] != "nan" else float('nan'))
                    press.append(float(parts[6]) if parts[6] != "nan" else float('nan'))
                except (ValueError, IndexError):
                    continue
        if not timestamps:
            QMessageBox.information(self, "Инфо", "Нет данных для отображения.")
            return
        self.load_playback_data(timestamps, mq2, mq7_1, mq7_2, rpm, temp, hum, press)
        QMessageBox.information(self, "Готово", f"Загружено {len(timestamps)} записей.")
        self.status_bar.showMessage("Данные загружены")

    # ---------- Кнопки ----------
    def toggle_freeze(self):
        self.is_frozen = not self.is_frozen
        self.freeze_btn.setText("Разморозить" if self.is_frozen else "Заморозить")

    def toggle_recording(self):
        self.is_recording = not self.is_recording
        if self.is_recording:
            self.record_btn.setText("Остановить запись")
            self.record_btn.setObjectName("record_active")
            self.record_btn.style().unpolish(self.record_btn)
            self.record_btn.style().polish(self.record_btn)
            self.recording_indicator.show()
            self.recorded_data.clear()
        else:
            self.record_btn.setText("Начать запись (на диск)")
            self.record_btn.setObjectName("")
            self.record_btn.style().unpolish(self.record_btn)
            self.record_btn.style().polish(self.record_btn)
            self.recording_indicator.hide()

    def save_to_file(self):
        if not self.recorded_data:
            self.status_bar.showMessage("Нет записанных данных.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить", "", "CSV (*.csv)")
        if path:
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["Timestamp", "MQ2", "MQ7_1", "MQ7_2", "RPM", "Temp", "Hum", "Press"])
                for r in self.recorded_data:
                    w.writerow([r["timestamp"], r["mq2"], r["mq7_1"], r["mq7_2"],
                                r["rpm"], r["temp"], r["hum"], r["press"]])
            self.show_notification("Файл сохранён", path)

    def load_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить", "", "CSV (*.csv)")
        if not path: return
        try:
            with open(path, 'r') as f:
                reader = csv.DictReader(f)
                timestamps, mq2, mq7_1, mq7_2, rpm, temp, hum, press = [], [], [], [], [], [], [], []
                for row in reader:
                    timestamps.append(float(row["Timestamp"]))
                    mq2.append(float(row["MQ2"]))  # было int, стало float
                    mq7_1.append(float(row["MQ7_1"]))  # --//--
                    mq7_2.append(float(row["MQ7_2"]))  # --//--
                    rpm.append(float(row["RPM"]))
                    temp.append(float(row["Temp"]) if row["Temp"] != "nan" else float('nan'))
                    hum.append(float(row["Hum"]) if row["Hum"] != "nan" else float('nan'))
                    press.append(float(row["Press"]) if row["Press"] != "nan" else float('nan'))
                self.load_playback_data(timestamps, mq2, mq7_1, mq7_2, rpm, temp, hum, press)
                self.status_bar.showMessage("Файл загружен")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл: {e}")

    def save_graph_as_image(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт графика", "", "PNG (*.png)")
        if path:
            try:
                exporter = ImageExporter(self.plot)
                exporter.export(path)
                self.show_notification("График сохранён", path)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить график: {e}")

    def save_graph_data_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить данные графика", "", "CSV (*.csv)")
        if not path: return
        data = {}
        first_curve = None
        for key in ["mq2", "mq7_1", "mq7_2", "rpm", "mix", "temp", "hum", "press"]:
            if key in self.graph_curves and self.graph_curves[key].isVisible():
                x, y = self.graph_curves[key].getData()
                if x is not None and len(x) > 0:
                    if first_curve is None: first_curve = x
                    data[key] = y
        if first_curve is None:
            QMessageBox.information(self, "Инфо", "Нет данных для сохранения.")
            return
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            headers = ["Time"] + list(data.keys())
            writer.writerow(headers)
            for i in range(len(first_curve)):
                row = [first_curve[i]] + [data[k][i] for k in headers[1:]]
                writer.writerow(row)
        self.show_notification("Данные графика сохранены", path)

    def open_calibration_dialog(self, name, key):
        dlg = CalibrationDialog(self, name, key)
        dlg.exec_()

    def show_rpm_instructions(self):
        QMessageBox.information(self, "Обороты", "Формула: rpm = frequency * 60.0 (4‑тактный 1‑цилиндровый).")

    def closeEvent(self, event):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SensorApp()
    window.show()
    sys.exit(app.exec())