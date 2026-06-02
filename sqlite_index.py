"""
SQLite Index with FTS + Mode-Safe Search
"""

import sqlite3
import os
import re
from lxml import etree
from concurrent.futures import ProcessPoolExecutor


# =========================
# Helpers (TOP LEVEL)
# =========================

def normalize_text(text):
    text = text.lower()
    text = text.replace("ſ", "s")
    text = text.replace("œ", "ae")
    text = text.replace("æ", "ae")
    text = text.replace("þ", "th")
    text = text.replace("vv", "w")
    text = text.replace("uu", "w")
    text = re.sub(r"[^\w\s]", "", text)
    return text


def clean_fts_query(q):
    q = q.replace('"', '').strip()
    q = re.sub(r"[^\w\s]", " ", q)
    return q


def parse_xml_file(args):
    tcp, xml_path = args

    try:
        tree = etree.parse(xml_path)
        root = tree.getroot()
    except:
        return tcp, []

    pages = []
    text_buffer = []
    page_label = "1"
    page_num = 0

    for elem in root.iter():

        if elem.tag == "PB":
            if text_buffer:
                page_text = " ".join(text_buffer)
                pages.append((page_num, page_label, page_text))
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
        pages.append((page_num, page_label, page_text))

    return tcp, pages


# =========================
# SQLite Index Class
# =========================

