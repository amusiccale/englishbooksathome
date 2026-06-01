"""
We Have Early English Books at Home
UI Layer
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTableWidget, QTextEdit,
    QPushButton, QLabel, QScrollArea, QSlider,
    QLineEdit, QComboBox, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor


class MainUI(QWidget):

    def setup_ui(self):

        self.setWindowTitle("We Have Early English Books at Home")

        main_layout = QVBoxLayout()
        self.vertical_split = QSplitter(Qt.Orientation.Vertical)

        # ================= TOP PANEL =================
        top_panel = QWidget()
        top_layout = QVBoxLayout()

        header = QLabel("We Have Early English Books at Home")
        header.setStyleSheet("font-size: 24px; font-weight: bold;")
        top_layout.addWidget(header)

        # ===== TOOLBAR =====
        toolbar = QHBoxLayout()

        self.btn_csv = QPushButton("Load CSV Index")
        self.btn_xml = QPushButton("Load XML Folder")
        self.btn_rebuild = QPushButton("Rebuild Index [time intensive]")
        self.btn_search = QPushButton("Search")

        self.status_label = QLabel("●")
        self.status_label.setStyleSheet("color: red; font-size: 16px;")

        toolbar.addWidget(self.btn_csv)
        toolbar.addWidget(self.btn_xml)
        toolbar.addWidget(self.btn_rebuild)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_search)
        toolbar.addWidget(self.status_label)

        top_layout.addLayout(toolbar)

        # ===== DATE FILTER =====
        date_row = QHBoxLayout()

        self.date_min = QSlider(Qt.Orientation.Horizontal)
        self.date_max = QSlider(Qt.Orientation.Horizontal)

        self.date_min.setRange(1400, 1900)
        self.date_max.setRange(1400, 1900)

        self.date_min.setValue(1400)
        self.date_max.setValue(1900)

        self.date_label = QLabel("Date: 1400–1900")

        def update_label():
            self.date_label.setText(
                f"Date: {self.date_min.value()}–{self.date_max.value()}"
            )

        self.date_min.valueChanged.connect(update_label)
        self.date_max.valueChanged.connect(update_label)

        date_row.addWidget(self.date_min)
        date_row.addWidget(self.date_max)
        date_row.addWidget(self.date_label)

        top_layout.addLayout(date_row)

        # ===== ADVANCED SEARCH =====
        self.adv_container = QWidget()
        self.adv_layout = QVBoxLayout()
        self.adv_container.setLayout(self.adv_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.adv_container)
        scroll.setMaximumHeight(200)

        top_layout.addWidget(scroll)
        top_panel.setLayout(top_layout)

        # ================= MAIN SPLIT =================
        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        left_split = QSplitter(Qt.Orientation.Vertical)

        # ===== RESULTS TREE =====
        self.results = QTreeWidget()
        self.results.setHeaderLabels(
            ["TCP", "Author", "Date", "Title", "Publisher", "Collection", "Hits"]
        )
        self.results.setSortingEnabled(True)

        # header controls
        header = self.results.header()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)

        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_column_menu)

        # row context menu
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.row_menu)

        # ===== KWIC =====
        self.kwic = QTableWidget()
        self.kwic.setColumnCount(3)
        self.kwic.setHorizontalHeaderLabels(["Left", "Match", "Right"])

        left_split.addWidget(self.results)
        left_split.addWidget(self.kwic)

        # ===== RIGHT PANEL =====
        right_panel = QWidget()
        right_layout = QVBoxLayout()

        # ===== READING TOOLBAR (NEW) =====
        read_toolbar = QHBoxLayout()

        self.btn_font = QPushButton("Font")
        self.btn_fullscreen = QPushButton("Fullscreen")

        self.btn_left = QPushButton("⯇")
        self.btn_center = QPushButton("≡")
        self.btn_right = QPushButton("⯈")

        read_toolbar.addWidget(self.btn_font)
        read_toolbar.addWidget(self.btn_fullscreen)
        read_toolbar.addStretch()
        read_toolbar.addWidget(self.btn_left)
        read_toolbar.addWidget(self.btn_center)
        read_toolbar.addWidget(self.btn_right)

        # ===== NAV =====
        nav = QHBoxLayout()

        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.page_label = QLabel("Page 1 / 1")

        nav.addWidget(self.btn_prev)
        nav.addWidget(self.page_label)
        nav.addWidget(self.btn_next)

        # ===== PREVIEW =====
        self.preview = QTextEdit()

        right_layout.addLayout(read_toolbar)
        right_layout.addLayout(nav)
        right_layout.addWidget(self.preview)

        right_panel.setLayout(right_layout)

        self.main_split.addWidget(left_split)
        self.main_split.addWidget(right_panel)

        self.vertical_split.addWidget(top_panel)
        self.vertical_split.addWidget(self.main_split)
        self.vertical_split.setStretchFactor(1, 4)

        main_layout.addWidget(self.vertical_split)
        self.setLayout(main_layout)

    # ================= SEARCH ROW =================
    def make_search_row(self):
        row = QHBoxLayout()

        query = QLineEdit()
        query.setPlaceholderText("Search term...")

        field = QComboBox()
        field.addItems(["Full Text", "Author", "Title", "Publisher", "Collection"])

        mode = QComboBox()
        mode.addItems(["Fuzzy", "Exact", "Phrase", "Boolean"])

        op = QComboBox()
        op.addItems(["AND", "OR", "NOT"])

        row.addWidget(query)
        row.addWidget(field)
        row.addWidget(mode)
        row.addWidget(op)

        return row, (query, field, mode, op)

    # ================= COLUMN MENU =================
    def show_column_menu(self, position):
        header = self.results.header()
        menu = QMenu(self)

        for col in range(self.results.columnCount()):
            name = self.results.headerItem().text(col)

            action = menu.addAction(name)
            action.setCheckable(True)

            visible = not self.results.isColumnHidden(col)
            action.setChecked(visible)

            action.triggered.connect(
                lambda checked, c=col: self.results.setColumnHidden(c, not checked)
            )

        menu.exec(header.mapToGlobal(position))

    # ================= ROW MENU =================
    def row_menu(self, pos):
        item = self.results.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)

        if not data or data.get("type") != "doc":
            return

        menu = QMenu(self)
        action = menu.addAction("Export RIS")

        action.triggered.connect(
            lambda: self.window().export_selected(data["meta"])
        )

        menu.exec(self.results.viewport().mapToGlobal(pos))

    # ================= HIGHLIGHT =================
    def highlight_all(self, positions, length):
        cursor = self.preview.textCursor()

        cursor.select(QTextCursor.SelectionType.Document)

        clear = QTextCharFormat()
        clear.setBackground(QColor("white"))
        cursor.setCharFormat(clear)

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("yellow"))

        text_len = len(self.preview.toPlainText())

        for pos in positions:
            if pos < 0 or pos >= text_len:
                continue

            cursor.setPosition(pos)
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                length
            )
            cursor.mergeCharFormat(fmt)
