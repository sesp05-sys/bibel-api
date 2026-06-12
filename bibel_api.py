#!/usr/bin/env python3
"""Standalone Bible API — KJV and Norwegian 1930 verse lookup.

Can be run as a standalone Flask app or imported as a Blueprint.

Usage as standalone:
    python bibel_api.py              # Runs on port 5002

Usage as Blueprint:
    from bibel_api import create_bible_blueprint
    app.register_blueprint(create_bible_blueprint(), url_prefix="/bible")
"""

import json
import os
import re

from flask import Blueprint, Flask, request, jsonify, Response

# ---------------------------------------------------------------------------
# Data directory (default: ./data/ next to this file)
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("BIBLE_DATA_DIR", os.path.join(_BASE_DIR, "data"))

# ---------------------------------------------------------------------------
# Lazy-loaded caches
# ---------------------------------------------------------------------------
_kjv = None
_nor = None
_versification_map = None
_red_letter = None


def _load_kjv():
    global _kjv
    if _kjv is None:
        path = os.environ.get("KJV_PATH", os.path.join(_DATA_DIR, "kjv.json"))
        with open(path, "r", encoding="utf-8") as f:
            _kjv = json.load(f)
    return _kjv


def _load_red_letter():
    """Load KJV red-letter word-index mapping.

    Format: {book_name: {chapter: {verse: [[startWord, endWord], ...]}}}
    Word indices are 0-based, matching words extracted by re.findall(r'[a-zA-Z]+', text).
    """
    global _red_letter
    if _red_letter is None:
        path = os.path.join(_DATA_DIR, "kjv_red_letter.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _red_letter = json.load(f)
        else:
            _red_letter = {}
    return _red_letter


def _load_nor():
    global _nor
    if _nor is None:
        path = os.environ.get("NOR_BIBLE_PATH", os.path.join(_DATA_DIR, "nor1930.json"))
        with open(path, "r", encoding="utf-8") as f:
            _nor = json.load(f)
    return _nor


# ---------------------------------------------------------------------------
# Versification mapping (Norwegian 1930 ↔ KJV)
# ---------------------------------------------------------------------------

def _build_versification_map():
    """Parse parenthetical hints like '(41:10)' in Norwegian Bible to build
    a mapping from Norwegian verse addresses to KJV addresses."""
    global _versification_map
    if _versification_map is not None:
        return _versification_map

    nor = _load_nor()
    _versification_map = {}
    par_re = re.compile(r"^\((\d+):(\d+)\)")

    for book_code, book in nor["bible"].items():
        book_map = {}
        for ch_str, chapter in book.items():
            kjv_ch = int(ch_str)
            for v_str, text in chapter.items():
                kjv_v = int(v_str)
                m = par_re.match(text)
                if m:
                    nor_ch, nor_v = int(m.group(1)), int(m.group(2))
                    if nor_ch != kjv_ch or nor_v != kjv_v:
                        book_map[(nor_ch, nor_v)] = (kjv_ch, kjv_v)
        if book_map:
            _versification_map[book_code] = book_map

    return _versification_map


def _nor_addr_to_kjv(book_code, ch, v):
    """Convert a Norwegian (chapter, verse) to KJV address."""
    vmap = _build_versification_map()
    return vmap.get(book_code, {}).get((ch, v), (ch, v))


# ---------------------------------------------------------------------------
# Book ID ↔ code helpers
# ---------------------------------------------------------------------------

def _book_id_to_code(book_id):
    """Convert book_id (1-66) to JSON key: OT='01O'-'39O', NT='40N'-'66N'."""
    if 1 <= book_id <= 39:
        return f"{book_id:02d}O"
    elif 40 <= book_id <= 66:
        return f"{book_id:02d}N"
    return None


# ---------------------------------------------------------------------------
# Book name aliases → book_id (1-66)
# ---------------------------------------------------------------------------
# Norwegian aliases map to (book_id, canonical_norwegian_name)
# English aliases map to (book_id, canonical_english_name)

_BOOK_ALIASES_NO = {
    "1. mosebok": 1, "1 mosebok": 1, "1 mos": 1, "1mos": 1,
    "2. mosebok": 2, "2 mosebok": 2, "2 mos": 2, "2mos": 2,
    "3. mosebok": 3, "3 mosebok": 3, "3 mos": 3, "3mos": 3,
    "4. mosebok": 4, "4 mosebok": 4, "4 mos": 4, "4mos": 4,
    "5. mosebok": 5, "5 mosebok": 5, "5 mos": 5, "5mos": 5,
    "josva": 6, "jos": 6,
    "dommerne": 7, "dom": 7,
    "rut": 8, "ruts bok": 8,
    "1. samuelsbok": 9, "1 samuel": 9, "1 sam": 9, "1sam": 9, "1. samuel": 9,
    "2. samuelsbok": 10, "2 samuel": 10, "2 sam": 10, "2sam": 10, "2. samuel": 10,
    "1. kongebok": 11, "1 kongebok": 11, "1 kong": 11, "1kong": 11,
    "2. kongebok": 12, "2 kongebok": 12, "2 kong": 12, "2kong": 12,
    "1. krønikebok": 13, "1 krøn": 13, "1krøn": 13,
    "2. krønikebok": 14, "2 krøn": 14, "2krøn": 14,
    "esra": 15,
    "nehemja": 16, "neh": 16,
    "ester": 17, "est": 17, "esters bok": 17,
    "job": 18, "jobs bok": 18,
    "salmene": 19, "salme": 19, "sal": 19, "salmenes bok": 19,
    "ordspråkene": 20, "ordsp": 20, "ord": 20, "salomos ordspråk": 20,
    "forkynneren": 21, "fork": 21,
    "høysangen": 22, "høys": 22,
    "jesaja": 23, "jes": 23, "esaias": 23,
    "jeremia": 24, "jer": 24, "jeremias": 24,
    "klagesangene": 25, "klag": 25,
    "esekiel": 26, "esek": 26,
    "daniel": 27, "dan": 27,
    "hosea": 28, "hos": 28,
    "joel": 29,
    "amos": 30, "am": 30,
    "obadja": 31, "obad": 31,
    "jona": 32, "jonas": 32,
    "mika": 33, "mi": 33,
    "nahum": 34, "nah": 34,
    "habakkuk": 35, "hab": 35,
    "sefanja": 36, "sef": 36,
    "haggai": 37, "hag": 37,
    "sakarja": 38, "sak": 38,
    "malaki": 39, "mal": 39, "malakias": 39,
    "matteus": 40, "matt": 40, "mat": 40,
    "markus": 41, "mark": 41, "mk": 41,
    "lukas": 42, "luk": 42,
    "johannes": 43, "joh": 43,
    "apostlenes gjerninger": 44, "apg": 44,
    "romerne": 45, "rom": 45, "romerbrevet": 45,
    "1. korinterbrev": 46, "1 korinterbrev": 46, "1 kor": 46, "1kor": 46,
    "2. korinterbrev": 47, "2 korinterbrev": 47, "2 kor": 47, "2kor": 47,
    "galaterne": 48, "gal": 48,
    "efeserne": 49, "ef": 49, "efeserbrevet": 49,
    "filipperne": 50, "fil": 50,
    "kolosserne": 51, "kol": 51, "kolossenserne": 51,
    "1. tessalonikerbrev": 52, "1 tessalonikerbrev": 52, "1 tess": 52, "1tess": 52,
    "1 tessalonikerne": 52, "1. tessalonikerne": 52,
    "2. tessalonikerbrev": 53, "2 tessalonikerbrev": 53, "2 tess": 53, "2tess": 53,
    "2 tessalonikerne": 53, "2. tessalonikerne": 53,
    "1. timoteus": 54, "1 timoteus": 54, "1 tim": 54, "1tim": 54,
    "2. timoteus": 55, "2 timoteus": 55, "2 tim": 55, "2tim": 55,
    "titus": 56, "tit": 56,
    "filemon": 57, "filem": 57,
    "hebreerne": 58, "hebr": 58, "heb": 58, "hebreerbrevet": 58,
    "jakob": 59, "jak": 59, "jakobs brev": 59,
    "1. peter": 60, "1 peter": 60, "1 pet": 60, "1pet": 60,
    "2. peter": 61, "2 peter": 61, "2 pet": 61, "2pet": 61, "2 peters brev": 61,
    "1. johannes": 62, "1 johannes": 62, "1 joh": 62, "1joh": 62, "1. johannesbrev": 62,
    "2. johannes": 63, "2 johannes": 63, "2 joh": 63, "2joh": 63,
    "3. johannes": 64, "3 johannes": 64, "3 joh": 64, "3joh": 64, "3. johannesbrev": 64,
    "judas": 65, "jud": 65, "judas brev": 65,
    "åpenbaringen": 66, "åp": 66,
}

_BOOK_ALIASES_EN = {
    "genesis": 1, "gen": 1,
    "exodus": 2, "ex": 2, "exod": 2,
    "leviticus": 3, "lev": 3,
    "numbers": 4, "num": 4,
    "deuteronomy": 5, "deut": 5, "dt": 5,
    "joshua": 6, "josh": 6,
    "judges": 7, "judg": 7,
    "ruth": 8,
    "1 samuel": 9, "1samuel": 9, "1sam": 9, "1 sam": 9,
    "2 samuel": 10, "2samuel": 10, "2sam": 10, "2 sam": 10,
    "1 kings": 11, "1kings": 11, "1 kgs": 11,
    "2 kings": 12, "2kings": 12, "2 kgs": 12,
    "1 chronicles": 13, "1chr": 13, "1 chr": 13,
    "2 chronicles": 14, "2chr": 14, "2 chr": 14,
    "ezra": 15,
    "nehemiah": 16, "neh": 16,
    "esther": 17, "esth": 17,
    "job": 18,
    "psalms": 19, "psalm": 19, "ps": 19, "psa": 19,
    "proverbs": 20, "prov": 20,
    "ecclesiastes": 21, "eccl": 21, "ecc": 21,
    "song of solomon": 22, "song": 22, "sos": 22,
    "isaiah": 23, "isa": 23,
    "jeremiah": 24, "jer": 24,
    "lamentations": 25, "lam": 25,
    "ezekiel": 26, "ezek": 26,
    "daniel": 27, "dan": 27,
    "hosea": 28, "hos": 28,
    "joel": 29,
    "amos": 30,
    "obadiah": 31, "obad": 31,
    "jonah": 32, "jon": 32,
    "micah": 33, "mic": 33,
    "nahum": 34, "nah": 34,
    "habakkuk": 35, "hab": 35,
    "zephaniah": 36, "zeph": 36,
    "haggai": 37, "hag": 37,
    "zechariah": 38, "zech": 38,
    "malachi": 39, "mal": 39,
    "matthew": 40, "matt": 40, "mt": 40,
    "mark": 41, "mk": 41,
    "luke": 42, "lk": 42,
    "john": 43, "jn": 43,
    "acts": 44,
    "romans": 45, "rom": 45,
    "1 corinthians": 46, "1cor": 46, "1 cor": 46,
    "2 corinthians": 47, "2cor": 47, "2 cor": 47,
    "galatians": 48, "gal": 48,
    "ephesians": 49, "eph": 49,
    "philippians": 50, "phil": 50,
    "colossians": 51, "col": 51,
    "1 thessalonians": 52, "1thess": 52, "1 thess": 52,
    "2 thessalonians": 53, "2thess": 53, "2 thess": 53,
    "1 timothy": 54, "1tim": 54, "1 tim": 54,
    "2 timothy": 55, "2tim": 55, "2 tim": 55,
    "titus": 56, "tit": 56,
    "philemon": 57, "philem": 57, "phlm": 57,
    "hebrews": 58, "heb": 58,
    "james": 59, "jas": 59,
    "1 peter": 60, "1pet": 60, "1 pet": 60, "1peter": 60,
    "2 peter": 61, "2pet": 61, "2 pet": 61, "2peter": 61,
    "1 john": 62, "1john": 62, "1 jn": 62,
    "2 john": 63, "2john": 63, "2 jn": 63,
    "3 john": 64, "3john": 64, "3 jn": 64,
    "jude": 65,
    "revelation": 66, "rev": 66,
}

# Merged dict for lookup (Norwegian takes priority, then English)
_ALL_ALIASES = {}
_ALL_ALIASES.update(_BOOK_ALIASES_EN)
_ALL_ALIASES.update(_BOOK_ALIASES_NO)

# Sorted by length descending for matching (longest first avoids partial matches)
_SORTED_ALIAS_KEYS = sorted(_ALL_ALIASES.keys(), key=lambda x: -len(x))

# Canonical names per book_id
_CANONICAL_NAMES = {
    1: ("1. Mosebok", "Genesis"), 2: ("2. Mosebok", "Exodus"),
    3: ("3. Mosebok", "Leviticus"), 4: ("4. Mosebok", "Numbers"),
    5: ("5. Mosebok", "Deuteronomy"), 6: ("Josva", "Joshua"),
    7: ("Dommerne", "Judges"), 8: ("Rut", "Ruth"),
    9: ("1. Samuelsbok", "1 Samuel"), 10: ("2. Samuelsbok", "2 Samuel"),
    11: ("1. Kongebok", "1 Kings"), 12: ("2. Kongebok", "2 Kings"),
    13: ("1. Krønikebok", "1 Chronicles"), 14: ("2. Krønikebok", "2 Chronicles"),
    15: ("Esra", "Ezra"), 16: ("Nehemja", "Nehemiah"),
    17: ("Ester", "Esther"), 18: ("Job", "Job"),
    19: ("Salmene", "Psalms"), 20: ("Ordspråkene", "Proverbs"),
    21: ("Forkynneren", "Ecclesiastes"), 22: ("Høysangen", "Song of Solomon"),
    23: ("Jesaja", "Isaiah"), 24: ("Jeremia", "Jeremiah"),
    25: ("Klagesangene", "Lamentations"), 26: ("Esekiel", "Ezekiel"),
    27: ("Daniel", "Daniel"), 28: ("Hosea", "Hosea"),
    29: ("Joel", "Joel"), 30: ("Amos", "Amos"),
    31: ("Obadja", "Obadiah"), 32: ("Jona", "Jonah"),
    33: ("Mika", "Micah"), 34: ("Nahum", "Nahum"),
    35: ("Habakkuk", "Habakkuk"), 36: ("Sefanja", "Zephaniah"),
    37: ("Haggai", "Haggai"), 38: ("Sakarja", "Zechariah"),
    39: ("Malaki", "Malachi"), 40: ("Matteus", "Matthew"),
    41: ("Markus", "Mark"), 42: ("Lukas", "Luke"),
    43: ("Johannes", "John"), 44: ("Apostlenes gjerninger", "Acts"),
    45: ("Romerne", "Romans"), 46: ("1. Korinterbrev", "1 Corinthians"),
    47: ("2. Korinterbrev", "2 Corinthians"), 48: ("Galaterne", "Galatians"),
    49: ("Efeserne", "Ephesians"), 50: ("Filipperne", "Philippians"),
    51: ("Kolosserne", "Colossians"), 52: ("1. Tessalonikerbrev", "1 Thessalonians"),
    53: ("2. Tessalonikerbrev", "2 Thessalonians"), 54: ("1. Timoteus", "1 Timothy"),
    55: ("2. Timoteus", "2 Timothy"), 56: ("Titus", "Titus"),
    57: ("Filemon", "Philemon"), 58: ("Hebreerne", "Hebrews"),
    59: ("Jakob", "James"), 60: ("1. Peter", "1 Peter"),
    61: ("2. Peter", "2 Peter"), 62: ("1. Johannes", "1 John"),
    63: ("2. Johannes", "2 John"), 64: ("3. Johannes", "3 John"),
    65: ("Judas", "Jude"), 66: ("Åpenbaringen", "Revelation"),
}


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------

def parse_reference(ref):
    """Parse a Bible reference string (Norwegian or English).

    Returns dict with keys: book_id, name_no, name_en, chapter, verse_start, verse_end
    or None if unparseable.

    Handles: "Joh 3:16", "John 3:16-18", "1 Kor 13:4-7", "Rev 21:1", "Sal 23"
    """
    if not ref:
        return None

    clean = ref.strip()
    lower = clean.lower()

    # Try to match a book name (longest first)
    book_id = None
    rest = None
    for alias in _SORTED_ALIAS_KEYS:
        if lower.startswith(alias):
            remainder = lower[len(alias):]
            if not remainder or remainder[0] in (" ", "\t", ":"):
                book_id = _ALL_ALIASES[alias]
                rest = remainder.strip()
                break

    if book_id is None:
        return None

    name_no, name_en = _CANONICAL_NAMES[book_id]

    if not rest:
        return None  # Just a book name

    # Parse chapter:verse patterns
    # "3:16", "3:16-18", "3,16", "3.16-18", "3" (chapter only)
    m = re.match(
        r"(\d+)\s*[:.,]\s*(\d+)(?:\s*[-–]\s*(\d+))?(?:\s*[,.]\s*(\d+)(?:\s*[-–]\s*(\d+))?)?",
        rest,
    )
    if m:
        chapter = int(m.group(1))
        v_start = int(m.group(2))
        if m.group(5):
            v_end = int(m.group(5))
        elif m.group(4):
            v_end = int(m.group(4))
        elif m.group(3):
            v_end = int(m.group(3))
        else:
            v_end = v_start
        return {
            "book_id": book_id, "name_no": name_no, "name_en": name_en,
            "chapter": chapter, "verse_start": v_start, "verse_end": v_end,
        }

    # Chapter only
    m = re.match(r"(\d+)$", rest)
    if m:
        return {
            "book_id": book_id, "name_no": name_no, "name_en": name_en,
            "chapter": int(m.group(1)), "verse_start": None, "verse_end": None,
        }

    return None


# ---------------------------------------------------------------------------
# Verse lookup functions
# ---------------------------------------------------------------------------

def lookup_verses(book_id, chapter, verse_start=None, verse_end=None, translation="both"):
    """Look up Bible verses.

    Args:
        book_id: 1-66
        chapter: chapter number
        verse_start: start verse (None = whole chapter)
        verse_end: end verse (None = same as start)
        translation: "kjv", "nor", or "both"

    Returns dict with keys: reference_no, reference_en, kjv_text, nor_text, verses
    """
    book_code = _book_id_to_code(book_id)
    if not book_code:
        return None

    name_no, name_en = _CANONICAL_NAMES.get(book_id, ("?", "?"))
    result = {
        "book_id": book_id,
        "book_no": name_no,
        "book_en": name_en,
        "chapter": chapter,
        "verse_start": verse_start,
        "verse_end": verse_end,
        "verses": [],
    }

    kjv = _load_kjv() if translation in ("kjv", "both") else None
    nor = _load_nor() if translation in ("nor", "both") else None

    # Determine verse range
    if verse_start is None:
        # Whole chapter — get max verse from whichever bible we have
        bible_data = kjv or nor
        ch_str = str(chapter)
        if book_code not in bible_data["bible"] or ch_str not in bible_data["bible"][book_code]:
            return None
        max_v = max(int(k) for k in bible_data["bible"][book_code][ch_str].keys())
        v_start, v_end = 1, max_v
    else:
        v_start = verse_start
        v_end = verse_end or verse_start

    par_re = re.compile(r"^\(\d+:\d+\)\s*")

    for v in range(v_start, v_end + 1):
        entry = {"verse": v}

        # KJV lookup (with versification mapping from Norwegian addresses)
        if kjv:
            kjv_ch, kjv_v = _nor_addr_to_kjv(book_code, chapter, v)
            ch_str = str(kjv_ch)
            v_str = str(kjv_v)
            if (book_code in kjv["bible"]
                    and ch_str in kjv["bible"][book_code]
                    and v_str in kjv["bible"][book_code][ch_str]):
                entry["kjv"] = kjv["bible"][book_code][ch_str][v_str]

        # Norwegian lookup
        if nor:
            ch_str = str(chapter)
            v_str = str(v)
            if (book_code in nor["bible"]
                    and ch_str in nor["bible"][book_code]
                    and v_str in nor["bible"][book_code][ch_str]):
                text = nor["bible"][book_code][ch_str][v_str]
                text = par_re.sub("", text)  # Strip versification hints
                entry["nor"] = text

        if "kjv" in entry or "nor" in entry:
            result["verses"].append(entry)

    # Build reference labels
    ref_suffix = f" {chapter}"
    if verse_start:
        ref_suffix += f":{verse_start}"
        if verse_end and verse_end != verse_start:
            ref_suffix += f"-{verse_end}"
    result["reference_no"] = name_no + ref_suffix
    result["reference_en"] = name_en + ref_suffix

    return result if result["verses"] else None


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

def create_bible_blueprint():
    """Create a Flask Blueprint for the Bible API."""
    bp = Blueprint("bible_api", __name__)

    @bp.after_request
    def after_request(response):
        # Sett CORS-headerne ÉN gang (headers[...] = overskriver; .add ville duplisert,
        # og nettlesere avviser doble Access-Control-Allow-Origin)
        if response.content_type and "application/json" in response.content_type:
            data = response.get_data(as_text=True)
            response = Response(data, content_type="application/json; charset=utf-8")
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @bp.route("/api/verse")
    def api_verse():
        """Look up a verse by reference string.

        Query params:
            ref: Bible reference, e.g. "Joh 3:16", "John 3:16-18", "Sal 23"
            lang: "kjv", "nor", or "both" (default: "both")

        Returns JSON:
            {book_no, book_en, chapter, verse_start, verse_end, reference_no, reference_en, verses: [{verse, kjv, nor}]}
        """
        ref = request.args.get("ref", "").strip()
        lang = request.args.get("lang", "both").lower()
        if lang not in ("kjv", "nor", "both"):
            lang = "both"

        if not ref:
            return jsonify({"error": "Missing 'ref' parameter. Example: /api/verse?ref=Joh+3:16"}), 400

        parsed = parse_reference(ref)
        if not parsed:
            return jsonify({"error": f"Could not parse reference: {ref}"}), 400

        result = lookup_verses(
            parsed["book_id"], parsed["chapter"],
            parsed["verse_start"], parsed["verse_end"],
            translation=lang,
        )
        if not result:
            return jsonify({"error": "Verses not found"}), 404

        return jsonify(result)

    @bp.route("/api/books")
    def api_books():
        """List all Bible books with IDs and names."""
        books = []
        for bid in range(1, 67):
            name_no, name_en = _CANONICAL_NAMES[bid]
            books.append({"id": bid, "name_no": name_no, "name_en": name_en})
        return jsonify(books)

    @bp.route("/api/chapters/<int:book_id>")
    def api_chapters(book_id):
        """List chapters in a book."""
        code = _book_id_to_code(book_id)
        if not code:
            return jsonify({"error": "Invalid book_id (1-66)"}), 400

        kjv = _load_kjv()
        if code not in kjv["bible"]:
            return jsonify({"error": "Book not found"}), 404

        chapters = []
        for ch_str in sorted(kjv["bible"][code].keys(), key=int):
            verse_count = len(kjv["bible"][code][ch_str])
            chapters.append({"chapter": int(ch_str), "verses": verse_count})

        name_no, name_en = _CANONICAL_NAMES.get(book_id, ("?", "?"))
        return jsonify({"book_id": book_id, "name_no": name_no, "name_en": name_en, "chapters": chapters})

    @bp.route("/api/search")
    def api_search():
        """Search for text across both translations.

        Query params:
            q: search text
            lang: "kjv", "nor", or "both" (default: "both")
            limit: max results (default: 50)
        """
        query = request.args.get("q", "").strip()
        lang = request.args.get("lang", "both").lower()
        limit = min(int(request.args.get("limit", 50)), 200)

        if not query or len(query) < 2:
            return jsonify({"error": "Query too short (min 2 characters)"}), 400

        results = []
        q_lower = query.lower()
        par_re = re.compile(r"^\(\d+:\d+\)\s*")

        if lang in ("kjv", "both"):
            kjv = _load_kjv()
            for book_code in kjv["books"]:
                book = kjv["bible"].get(book_code, {})
                for ch_str, chapter in book.items():
                    for v_str, text in chapter.items():
                        if q_lower in text.lower():
                            bid = kjv["books"].index(book_code) + 1
                            name_no, name_en = _CANONICAL_NAMES.get(bid, ("?", "?"))
                            results.append({
                                "reference": f"{name_en} {ch_str}:{v_str}",
                                "book_id": bid, "chapter": int(ch_str), "verse": int(v_str),
                                "text": text, "lang": "kjv",
                            })
                            if len(results) >= limit:
                                break
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break

        if lang in ("nor", "both") and len(results) < limit:
            nor = _load_nor()
            for book_code in nor["books"]:
                book = nor["bible"].get(book_code, {})
                for ch_str, chapter in book.items():
                    for v_str, text in chapter.items():
                        clean_text = par_re.sub("", text)
                        if q_lower in clean_text.lower():
                            bid = nor["books"].index(book_code) + 1
                            name_no, name_en = _CANONICAL_NAMES.get(bid, ("?", "?"))
                            results.append({
                                "reference": f"{name_no} {ch_str}:{v_str}",
                                "book_id": bid, "chapter": int(ch_str), "verse": int(v_str),
                                "text": clean_text, "lang": "nor",
                            })
                            if len(results) >= limit:
                                break
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break

        return jsonify({"query": query, "count": len(results), "results": results})

    @bp.route("/api/redletter")
    def api_red_letter():
        """Get red-letter word ranges for a chapter or verse.

        Returns word-index ranges for Words of Jesus in KJV text.
        Word indices match re.findall(r'[a-zA-Z]+', verse_text).

        Query params:
            book: English book name (e.g. "Matthew", "1 Corinthians")
            chapter: chapter number (optional — returns all chapters if omitted)
            verse: verse number (optional — returns all verses in chapter if omitted)

        Response format:
            {chapter: {verse: [[startWordIdx, endWordIdx], ...]}}
        """
        rl = _load_red_letter()
        book = request.args.get("book", "").strip()
        chapter = request.args.get("chapter", "").strip()
        verse = request.args.get("verse", "").strip()

        if not book:
            # Return list of books that have red-letter data
            return jsonify({
                "books": [b for b in rl if any(rl[b].values())],
                "description": "KJV Red Letter — Words of Jesus word-index ranges",
            })

        book_data = rl.get(book, {})
        if not book_data:
            return jsonify({"error": f"No red-letter data for '{book}'"}), 404

        if chapter and verse:
            ranges = book_data.get(chapter, {}).get(verse)
            if not ranges:
                return jsonify({"book": book, "chapter": int(chapter), "verse": int(verse), "red_letter": False})
            return jsonify({"book": book, "chapter": int(chapter), "verse": int(verse), "red_letter": True, "ranges": ranges})

        if chapter:
            ch_data = book_data.get(chapter, {})
            return jsonify({"book": book, "chapter": int(chapter), "verses": ch_data})

        return jsonify({"book": book, "chapters": book_data})

    @bp.route("/api/redletter/full")
    def api_red_letter_full():
        """Return the complete red-letter mapping (for client-side caching)."""
        rl = _load_red_letter()
        return jsonify(rl)

    return bp


# ---------------------------------------------------------------------------
# Standalone app
# ---------------------------------------------------------------------------

def create_app():
    """Create standalone Flask app."""
    app = Flask(__name__)
    app.register_blueprint(create_bible_blueprint())

    @app.route("/")
    def index():
        return jsonify({
            "name": "Bibel API",
            "version": "1.0",
            "endpoints": {
                "/api/verse?ref=Joh+3:16": "Look up verse(s) by reference",
                "/api/verse?ref=Joh+3:16&lang=kjv": "KJV only",
                "/api/verse?ref=Sal+23&lang=nor": "Norwegian 1930 only",
                "/api/books": "List all books",
                "/api/chapters/43": "List chapters in a book",
                "/api/search?q=beginning": "Search verse text",
                "/api/redletter": "List books with red-letter data",
                "/api/redletter?book=Matthew&chapter=3": "Red-letter ranges for a chapter",
                "/api/redletter?book=John&chapter=3&verse=16": "Red-letter ranges for a verse",
                "/api/redletter/full": "Complete red-letter mapping (for caching)",
            },
        })

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=True)
