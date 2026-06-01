"""
We Have Early English Books at Home
SQLite Index with Page Awareness
"""

import sqlite3
import os
import re
from lxml import etree


class SQLiteIndex:

    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.create_tables()

    def create_tables(self):

        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            tcp TEXT PRIMARY KEY,
            author TEXT,
            title TEXT,
            publisher TEXT,
            collection TEXT,
            date TEXT,
            year INTEGER
        )
        """)

        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            tcp TEXT,
            page_num INTEGER,
            page_label TEXT,
            content TEXT
        )
        """)

        self.conn.commit()

    def extract_year(self, date_str):
        if not date_str:
            return 0

        date_str = str(date_str)
        date_str = re.sub(r"[\[\]]", "", date_str)

        # Arabic first
        match = re.search(r"\d{3,4}", date_str)
        if match:
            return int(match.group(0))

        return 0


    # =========================
    def build_index(self, csv_data, xml_root):

        for row in csv_data:

            tcp = str(row.get("TCP", ""))

            xml_path = None

            for root, _, files in os.walk(xml_root):
                for f in files:
                    if tcp in f and f.endswith(".xml"):
                        xml_path = os.path.join(root, f)
                        break
                if xml_path:
                    break

            if not xml_path:
                continue

            try:
                tree = etree.parse(xml_path)
                root = tree.getroot()
            except:
                continue

            self.cur.execute("DELETE FROM pages WHERE tcp=?", (tcp,))

            text_buffer = []
            page_label = "1"
            page_num = 0

            for elem in root.iter():

                if elem.tag == "PB":

                    if text_buffer:
                        page_text = " ".join(text_buffer)

                        self.cur.execute(
                            "INSERT INTO pages VALUES (?, ?, ?, ?)",
                            (tcp, page_num, page_label, page_text)
                        )

                        text_buffer = []
                        page_num += 1

                    page_label = elem.attrib.get("REF", str(page_num + 1))

                elif elem.tag in ["P", "L"]:

                    txt = "".join(elem.itertext()).strip()

                    if txt:
                        clean = re.sub(r"\s+", " ", txt)
                        clean = clean.replace("ſ", "s")
                        text_buffer.append(clean)

            if text_buffer:
                page_text = " ".join(text_buffer)

                self.cur.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, ?)",
                    (tcp, page_num, page_label, page_text)
                )

            self.cur.execute("""
                INSERT OR REPLACE INTO documents
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                tcp,
                row.get("Author", ""),
                row.get("Title", ""),
                row.get("Publisher", ""),
                row.get("COLLECTION", ""),
                row.get("Date", ""),
                self.extract_year(row.get("Date"))
            ))

        self.conn.commit()

    # =========================
    def get_pages(self, tcp):

        return self.cur.execute("""
            SELECT page_num, page_label, content
            FROM pages
            WHERE tcp=?
            ORDER BY page_num
        """, (tcp,)).fetchall()

    # =========================
    def search(self, query, min_year=1400, max_year=1900):

        results = {}

        if not query or not query.strip():
            return results

        query = query.lower().strip()

        rows = list(self.cur.execute("""
            SELECT d.*, p.page_num, p.page_label, p.content
            FROM documents d
            JOIN pages p ON d.tcp = p.tcp
        """))

        print("Rows pulled:", len(rows))

        for r in rows:

            tcp = r[0]
            page_num = r[7]
            page_label = r[8]
            text = r[9]

            matches = [
                m.start()
                for m in re.finditer(re.escape(query), text.lower())
            ]

            if not matches:
                continue

            entry = results.setdefault(tcp, {
                "meta": dict(zip(
                    ["TCP", "Author", "Title", "Publisher", "Collection", "Date", "Year"],
                    r[:7]
                )),
                "pages": []
            })

            entry["pages"].append({
                "tcp": tcp,
                "page_num": page_num,
                "page_label": page_label,
                "text": text,
                "matches": matches
            })

        print("Documents returned:", len(results))

        return results
