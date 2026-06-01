import re
from rapidfuzz import fuzz

def normalize(text):
    text = text.lower()
    text = text.replace("ſ", "s")
    text = re.sub(r"[^\w\s]", "", text)
    return text

def find_matches(text, query):
    norm_text = normalize(text)
    norm_query = normalize(query)

    matches = []

    for i in range(len(norm_text)):
        window = norm_text[i:i+len(norm_query)+10]
        score = fuzz.partial_ratio(norm_query, window)

        if score > 80:
            matches.append(i)

    return matches
