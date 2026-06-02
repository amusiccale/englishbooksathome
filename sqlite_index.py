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
            MAX_FTS_ROWS = 150   # per pass (total ≈ 300)

            # ✅ FIRST PASS
            fts_rows_primary = self.cur.execute("""
                SELECT p.tcp, p.page_num, p.page_label, p.content
                FROM pages_fts f
                JOIN pages p ON f.tcp = p.tcp AND f.page_num = p.page_num
                WHERE f.content MATCH ?
                LIMIT ?
            """, (fts_query, MAX_FTS_ROWS)).fetchall()

            # ✅ SECOND PASS (shifted window)
            fts_rows_secondary = self.cur.execute("""
                SELECT p.tcp, p.page_num, p.page_label, p.content
                FROM pages_fts f
                JOIN pages p ON f.tcp = p.tcp AND f.page_num = p.page_num
                WHERE f.content MATCH ?
                LIMIT ? OFFSET ?
            """, (fts_query, MAX_FTS_ROWS, MAX_FTS_ROWS)).fetchall()

            # ✅ COMBINE + DEDUPE
            seen = set()
            rows = []

            for tcp, page_num, page_label, text in fts_rows_primary + fts_rows_secondary:
                key = (tcp, page_num)
                if key not in seen:
                    rows.append((tcp, page_num, page_label, text))
                    seen.add(key)


            # ✅ fallback remains unchanged
            if not rows:
                print("FTS miss → fuzzy fallback to full scan")
                rows = self.cur.execute("""
                    SELECT tcp, page_num, page_label, content
                    FROM pages
                """).fetchall()
                rows = rows[:200]


##-----------EXACT MODE---------
        else:
            # ✅ Exact mode (unchanged)
            rows = self.cur.execute("""
                SELECT tcp, page_num, page_label, content
                FROM pages
            """).fetchall()

        # ✅ Debug
        print("Rows pulled:", len(rows))

        #======================
        #---metadata lookup, added 2 June 26====
        #======================
        
        #=====✅ METADATA SEARCH (author + title)
        meta_rows = self.cur.execute("""
            SELECT tcp FROM documents
            WHERE LOWER(author) LIKE ?
               OR LOWER(title) LIKE ?
        """, (f"%{query_lower}%", f"%{query_lower}%")).fetchall()

        meta_tcps = set(r[0] for r in meta_rows)

        if meta_tcps:
            meta_pages = []

            for tcp in meta_tcps:
                pages = self.cur.execute("""
                    SELECT tcp, page_num, page_label, content
                    FROM pages
                    WHERE tcp = ?
                    LIMIT 10
                """, (tcp,)).fetchall()

                meta_pages.extend(pages)

            # ✅ merge + dedupe
            seen = set((t[0], t[1]) for t in rows)
            for r in meta_pages:
                key = (r[0], r[1])
                if key not in seen:
                    rows.append(r)
                    seen.add(key)
        
        # =========================
        # PROCESS MATCHES
        # =========================
        # ✅ ULTRA-FAST STRAT: pre-classify rows (order-preserving)
        pre_filtered = []
        needs_fuzzy = []

        for tcp, page_num, page_label, text in rows:
            text_lower = text.lower()

            # ✅ direct text hits
            if query_lower in text_lower:
                pre_filtered.append((tcp, page_num, page_label, text))

            # ✅ metadata hits must survive
            elif tcp in meta_tcps:
                pre_filtered.append((tcp, page_num, page_label, text))

            # ✅ possible fuzzy candidates
            elif query_lower[:3] in text_lower:
                needs_fuzzy.append((tcp, page_num, page_label, text))


        # ✅ cap fuzzy workload AFTER loop
        MAX_FUZZY_ROWS = 30
        needs_fuzzy = needs_fuzzy[:MAX_FUZZY_ROWS]

        # ✅ track fuzzy rows
        fuzzy_only_set = set((tcp, page_num) for tcp, page_num, _, _ in needs_fuzzy)

        # ✅ merge WITHOUT breaking document order
        seen = set()
        final_rows = []

        for r in rows:
            key = (r[0], r[1])
            if key in seen:
                continue

            if r in pre_filtered or r in needs_fuzzy:
                final_rows.append(r)
                seen.add(key)

        rows = final_rows
        
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
                    if tcp in meta_tcps:
                        matches = [0]   # ✅ PRIORITY FIX
                    else:
                        approx = text_lower.find(query_lower[:3])
                        if approx != -1:
                            matches = [approx]
                        else:
                            continue

            # ========= PHRASE =========
            elif mode == "Phrase":
                matches = [
                    m.start()
                    for m in re.finditer(re.escape(query_lower), text_lower)
                ]

                if not matches:
                    if tcp in meta_tcps:
                        matches = [0]   # ✅ PRIORITY FIX
                    else:
                        approx = text_lower.find(query_lower[:3])
                        if approx != -1:
                            matches = [approx]
                        else:
                            continue

            # ========= FUZZY =========
            else:
                from rapidfuzz import fuzz

                # ✅ FAST PATH FIRST: substring match (handles most real cases)
                if query_lower in text_lower:
                    found = True

                else:
                    # ✅ lightweight prefilter (skip obvious misses fast)
                    if len(query_lower) >= 6:
                        if query_lower[:5] not in text_lower:
                            continue

                    norm_text = normalize_text(text)
                    norm_query = normalize_text(query)

                    # ✅ SINGLE fuzzy check (no anchors, no windows)
                    if fuzz.partial_ratio(norm_query, norm_text) >= 75:
                        found = True
                    else:
                        continue

                # ✅ REGEX MATCH (for KWIC offsets)
                matches = [
                    m.start()
                    for m in re.finditer(re.escape(query_lower), text_lower)
                ]

                # ✅ fallback for fuzzy / exact / phrase hits
                if not matches:
                    # ✅ FIRST priority: metadata (author/title)
                    if tcp in meta_tcps:
                        matches = [0]   # force survival

                    else:
                        approx = text_lower.find(query_lower[:3])
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
