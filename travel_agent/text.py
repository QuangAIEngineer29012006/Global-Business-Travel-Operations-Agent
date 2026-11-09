import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text
                     if unicodedata.category(c) != "Mn")).split())
