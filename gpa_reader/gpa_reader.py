"""
YouOS GPA Report Reader
Reads student GPA reports from PDF files and displays sorted results
"""

import sys
import re
import os
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Installing pdfplumber...")
    os.system(f"{sys.executable} -m pip install pdfplumber --break-system-packages")
    import pdfplumber

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QFrame, QScrollArea, QComboBox,
    QLineEdit, QMessageBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QDragEnterEvent, QDropEvent

# ── Color palette matching YouOS App Store ──────────────────────────────────
COLORS = {
    'bg_primary':    '#0f0f1e',
    'bg_secondary':  '#1a1a2e',
    'bg_tertiary':   '#252538',
    'accent_primary': '#3b82f6',
    'accent_hover':  '#60a5fa',
    'text_primary':  '#ffffff',
    'text_secondary': '#9ca3af',
    'border':        '#374151',
    'success':       '#10b981',
    'error':         '#ef4444',
    'warning':       '#f59e0b',
    'gold':          '#fbbf24',
    'silver':        '#94a3b8',
    'bronze':        '#cd7c42',
}


# ── PDF Parsing Thread ───────────────────────────────────────────────────────
class PDFParserThread(QThread):
    finished  = pyqtSignal(list, str)   # (students, raw_text)
    progress  = pyqtSignal(int)
    error     = pyqtSignal(str)

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self):
        try:
            students = []
            raw_text = ""

            with pdfplumber.open(self.pdf_path) as pdf:
                total = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    # ── Try table extraction first ──────────────────────────
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if not row:
                                continue
                            student = self._parse_row(row)
                            if student:
                                students.append(student)

                    # ── Also capture raw text for fallback ─────────────────
                    text = page.extract_text() or ""
                    raw_text += text + "\n"

                    self.progress.emit(int((i + 1) / total * 100))

            # ── Fallback: parse raw text if no table results ────────────────
            if not students:
                students = self._parse_text(raw_text)

            # ── Deduplicate by name ─────────────────────────────────────────
            seen = {}
            for s in students:
                key = s['name'].lower().strip()
                if key not in seen:
                    seen[key] = s

            students = list(seen.values())
            self.finished.emit(students, raw_text)

        except Exception as e:
            self.error.emit(str(e))

    # ── helpers ──────────────────────────────────────────────────────────────
    def _parse_row(self, row):
        """Try to detect a name + GPA pair from a table row."""
        row = [str(c).strip() if c else '' for c in row]
        name  = None
        gpa   = None

        for cell in row:
            # Try GPA: a float between 0.0 and 4.0 (or up to 100 for percentage scales)
            gpa_match = re.search(r'\b(\d{1,3}(?:\.\d{1,2})?)\b', cell)
            if gpa_match:
                val = float(gpa_match.group(1))
                if 0.0 <= val <= 4.0 or 0.0 <= val <= 100.0:
                    gpa = val
                    continue
            # Assume a cell with mostly letters is a name
            letters = sum(c.isalpha() or c in " '-." for c in cell)
            if letters > len(cell) * 0.6 and len(cell.split()) >= 1 and len(cell) > 2:
                name = cell

        if name and gpa is not None:
            return {'name': self._clean_name(name), 'gpa': gpa}
        return None

    def _parse_text(self, text: str):
        """Fallback regex parser for common GPA report formats."""
        students = []
        lines = text.splitlines()

        # Patterns:  "Name  GPA"  or  "GPA  Name"  or  "1. Name - 3.85"
        patterns = [
            # John Smith   3.85
            r'^([A-Za-z][A-Za-z\s\'\-\.]{2,40})\s+(\d{1,3}(?:\.\d{1,2})?)$',
            # 3.85   John Smith
            r'^(\d{1,3}(?:\.\d{1,2})?)\s+([A-Za-z][A-Za-z\s\'\-\.]{2,40})$',
            # 1. John Smith - 3.85
            r'^\d+[\.\)]\s+([A-Za-z][A-Za-z\s\'\-\.]{2,40})\s*[-:]\s*(\d{1,3}(?:\.\d{1,2})?)$',
            # John Smith: 3.85
            r'^([A-Za-z][A-Za-z\s\'\-\.]{2,40}):\s*(\d{1,3}(?:\.\d{1,2})?)$',
            # Name | GPA  (pipe-separated)
            r'^([A-Za-z][A-Za-z\s\'\-\.]{2,40})\s*\|\s*(\d{1,3}(?:\.\d{1,2})?)$',
        ]

        for line in lines:
            line = line.strip()
            if not line:
                continue
            for pat in patterns:
                m = re.match(pat, line)
                if m:
                    g1, g2 = m.group(1).strip(), m.group(2).strip()
                    try:
                        # Determine which group is the GPA
                        try:
                            gpa  = float(g1); name = g2
                        except ValueError:
                            gpa  = float(g2); name = g1

                        if 0.0 <= gpa <= 4.0 or 0.0 <= gpa <= 100.0:
                            students.append({'name': self._clean_name(name), 'gpa': gpa})
                            break
                    except ValueError:
                        pass

        return students

    def _clean_name(self, name: str) -> str:
        # Remove leading numbers/dots
        name = re.sub(r'^\d+[\.\)]\s*', '', name).strip()
        # Title-case
        return ' '.join(w.capitalize() for w in name.split())


