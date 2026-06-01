def export_ris(row, filepath):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("TY  - BOOK\n")

        title = row.get("Title", "")
        author = row.get("Author", "")
        date = row.get("Date", "")
        publisher = row.get("Publisher", "")
        tcp = row.get("TCP", "")

        f.write(f"TI  - {title}\n")
        f.write(f"AU  - {author}\n")
        f.write(f"PY  - {date}\n")
        f.write(f"PB  - {publisher}\n")
        f.write(f"ID  - {tcp}\n")

        f.write("ER  - \n")