class SQLiteIndex:

    def __init__(self, db_path):

        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()

        self.create_tables()

        # ✅ Performance tuning
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.conn.execute("PRAGMA cache_size = -100000")

    # =========================

    def create_tables(self):

        self.cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts
        USING fts5(
            tcp,
            page_num,
            content,
            tokenize = 'unicode61'
        )
        """)

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

    # =========================

    def extract_year(self, date_str):

        if not date_str:
            return 0

        date_str = str(date_str)
        date_str = re.sub(r"[\[\]]", "", date_str)

        match = re.search(r"\d{3,4}", date_str)
        if match:
            return int(match.group(0))

        return 0

    # =========================

    def build_index(self, csv_data, xml_root):

        self.conn.execute("BEGIN")

        page_batch = []
        fts_batch = []

        # ✅ build XML map once
        xml_map = {}
        for root_dir, _, files in os.walk(xml_root):
            for f in files:
                if f.endswith(".xml"):
                    xml_map[f.replace(".xml", "")] = os.path.join(root_dir, f)

        tasks = []
        meta_map = {}

        for row in csv_data:
            tcp = str(row.get("TCP", ""))
            xml_path = xml_map.get(tcp)

            if xml_path:
                tasks.append((tcp, xml_path))
                meta_map[tcp] = row

        with ProcessPoolExecutor() as executor:

            for tcp, pages in executor.map(parse_xml_file, tasks):

                if not pages:
                    continue

                row = meta_map[tcp]

                self.cur.execute("DELETE FROM pages WHERE tcp=?", (tcp,))
                self.cur.execute("DELETE FROM pages_fts WHERE tcp=?", (tcp,))

                for page_num, page_label, page_text in pages:
                    page_batch.append((tcp, page_num, page_label, page_text))
                    fts_batch.append((tcp, page_num, normalize_text(page_text)))

                if len(page_batch) >= 1000:
                    self.cur.executemany(
                        "INSERT INTO pages VALUES (?, ?, ?, ?)", page_batch
                    )
                    self.cur.executemany(
                        "INSERT INTO pages_fts (tcp, page_num, content) VALUES (?, ?, ?)", fts_batch
                    )
                    page_batch.clear()
                    fts_batch.clear()

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

        if page_batch:
            self.cur.executemany(
                "INSERT INTO pages VALUES (?, ?, ?, ?)", page_batch
            )
            self.cur.executemany(
                "INSERT INTO pages_fts (tcp, page_num, content) VALUES (?, ?, ?)", fts_batch
            )

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

    def search(self, query, min_year=1400, max_year=1900, mode="Fuzzy"):

        results = {}

        if not query or not query.strip():
            return results

        query = query.strip()
        query_lower = query.lower()

        # =========================
        # FETCH CANDIDATE ROWS
        # =========================
        # ✅ clean FTS query
        fts_query = normalize_text(clean_fts_query(query))

        # ✅ tighten Phrase search (important)
        if mode == "Phrase":
            fts_query = f'"{fts_query}"'

        # =========================
        # FETCH CANDIDATE ROWS
        # =========================

        if mode == "Phrase":

            rows = self.cur.execute("""
                SELECT p.tcp, p.page_num, p.page_label, p.content
                FROM pages_fts f
                JOIN pages p ON f.tcp = p.tcp AND f.page_num = p.page_num
                WHERE f.content MATCH ?
            """, (fts_query,)).fetchall()

## revised Fuzzy logic, 2 June 26
        elif mode == "Fuzzy":

            # ✅ limit FTS at SQL level
            MAX_FTS_ROWS = 200

            fts_rows = self.cur.execute(f"""
                SELECT p.tcp, p.page_num, p.page_label, p.content
                FROM pages_fts f
                JOIN pages p ON f.tcp = p.tcp AND f.page_num = p.page_num
                WHERE f.content MATCH ?
                LIMIT {MAX_FTS_ROWS}
            """, (fts_query,)).fetchall()

            if fts_rows:
                rows = fts_rows
            else:
                print("FTS miss → fuzzy fallback to full scan")
                rows = self.cur.execute("""
                    SELECT tcp, page_num, page_label, content
                    FROM pages
                """).fetchall()
                rows = rows[:200]

            # ✅ LIMIT pages per document (preserve edition diversity)
            MAX_PAGES_PER_DOC = 3
            doc_counts = {}
            diverse_rows = []

            for tcp, page_num, page_label, text in rows:
                count = doc_counts.get(tcp, 0)
                if count < MAX_PAGES_PER_DOC:
                    diverse_rows.append((tcp, page_num, page_label, text))
                    doc_counts[tcp] = count + 1

            rows = diverse_rows


            # ✅ SINGLE filtering stage (keep only one!)
            preview = query_lower[:4] if len(query_lower) >= 4 else query_lower

            filtered_rows = [
                (tcp, page_num, page_label, text)
                for tcp, page_num, page_label, text in rows
                if preview in text.lower()
            ]

            # ✅ fallback safety
            if not filtered_rows:
                filtered_rows = rows

            # ✅ FINAL DIVERSITY-PRESERVING CAP
            MAX_FINAL_ROWS = 150 if len(query_lower) >= 6 else 120

            if len(filtered_rows) > MAX_FINAL_ROWS:
                half = MAX_FINAL_ROWS // 2
                rows = filtered_rows[:half] + filtered_rows[-half:]
            else:
                rows = filtered_rows

##        elif mode == "Fuzzy":
##
##            # ✅ limit FTS at SQL level (fastest win)
##            MAX_FTS_ROWS = 200
##
##            fts_rows = self.cur.execute(f"""
##                SELECT p.tcp, p.page_num, p.page_label, p.content
##                FROM pages_fts f
##                JOIN pages p ON f.tcp = p.tcp AND f.page_num = p.page_num
##                WHERE f.content MATCH ?
##                LIMIT {MAX_FTS_ROWS}
##            """, (fts_query,)).fetchall()
##
##            if fts_rows:
##                rows = fts_rows
##            else:
##                print("FTS miss → fuzzy fallback to full scan")
##                rows = self.cur.execute("""
##                    SELECT tcp, page_num, page_label, content
##                    FROM pages
##                """).fetchall()
##
##                rows = rows[:200]   # ✅ cap fallback
##
##            # ✅ LIMIT pages per document (critical for recall)
##            MAX_PAGES_PER_DOC = 3
##
##            doc_counts = {}
##            diverse_rows = []
##
##            for tcp, page_num, page_label, text in rows:
##                count = doc_counts.get(tcp, 0)
##
##                if count < MAX_PAGES_PER_DOC:
##                    diverse_rows.append((tcp, page_num, page_label, text))
##                    doc_counts[tcp] = count + 1
##
##            # ✅ replace rows with diversified set
##            rows = diverse_rows
##
##
##            # ✅ SMART substring filter (lightweight, never zero-out)
##            preview = query_lower[:4] if len(query_lower) >= 4 else query_lower
##
##            filtered_rows = [
##                (tcp, page_num, page_label, text)
##                for tcp, page_num, page_label, text in rows
##                if preview in text.lower()
##            ]
##
##            # ✅ SAFE fallback (never allow empty candidate set)
##            if not filtered_rows:
##                filtered_rows = rows
##
##            # ✅ FINAL CAP (keeps fuzzy fast)
##            MAX_FINAL_ROWS = 120
##
##            if len(filtered_rows) > MAX_FINAL_ROWS:
##                half = MAX_FINAL_ROWS // 2
##                rows = filtered_rows[:half] + filtered_rows[-half:]
##            else:
##                rows = filtered_rows
##
##                
##            #====================    
##            # ✅ SMART anchor selection
##            anchors = []
##
##            if len(query_lower) >= 6:
##                anchors = [
##                    query_lower[:4],
##                    query_lower[-4:],
##                    query_lower[1:5]
##                ]
##            elif len(query_lower) >= 4:
##                anchors = [query_lower[:3]]
##            else:
##                anchors = [query_lower]
##
##            filtered_rows = []
##
##            for tcp, page_num, page_label, text in rows:
##                t = text.lower()
##
##                if any(anchor in t for anchor in anchors):
##                    filtered_rows.append((tcp, page_num, page_label, text))
##
##            # ✅ NEW: progressive fallback instead of all-or-nothing
##            if len(filtered_rows) < 10:
##                print("Anchor filter too strict → relaxing")
##
##                weaker_anchor = query_lower[:3] if len(query_lower) >= 3 else query_lower
##
##                filtered_rows = [
##                    (tcp, page_num, page_label, text)
##                    for tcp, page_num, page_label, text in rows
##                    if weaker_anchor in text.lower()
##                ]
##
##            # ✅ FINAL fallback (don’t overfilter to zero)
##            if not filtered_rows:
##                print("Filter eliminated everything → using raw rows")
##                filtered_rows = rows[:200]
##
##            # ✅ FINAL cap
##            rows = filtered_rows[:120]
##
##            # ✅ ===== NEW: FAST substring prefilter =====
##            preview = query_lower[:4] if len(query_lower) >= 4 else query_lower
##
##            filtered_rows = []
##            for tcp, page_num, page_label, text in rows:
##                if preview in text.lower():
##                    filtered_rows.append((tcp, page_num, page_label, text))
##
##            # ✅ fallback if filter is too strict
##            if not filtered_rows:
##                filtered_rows = rows
##
##            # ✅ FINAL row cap BEFORE fuzzy runs
##            # ✅ balance early + later rows for better coverage
##            MAX_FINAL_ROWS = 150 if len(query_lower) >= 6 else 120
##
##            if len(filtered_rows) > MAX_FINAL_ROWS:
##                half = MAX_FINAL_ROWS // 2
##                rows = filtered_rows[:half] + filtered_rows[-half:]
##            else:
##                rows = filtered_rows