# ── Rank badge colours ───────────────────────────────────────────────────────
def rank_color(rank: int) -> str:
    if rank == 1: return COLORS['gold']
    if rank == 2: return COLORS['silver']
    if rank == 3: return COLORS['bronze']
    return COLORS['text_primary']

def rank_icon(rank: int) -> str:
    if rank == 1: return '🥇'
    if rank == 2: return '🥈'
    if rank == 3: return '🥉'
    return f'#{rank}'


# ── Main Window ──────────────────────────────────────────────────────────────
class GPAReaderWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.students   = []
        self.parser     = None
        self.pdf_path   = None
        self.setWindowTitle("📊 YouOS GPA Report Reader")
        self.setMinimumSize(820, 680)
        self.setAcceptDrops(True)
        self._apply_global_style()
        self._build_ui()

    # ── Styling ──────────────────────────────────────────────────────────────
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: {COLORS['bg_primary']};
                color: {COLORS['text_primary']};
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }}
            QScrollBar:vertical {{
                background: {COLORS['bg_secondary']};
                width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border']};
                border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QTableWidget {{
                background: transparent;
                border: none;
                gridline-color: {COLORS['border']};
            }}
            QTableWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QTableWidget::item:selected {{
                background: {COLORS['accent_primary']}33;
                color: {COLORS['text_primary']};
            }}
            QHeaderView::section {{
                background: {COLORS['bg_secondary']};
                color: {COLORS['text_secondary']};
                font-weight: bold;
                font-size: 12px;
                padding: 10px 12px;
                border: none;
                border-bottom: 2px solid {COLORS['border']};
            }}
            QTableCornerButton::section {{
                background: {COLORS['bg_secondary']};
                border: none;
            }}
        """)

    # ── UI Construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_drop_zone())
        root.addWidget(self._make_stats_bar())
        root.addWidget(self._make_table(), stretch=1)
        root.addWidget(self._make_status_bar())

    def _make_header(self):
        header = QFrame()
        header.setFixedHeight(75)
        header.setStyleSheet(f"background: {COLORS['accent_primary']};")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(30, 15, 30, 15)

        title = QLabel("📊 GPA Report Reader")
        title.setStyleSheet("color: white; font-size: 22px; font-weight: bold;")
        lay.addWidget(title)

        lay.addStretch()

        subtitle = QLabel("YouOS Academic Tools")
        subtitle.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 13px;")
        lay.addWidget(subtitle)
        return header

    def _make_toolbar(self):
        bar = QFrame()
        bar.setFixedHeight(64)
        bar.setStyleSheet(f"background: {COLORS['bg_secondary']}; border-bottom: 1px solid {COLORS['border']};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 10, 20, 10)
        lay.setSpacing(12)

        # Open PDF button
        self.open_btn = QPushButton("📂  Open PDF")
        self.open_btn.setFixedHeight(40)
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setStyleSheet(self._btn_style(COLORS['accent_primary'], '#2563eb'))
        self.open_btn.clicked.connect(self._open_file_dialog)
        lay.addWidget(self.open_btn)

        # Sort label
        sort_lbl = QLabel("Sort by GPA:")
        sort_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        lay.addWidget(sort_lbl)

        # Sort dropdown
        self.sort_combo = QComboBox()
        self.sort_combo.setFixedHeight(40)
        self.sort_combo.setFixedWidth(220)
        self.sort_combo.addItems([
            "⬇  Highest → Lowest",
            "⬆  Lowest → Highest",
        ])
        self.sort_combo.setStyleSheet(f"""
            QComboBox {{
                background: {COLORS['bg_tertiary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                color: {COLORS['text_primary']};
                padding: 0 12px;
                font-size: 13px;
            }}
            QComboBox:hover {{ border-color: {COLORS['accent_primary']}; }}
            QComboBox::drop-down {{
                border: none; width: 30px;
            }}
            QComboBox QAbstractItemView {{
                background: {COLORS['bg_tertiary']};
                color: {COLORS['text_primary']};
                selection-background-color: {COLORS['accent_primary']};
                border: 1px solid {COLORS['border']};
            }}
        """)
        self.sort_combo.currentIndexChanged.connect(self._refresh_table)
        lay.addWidget(self.sort_combo)

        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍  Search student...")
        self.search_input.setFixedHeight(40)
        self.search_input.setFixedWidth(200)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_tertiary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                color: {COLORS['text_primary']};
                padding: 0 14px;
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['accent_primary']}; }}
        """)
        self.search_input.textChanged.connect(self._refresh_table)
        lay.addWidget(self.search_input)

        lay.addStretch()

        # Export button (disabled until data loaded)
        self.export_btn = QPushButton("💾  Export CSV")
        self.export_btn.setFixedHeight(40)
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet(self._btn_style(COLORS['success'], '#059669', disabled=True))
        self.export_btn.clicked.connect(self._export_csv)
        lay.addWidget(self.export_btn)

        return bar

    def _make_drop_zone(self):
        self.drop_frame = QFrame()
        self.drop_frame.setFixedHeight(130)
        self.drop_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_secondary']};
                border: 2px dashed {COLORS['border']};
                border-radius: 12px;
                margin: 16px 20px 0px 20px;
            }}
        """)
        lay = QVBoxLayout(self.drop_frame)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("📄")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 32px; border: none;")
        lay.addWidget(icon)

        lbl = QLabel("Drag & drop a GPA report PDF here, or click  📂 Open PDF  above")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; border: none;")
        lay.addWidget(lbl)

        return self.drop_frame

    def _make_stats_bar(self):
        self.stats_frame = QFrame()
        self.stats_frame.setFixedHeight(0)   # Hidden initially
        self.stats_frame.setStyleSheet(f"background: {COLORS['bg_secondary']}; border-radius: 10px; margin: 12px 20px 0 20px;")
        self.stats_layout = QHBoxLayout(self.stats_frame)
        self.stats_layout.setContentsMargins(20, 0, 20, 0)
        self.stats_layout.setSpacing(30)

        self.stat_count  = self._stat_widget("Students", "—")
        self.stat_avg    = self._stat_widget("Average GPA", "—")
        self.stat_high   = self._stat_widget("Highest GPA", "—")
        self.stat_low    = self._stat_widget("Lowest GPA", "—")

        for w in [self.stat_count, self.stat_avg, self.stat_high, self.stat_low]:
            self.stats_layout.addWidget(w)
        self.stats_layout.addStretch()

        return self.stats_frame

    def _stat_widget(self, label: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("border: none;")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(2)

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"color: {COLORS['accent_primary']}; font-size: 22px; font-weight: bold;")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)

        key_lbl = QLabel(label)
        key_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")

        lay.addWidget(val_lbl)
        lay.addWidget(key_lbl)

        # Store reference by label text so we can update
        frame.val_lbl = val_lbl
        return frame

    def _make_table(self):
        container = QFrame()
        container.setStyleSheet("margin: 12px 20px 0 20px;")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Rank", "Student Name", "GPA", "Grade"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(self.table.styleSheet() + f"""
            QTableWidget {{ alternate-background-color: {COLORS['bg_secondary']}; }}
        """)
        self.table.setRowCount(0)

        lay.addWidget(self.table)
        return container

    def _make_status_bar(self):
        bar = QFrame()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background: {COLORS['bg_secondary']}; border-top: 1px solid {COLORS['border']};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 8, 20, 8)

        self.status_lbl = QLabel("Ready — Open a PDF to begin")
        self.status_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        lay.addWidget(self.status_lbl)

        lay.addStretch()

        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setFixedHeight(18)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                background: {COLORS['bg_tertiary']};
                text-align: center;
                color: {COLORS['text_primary']};
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background: {COLORS['accent_primary']};
                border-radius: 3px;
            }}
        """)
        self.progress.hide()
        lay.addWidget(self.progress)

        return bar

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _btn_style(self, color, hover, disabled=False):
        dis = f"QPushButton:disabled {{ background: {COLORS['bg_tertiary']}; color: {COLORS['text_secondary']}; }}" if disabled else ""
        return f"""
            QPushButton {{
                background: {color};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            {dis}
        """

    def _gpa_to_letter(self, gpa: float) -> str:
        if gpa >= 3.7: return 'A+'
        if gpa >= 3.3: return 'A'
        if gpa >= 3.0: return 'A−'
        if gpa >= 2.7: return 'B+'
        if gpa >= 2.3: return 'B'
        if gpa >= 2.0: return 'B−'
        if gpa >= 1.7: return 'C+'
        if gpa >= 1.3: return 'C'
        if gpa >= 1.0: return 'C−'
        if gpa >= 0.7: return 'D+'
        if gpa >= 0.3: return 'D'
        if gpa > 0.0:  return 'D−'
        return 'F'

    def _gpa_color(self, gpa: float) -> str:
        if gpa >= 3.5: return COLORS['success']
        if gpa >= 2.5: return COLORS['warning']
        if gpa >= 1.5: return '#f97316'
        return COLORS['error']

    # ── Drag & Drop ───────────────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith('.pdf'):
                    event.acceptProposedAction()
                    self.drop_frame.setStyleSheet(self.drop_frame.styleSheet().replace(
                        COLORS['border'], COLORS['accent_primary']))
                    return

    def dragLeaveEvent(self, event):
        self.drop_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_secondary']};
                border: 2px dashed {COLORS['border']};
                border-radius: 12px;
                margin: 16px 20px 0px 20px;
            }}
        """)

    def dropEvent(self, event: QDropEvent):
        self.dragLeaveEvent(event)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pdf'):
                self._load_pdf(path)
                return

    # ── Actions ───────────────────────────────────────────────────────────────
    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open GPA Report PDF", "",
            "PDF Files (*.pdf);;All Files (*)"
        )
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path: str):
        self.pdf_path = path
        self.students = []
        self.table.setRowCount(0)
        self.status_lbl.setText(f"Parsing: {Path(path).name} …")
        self.progress.setValue(0)
        self.progress.show()
        self.open_btn.setEnabled(False)
        self.drop_frame.setFixedHeight(0)   # Hide drop zone when loading

        self.parser = PDFParserThread(path)
        self.parser.progress.connect(self.progress.setValue)
        self.parser.finished.connect(self._on_parse_done)
        self.parser.error.connect(self._on_parse_error)
        self.parser.start()

    def _on_parse_done(self, students: list, raw_text: str):
        self.progress.hide()
        self.open_btn.setEnabled(True)

        if not students:
            self.status_lbl.setText("⚠  No student/GPA data found. Is this a valid GPA report?")
            self.drop_frame.setFixedHeight(130)
            QMessageBox.warning(self, "No Data Found",
                "Could not extract student GPA data from this PDF.\n\n"
                "Make sure the PDF contains a table or list with student names and GPA values.\n\n"
                "Supported formats:\n"
                "• Table with Name and GPA columns\n"
                "• Lines like: 'John Smith  3.85'\n"
                "• Lines like: '1. John Smith - 3.85'")
            return

        self.students = students
        self.export_btn.setEnabled(True)
        self._update_stats()
        self._refresh_table()
        self.status_lbl.setText(f"✅  Loaded {len(students)} students from: {Path(self.pdf_path).name}")

    def _on_parse_error(self, msg: str):
        self.progress.hide()
        self.open_btn.setEnabled(True)
        self.drop_frame.setFixedHeight(130)
        self.status_lbl.setText(f"❌  Error: {msg}")
        QMessageBox.critical(self, "Parse Error", f"Failed to read PDF:\n{msg}")

    def _update_stats(self):
        if not self.students:
            return

        gpas = [s['gpa'] for s in self.students]
        avg  = sum(gpas) / len(gpas)
        self.stat_count.val_lbl.setText(str(len(self.students)))
        self.stat_avg.val_lbl.setText(f"{avg:.2f}")
        self.stat_high.val_lbl.setText(f"{max(gpas):.2f}")
        self.stat_low.val_lbl.setText(f"{min(gpas):.2f}")

        # Show stats bar
        self.stats_frame.setFixedHeight(70)

    def _refresh_table(self):
        query = self.search_input.text().lower().strip()
        descending = self.sort_combo.currentIndex() == 0

        filtered = [s for s in self.students if query in s['name'].lower()] if query else self.students[:]
        filtered.sort(key=lambda s: s['gpa'], reverse=descending)

        self.table.setRowCount(len(filtered))
        self.table.setRowHeight

        for row_idx, student in enumerate(filtered):
            rank = row_idx + 1

            # Rank
            rank_item = QTableWidgetItem(rank_icon(rank) if rank <= 3 else str(rank))
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            rank_item.setForeground(QColor(rank_color(rank)))
            font = QFont(); font.setBold(rank <= 3); font.setPointSize(13 if rank <= 3 else 11)
            rank_item.setFont(font)
            self.table.setItem(row_idx, 0, rank_item)

            # Name
            name_item = QTableWidgetItem(student['name'])
            name_item.setForeground(QColor(COLORS['text_primary']))
            name_font = QFont(); name_font.setPointSize(12); name_font.setBold(rank <= 3)
            name_item.setFont(name_font)
            self.table.setItem(row_idx, 1, name_item)

            # GPA
            gpa_item = QTableWidgetItem(f"{student['gpa']:.2f}")
            gpa_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            gpa_item.setForeground(QColor(self._gpa_color(student['gpa'])))
            gpa_font = QFont(); gpa_font.setBold(True); gpa_font.setPointSize(12)
            gpa_item.setFont(gpa_font)
            self.table.setItem(row_idx, 2, gpa_item)

            # Letter grade
            letter = self._gpa_to_letter(student['gpa'])
            grade_item = QTableWidgetItem(letter)
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            grade_item.setForeground(QColor(self._gpa_color(student['gpa'])))
            grade_font = QFont(); grade_font.setBold(True)
            grade_item.setFont(grade_font)
            self.table.setItem(row_idx, 3, grade_item)

            # Row height
            self.table.setRowHeight(row_idx, 46)

    def _export_csv(self):
        if not self.students:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "gpa_report.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        descending = self.sort_combo.currentIndex() == 0
        sorted_students = sorted(self.students, key=lambda s: s['gpa'], reverse=descending)

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("Rank,Name,GPA,Grade\n")
                for i, s in enumerate(sorted_students, 1):
                    f.write(f"{i},{s['name']},{s['gpa']:.2f},{self._gpa_to_letter(s['gpa'])}\n")
            self.status_lbl.setText(f"✅  Exported to {Path(path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))


# ── Entry point ──────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GPA Report Reader")
    app.setStyle("Fusion")

    # Dark palette base
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,       QColor(COLORS['bg_primary']))
    palette.setColor(QPalette.ColorRole.WindowText,   QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Base,         QColor(COLORS['bg_secondary']))
    palette.setColor(QPalette.ColorRole.AlternateBase,QColor(COLORS['bg_tertiary']))
    palette.setColor(QPalette.ColorRole.Text,         QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Button,       QColor(COLORS['bg_secondary']))
    palette.setColor(QPalette.ColorRole.ButtonText,   QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Highlight,    QColor(COLORS['accent_primary']))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
    app.setPalette(palette)

    win = GPAReaderWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
