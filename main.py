"""
We Have Early English Books at Home
Main Controller (Restored + Stable + Features)
"""

import sys, re
import pandas as pd

from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QTreeWidgetItem,
    QTableWidgetItem, QMessageBox, QHBoxLayout, QPushButton, QFontDialog
)
from PyQt6.QtGui import QTextOption, QPalette, QColor
from PyQt6.QtCore import Qt

from ui import MainUI
from kwic import generate_kwic
from ris_export import export_ris
from sqlite_index import SQLiteIndex


class NumericTreeItem(QTreeWidgetItem):
    def __lt__(self, other):
        column = self.treeWidget().sortColumn()

        # ✅ Only enforce numeric comparison on Hits column (col 6)
        if column == 6:
            try:
                return int(self.text(column)) < int(other.text(column))
            except:
                return super().__lt__(other)

        # ✅ fallback for all other columns
        return super().__lt__(other)

def safe_str(val):
    if pd.isna(val):
        return ""
    return str(val)


class App(MainUI):

    def __init__(self):
        super().__init__()

        self.csv_data = []
        self.root_dir = None
        self.db = None

        self.csv_loaded = False
        self.xml_loaded = False

        self.current_pages = []
        self.current_page = 0
        self.search_rows = []

        self.setup_ui()
        self.build_advanced_search()
        self.bind_controls()

    # ================= CONTROLS =================
    def bind_controls(self):

        self.btn_csv.clicked.connect(self.load_csv)
        self.btn_xml.clicked.connect(self.load_xml)
        self.btn_rebuild.clicked.connect(self.rebuild_index)
        self.btn_search.clicked.connect(self.search)

        self.btn_font.clicked.connect(self.open_font)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        self.btn_left.clicked.connect(lambda: self.set_align(Qt.AlignmentFlag.AlignLeft))
        self.btn_center.clicked.connect(lambda: self.set_align(Qt.AlignmentFlag.AlignCenter))
        self.btn_right.clicked.connect(lambda: self.set_align(Qt.AlignmentFlag.AlignRight))

        self.btn_next.clicked.connect(self.next_page)
        self.btn_prev.clicked.connect(self.prev_page)

    # ================= STATUS =================
    def update_status(self):
        if self.csv_loaded and self.xml_loaded:
            self.status_label.setStyleSheet("color: green; font-size: 16px;")
        elif self.csv_loaded or self.xml_loaded:
            self.status_label.setStyleSheet("color: orange; font-size: 16px;")
        else:
            self.status_label.setStyleSheet("color: red; font-size: 16px;")

    # ================= SEARCH UI =================
    def build_advanced_search(self):

        self.search_rows = []

        row_layout, row_data = self.make_search_row()
        self.adv_layout.addLayout(row_layout)
        self.search_rows.append(row_data)

        row_data[0].returnPressed.connect(self.search)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+")
        self.btn_remove = QPushButton("–")

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_remove)
        self.adv_layout.addLayout(btn_row)

        self.btn_add.clicked.connect(self.add_search_row)
        self.btn_remove.clicked.connect(self.remove_last_row)

    def add_search_row(self):
        if len(self.search_rows) >= 5:
            return
        row_layout, row_data = self.make_search_row()
        self.adv_layout.insertLayout(len(self.search_rows), row_layout)
        self.search_rows.append(row_data)
        row_data[0].returnPressed.connect(self.search)

    def remove_last_row(self):
        if len(self.search_rows) <= 1:
            return
        layout = self.adv_layout.takeAt(len(self.search_rows)-1)
        if layout:
            for i in reversed(range(layout.count())):
                w = layout.itemAt(i).widget()
                if w:
                    w.deleteLater()
        self.search_rows.pop()

    def get_query(self):
        for q, _, _, _ in self.search_rows:
            if q.text().strip():
                return q.text()
        return ""

    # ================= LOAD =================
    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self)
        if not path:
            return

        df = pd.read_csv(path)
        self.csv_data = df.to_dict("records")

        db_path = path + ".db"
        self.db = SQLiteIndex(db_path)

        print("Database loaded")

        self.csv_loaded = True
        self.update_status()

    def load_xml(self):
        path = QFileDialog.getExistingDirectory(self)
        if not path or not self.db:
            return

        self.root_dir = path

        print("XML directory set — no indexing performed")
        QMessageBox.information(
            self,
            "Index Status",
            "Index not rebuilt automatically.\nClick 'Rebuild Index' if needed."
        )

        self.xml_loaded = True
        self.update_status()


    def rebuild_index(self):
        if not self.db or not self.root_dir:
            QMessageBox.warning(self, "Error", "Load CSV + XML first.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Rebuild",
            "Rebuild the index? This may take a few minutes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )

        if reply == QMessageBox.StandardButton.Yes:
            print("Rebuilding index...")
            self.db.build_index(self.csv_data, self.root_dir)
            print("Index rebuild complete.")

    # ================= SEARCH =================
    def search(self):

        self.results.clear()

        if not self.db:
            return

        # ✅ collect advanced rows
        queries = []

        for (q, field, mode_box, op_box) in self.search_rows:
            text = q.text().strip()
            if not text:
                continue

            queries.append({
                "query": text,
                "mode": mode_box.currentText(),
                "op": op_box.currentText()
            })

        if not queries:
            return

        # ✅ year filter
        min_year = self.date_min.value()
        max_year = self.date_max.value()
        if min_year > max_year:
            min_year, max_year = max_year, min_year

        print("Advanced queries:", queries)
        print("Year filter:", min_year, max_year)

        # ✅ ---- FIRST QUERY ----
        base = queries[0]

        print("Query:", base["query"], "| Mode:", base["mode"])

        results = self.db.search(
            base["query"],
            min_year,
            max_year,
            mode=base["mode"]
        )

        print("Documents returned (base):", len(results))

        # ✅ ---- BOOLEAN STACKING ----
        for q in queries[1:]:

            print(f"Applying {q['op']} with:", q["query"], "| Mode:", q["mode"])

            new_results = self.db.search(
                q["query"],
                min_year,
                max_year,
                mode=q["mode"]
            )

            print("Documents returned (new):", len(new_results))

            if q["op"] == "AND":
                results = {k: v for k, v in results.items() if k in new_results}

            elif q["op"] == "OR":
                for k, v in new_results.items():
                    if k not in results:
                        results[k] = v

            elif q["op"] == "NOT":
                results = {k: v for k, v in results.items() if k not in new_results}

        print("Final documents returned:", len(results))

        # ✅ ---- BUILD UI ----
        query_lower = base["query"].lower()
        
        for tcp, data in results.items():

            pages = data["pages"]
            meta = data["meta"]
            #total_hits = sum(len(p["matches"]) for p in pages)
            total_hits = sum(len(p["matches"]) for p in pages)

            # ✅ ranking boosters
            title_match = query_lower in safe_str(meta.get("Title", "")).lower()
            author_match = query_lower in safe_str(meta.get("Author", "")).lower()

            score = total_hits

            # ✅ boost title heavily
            if title_match:
                score += 1000

            # ✅ boost author moderately
            if author_match:
                score += 500


            parent = NumericTreeItem([
                safe_str(meta.get("TCP", tcp)),
                safe_str(meta.get("Author", "")),
                safe_str(meta.get("Date", "")),
                safe_str(meta.get("Title", "")),
                safe_str(meta.get("Publisher", "")),
                safe_str(meta.get("Collection", "")),
                str(total_hits)
            ])

            parent.setData(6, Qt.ItemDataRole.UserRole, score)
            parent.setData(2, Qt.ItemDataRole.UserRole, meta.get("Year", 0))
            
            # ✅ load ALL pages for this document
            all_pages_raw = self.db.get_pages(tcp)

            # ✅ convert to full document page list (WITH tcp!)
            all_pages = [
                {
                    "tcp": tcp,               # ✅ REQUIRED
                    "page_num": p[0],
                    "page_label": p[1],
                    "text": p[2],
                    "matches": []
                }
                for p in all_pages_raw
            ]

            # ✅ map hit pages using page_num (NOT label)
            hit_map = {p["page_num"]: p for p in pages}

            for ap in all_pages:
                if ap["page_num"] in hit_map:
                    ap["matches"] = hit_map[ap["page_num"]]["matches"]

            # ✅ store FULL document
            parent.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "doc",
                "meta": meta,
                "pages": all_pages
            })

