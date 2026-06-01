def generate_kwic(text, matches, width=40):
    rows = []

    for m in matches:
        left = text[max(0, m-width):m]
        right = text[m+20:m+width]

        rows.append((left.strip(), text[m:m+20], right.strip(), m))

    return rows
