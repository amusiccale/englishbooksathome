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
        if elem.tag == "PB":
            if current:
                pages.append("\n".join(current))
            current = []

        elif elem.tag in ["P", "L"]:
            text = "".join(elem.itertext()).strip()
            if text:
                current.append(text)

    if current:
        pages.append("\n".join(current))

    return pages