##            parent.setData(0, Qt.ItemDataRole.UserRole, {
##                "type": "doc",
##                "meta": meta,
##                ## old page load logic ========
##                ## "pages": pages
##                all_pages = self.db.cur.execute("""
##                SELECT page_num, page_label, content
##                FROM pages
##                WHERE tcp = ?
##                ORDER BY page_num
##            """, (tcp,)).fetchall()
##
##            parent.setData(0, Qt.ItemDataRole.UserRole, {
##                "type": "doc",
##                "meta": meta,
##                "pages": [
##                    {
##                        "page_num": p[0],
##                        "page_label": p[1],
##                        "text": p[2],
##                        "matches": []  # will mark later if it's a hit
##                    }
##                    for p in all_pages
##                ]
##            })

            for p in pages:
                child = QTreeWidgetItem([
                    "", "", "", f"Page {p['page_label']}", "", "", str(len(p["matches"]))
                ])

                child.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "page",
                    "page": p
                })

                parent.addChild(child)

            self.results.addTopLevelItem(parent)

        self.results.collapseAll()
        # ✅ enforce numeric sorting by Hits column
        self.results.sortItems(6, Qt.SortOrder.DescendingOrder)


        try:
            self.results.itemClicked.disconnect()
        except:
            pass

        self.results.itemClicked.connect(self.handle_click)

    # ================= CLICK =================
    def handle_click(self, item):

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data["type"] == "doc":
            self.current_pages = data["pages"]
            self.current_page = 0

        elif data["type"] == "page":

            tcp = data["page"]["tcp"]

            # ✅ load FULL document
            raw_pages = self.db.get_pages(tcp)

            full_pages = [
                {
                    "tcp": tcp,
                    "page_num": p[0],
                    "page_label": p[1],
                    "text": p[2],
                    "matches": []
                }
                for p in raw_pages
            ]

            # ✅ reattach matches from search results
            search_pages = item.parent().data(0, Qt.ItemDataRole.UserRole)["pages"]

            match_map = {p["page_num"]: p["matches"] for p in search_pages}

            for p in full_pages:
                if p["page_num"] in match_map:
                    p["matches"] = match_map[p["page_num"]]

            self.current_pages = full_pages

            # jump to correct page
            self.current_page = data["page"]["page_num"]
            
        if self.current_pages:
            self.current_page = max(0, min(self.current_page, len(self.current_pages) - 1))

        self.update_page()

    # ================= PAGE =================
    def update_page(self):

        if not self.current_pages:
            return

        if self.current_page >= len(self.current_pages):
            self.current_page = 0

        page = self.current_pages[self.current_page]
        text = page["text"]

        self.preview.setPlainText(text)

        hit_count = len(page.get("matches", []))

        label = f"Page {page['page_label']} ({self.current_page+1}/{len(self.current_pages)})"

        if hit_count:
            label += f" | {hit_count} hits"

        self.page_label.setText(label)

        matches = page.get("matches", [])
        matches = [m for m in matches if 0 <= m < len(text)]

        self.highlight_all(matches, len(self.get_query()))

        kwic_rows = generate_kwic(text, matches)

        self.kwic.clearContents()
        self.kwic.setRowCount(0)

        for i, (l, m, r, pos) in enumerate(kwic_rows):
            self.kwic.insertRow(i)
            item = QTableWidgetItem(l)
            item.setData(Qt.ItemDataRole.UserRole, pos)

            self.kwic.setItem(i, 0, item)
            self.kwic.setItem(i, 1, QTableWidgetItem(m))
            self.kwic.setItem(i, 2, QTableWidgetItem(r))

        self.kwic.cellClicked.connect(self.jump_to_kwic)

    def jump_to_kwic(self, row, col):
        pos = self.kwic.item(row, 0).data(Qt.ItemDataRole.UserRole)
        cursor = self.preview.textCursor()
        cursor.setPosition(pos)
        self.preview.setTextCursor(cursor)
        self.preview.ensureCursorVisible()

    # ================= NAV =================
    def next_page(self):
        if self.current_page < len(self.current_pages)-1:
            self.current_page += 1
            self.update_page()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_page()

    # ================= FONT =================
    def open_font(self):
        font, ok = QFontDialog.getFont()
        if ok:
            self.preview.setFont(font)

    def set_align(self, alignment):
        opt = self.preview.document().defaultTextOption()
        opt.setAlignment(alignment)
        self.preview.document().setDefaultTextOption(opt)

    # ================= FULLSCREEN =================
    def toggle_fullscreen(self):
        if not hasattr(self, "_fs"):
            self._fs = False

        if not self._fs:
            self._parent_layout = self.preview.parentWidget().layout()
            self.preview.setParent(None)
            self.preview.setWindowFlag(Qt.WindowType.Window)
            self.preview.showFullScreen()
            self._fs = True
        else:
            self.preview.showNormal()
            self._parent_layout.addWidget(self.preview)
            self._fs = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and getattr(self, "_fs", False):
            self.toggle_fullscreen()

    #===========RIS EXPORT==========
    def export_selected(self, meta):
        from PyQt6.QtWidgets import QFileDialog

        # ✅ prompt for file save location
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export RIS",
            "",
            "RIS Files (*.ris)"
        )

        if not path:
            return

        try:
            export_ris(meta, path)
            print(f"RIS export successful: {path}")
            QMessageBox.information(self, "Export Complete", f"Saved to:\n{path}")
        except Exception as e:
            print(f"RIS export failed: {e}")
        
if __name__ == "__main__":
    app = QApplication(sys.argv)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Base, QColor("white"))
    palette.setColor(QPalette.ColorRole.Text, QColor("black"))
    app.setPalette(palette)

    w = App()
    w.resize(1300, 900)
    w.show()

    sys.exit(app.exec())