##-----------EXACT MODE---------
        else:
            # ✅ Exact mode (unchanged)
            rows = self.cur.execute("""
                SELECT tcp, page_num, page_label, content
                FROM pages
            """).fetchall()

        # ✅ Debug
        print("Rows pulled:", len(rows))
        # =========================
        # PROCESS MATCHES
        # =========================

        for tcp, page_num, page_label, text in rows:

            text_lower = text.lower()

            # ========= EXACT =========
            if mode == "Exact":
                pattern = rf"\b{re.escape(query_lower)}\b"

                matches = [
                    m.start()
                    for m in re.finditer(pattern, text_lower)
                ]

                if not matches:
                    continue

            # ========= PHRASE =========
            elif mode == "Phrase":
                matches = [
                    m.start()
                    for m in re.finditer(re.escape(query_lower), text_lower)
                ]

                if not matches:
                    continue

            # ========= FUZZY, now with rows capped at 500 for speed  =========
            else:
                from rapidfuzz import fuzz

                norm_text = normalize_text(text)
                norm_query = normalize_text(query)

                # ✅ FAST prefilter (skip clearly irrelevant pages)
                if len(query_lower) >= 6:
                    if query_lower[:6] not in text_lower and norm_query[:6] not in norm_text:
                        continue

                # ✅ FIND ANCHOR POSITIONS (instead of scanning whole text)
                anchor = query_lower[:3] if len(query_lower) >= 3 else query_lower

                candidate_positions = [
                    m.start()
                    for m in re.finditer(re.escape(anchor), text_lower)
                ]

                # ✅ LIMIT WORK (critical for speed)
                if len(candidate_positions) > 30:
                    candidate_positions = candidate_positions[:30]

                found = False

                for pos in candidate_positions:
                    window = text_lower[max(0, pos-25):pos+len(query_lower)+25]

                    if fuzz.ratio(normalize_text(window), norm_query) >= 70:
                        found = True
                        break

                if not found:
                    # ✅ fallback: allow rows that have exact substring matches
                    if query_lower in text_lower:
                        found = True
                    else:
                        continue

                # ✅ REGEX MATCH (for KWIC/offset stability)
                matches = [
                    m.start()
                    for m in re.finditer(re.escape(query_lower), text_lower)
                ]

                if not matches:
                    approx = text_lower.find(anchor)
                    if approx != -1:
                        matches = [approx]
                    else:
                        continue
            # =========================
            # BUILD RESULTS
            # =========================

            r = self.cur.execute("""
                SELECT * FROM documents WHERE tcp=?
            """, (tcp,)).fetchone()

            entry = results.setdefault(tcp, {
                "meta": dict(zip(
                    ["TCP","Author","Title","Publisher","Collection","Date","Year"],
                    r
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
