from lxml import etree

def extract_pages(xml_path):
    try:
        tree = etree.parse(xml_path)
        root = tree.getroot()
    except:
        return []

    pages = []
    current = []

    for elem in root.iter():

        tag = elem.tag

        # ✅ skip non-element nodes (comments, etc.)
        if not isinstance(tag, str):
            continue

        # ✅ SAFE normalization (handles namespaces + case)
        # ex: "{tei}p" → "p"
        tag = tag.split("}")[-1].upper()

        # ✅ Page break
        if tag == "PB":
            if current:
                pages.append("\n".join(current))
                current = []

        # ✅ Paragraph / line text (ECCO + EEBO compatible)
        elif tag == "P" or tag == "L":
            text = "".join(elem.itertext()).strip()
            if text:
                current.append(text)

    # ✅ final page flush
    if current:
        pages.append("\n".join(current))

    return pages
