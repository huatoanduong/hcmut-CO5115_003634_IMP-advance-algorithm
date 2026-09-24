"""Simple, fast Vietnamese address parser (standard library only).

Idea:
  1. Fold the input to lowercase ASCII (drop tone marks), split it into tokens,
     and glue the tokens into one compact string, e.g. "TỉnhQuảng Nam" -> "tinhquangnam".
  2. Addresses are written ward -> district -> province, so read from the RIGHT:
     match the province at the end, cut it off, drop prefixes like "tinh"/"tp",
     then match the district, then the ward.
  3. Each level has a Trie of REVERSED names, so "match a name ending here"
     is a plain walk. Try exact first; if that fails, run a Trie-guided
     edit-distance search that visits only names within 1-2 typos.
"""
import re
import unicodedata

MAX_TYPOS = 2

# Administrative prefix words that may sit just before a name (single or multi-token).
# Longer phrases first so "t p" wins over "p".
PREFIXES = [
    ("thanh", "pho"), ("thi", "xa"), ("thi", "tran"), ("t", "pho"), ("t", "xa"),
    ("t", "p"), ("t", "x"), ("t", "t"),
    ("thanhpho",), ("thixa",), ("thitran",), ("tinh",), ("huyen",), ("quan",), ("phuong",),
    ("xa",), ("tp",), ("tx",), ("tt",), ("t",), ("h",), ("q",), ("p",), ("f",), ("x",),
]
STRAY_DIGIT_RE = re.compile(r"(?<=[^\W\d_])\d(?=[^\W\d_])")  # "Sơ6n" -> "Sơn"
EMPTY_FIELD_RE = re.compile(r",[\s.]*,")                     # ",," marks a missing level
# Pure-number names (Phường 3, Quận 10) only count right after one of these tokens.
NUMBER_PREFIXES = {"district": {"q", "quan"}, "ward": {"p", "f", "phuong"}}
ALIASES = {"province": {"hcm": "Hồ Chí Minh", "hcminh": "Hồ Chí Minh", "tphcm": "Hồ Chí Minh",
                        "hn": "Hà Nội", "brvt": "Bà Rịa - Vũng Tàu", "tth": "Thừa Thiên Huế"}}


def _build_fold_table():
    table = {}
    for cp in list(range(0xC0, 0x250)) + list(range(0x1E00, 0x1F00)):
        base = unicodedata.normalize("NFD", chr(cp))[0]
        if base.isascii() and base.isalpha():
            table[cp] = base
    table[ord("đ")], table[ord("Đ")] = "d", "D"
    for cp in range(0x300, 0x370):  # stray combining marks
        table[cp] = None
    return table


FOLD = _build_fold_table()
TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def fold(text):
    """Lowercase ASCII without tone marks, spaces or punctuation."""
    return "".join(TOKEN_RE.findall(unicodedata.normalize("NFC", text).translate(FOLD))).lower()


def allowed_typos(length):
    return 0 if length <= 3 else 1 if length <= 7 else 2


class Trie:
    """Trie over reversed folded names; a terminal node keeps the canonical names."""

    def __init__(self):
        self.root = {}

    def add(self, key, name):
        node = self.root
        for ch in reversed(key):
            node = node.setdefault(ch, {})
        names = node.setdefault("$", [])
        if name not in names:
            names.append(name)

    def exact(self, text, end):
        """Longest name that ends exactly at text[end]. Returns (names, start) or None."""
        node, best = self.root, None
        for i in range(end - 1, -1, -1):
            node = node.get(text[i])
            if node is None:
                break
            if "$" in node:
                best = (node["$"], i)
        return best

    def fuzzy(self, text, end):
        """Best name ending at text[end] within allowed typos (banded Levenshtein on the Trie).
        Returns (names, start, typos) or None."""
        k = MAX_TYPOS
        q = text[max(0, end - 20):end][::-1]  # reversed text, read right-to-left
        n = len(q)
        inf = k + 1
        width = 2 * k + 1
        # band[t] = distance(name prefix of length d, q[:d - k + t])
        first = [j if 0 <= j <= n else inf for j in range(-k, k + 1)]
        best = None
        stack = [(self.root, 0, first)]
        while stack:
            node, d, band = stack.pop()
            for ch, child in node.items():
                if ch == "$":
                    continue
                d1 = d + 1
                new = [inf] * width
                for t in range(width):
                    j = d1 - k + t
                    if j < 0 or j > n:
                        continue
                    if j == 0:
                        new[t] = d1
                        continue
                    v = band[t] + (q[j - 1] != ch)            # substitute / match
                    if t + 1 < width and band[t + 1] + 1 < v:  # extra char in name
                        v = band[t + 1] + 1
                    if t > 0 and new[t - 1] + 1 < v:           # extra char in text
                        v = new[t - 1] + 1
                    new[t] = v if v < inf else inf
                low = min(new)
                if low > k:
                    continue
                if "$" in child and low <= allowed_typos(d1):
                    j = d1 - k + new.index(low)
                    score = (low, -d1)
                    if best is None or score < best[0]:
                        best = (score, child["$"], end - j, low)
                stack.append((child, d1, new))
        return None if best is None else best[1:]


class Solution:
    def __init__(self):
        # list provice, district, ward for private test, do not change for any reason
        self.province_path = "list_province.txt"
        self.district_path = "list_district.txt"
        self.ward_path = "list_ward.txt"

        self.tries = {}
        self.number_names = {}
        for level, path in (("province", self.province_path), ("district", self.district_path),
                            ("ward", self.ward_path)):
            trie, numbers = Trie(), {}
            with open(path, encoding="utf-8") as f:
                for line in f:
                    name = " ".join(line.split())
                    key = fold(name)
                    if not key:
                        continue
                    if key.isdigit():
                        numbers[str(int(key))] = numbers.get(str(int(key)), name)
                    else:
                        trie.add(key, name)
            for alias, name in ALIASES.get(level, {}).items():
                trie.add(alias, name)
            self.tries[level] = trie
            self.number_names[level] = numbers

    def process(self, s: str):
        text = STRAY_DIGIT_RE.sub("", unicodedata.normalize("NFC", s))
        folded = text.translate(FOLD)
        empty_marks = [m.end() for m in EMPTY_FIELD_RE.finditer(text)]
        tokens, accented, starts, empty_at = [], [], [], set()
        pos = 0
        for m in TOKEN_RE.finditer(folded):
            while empty_marks and empty_marks[0] <= m.start():
                empty_at.add(pos)  # compact position right after a ",,"
                empty_marks.pop(0)
            starts.append(pos)
            tokens.append(m.group().lower())
            accented.append(text[m.start():m.end()].lower())
            pos += m.end() - m.start()
        compact = "".join(tokens)
        accented = "".join(accented)

        result = {"province": "", "district": "", "ward": ""}
        end = len(compact)
        for level in ("province", "district", "ward"):
            stripped = self._strip_prefixes(compact, starts, end)
            if stripped in empty_at and level != "province":
                empty_at.discard(stripped)  # this level was left blank: ", ,"
                end = stripped
                continue
            # A prefix word can also end a real name ("Nho Quan"), so try the raw tail first.
            hit = (self._match(level, compact, accented, starts, end, fuzzy=False)
                   or self._match(level, compact, accented, starts, stripped))
            if hit is None and stripped > 0:
                # Retry once without a short junk token at the tail ("Tân7", "Hhi").
                tok = self._token_start(starts, stripped)
                if stripped - tok <= 2 or compact[tok:stripped].isdigit():
                    hit = self._match(level, compact, accented, starts, tok)
            if hit:
                result[level], end = hit
        return result

    # --- helpers -------------------------------------------------------------

    def _match(self, level, compact, accented, starts, end, fuzzy=True):
        if end <= 0:
            return None
        # "Phường 3", "Quận 10": a number right after its prefix token.
        numbers = self.number_names.get(level)
        if numbers:
            tok_start = self._token_start(starts, end)
            num = compact[tok_start:end]
            if num.isdigit() and str(int(num)) in numbers:
                prev = compact[self._token_start(starts, tok_start):tok_start]
                if prev in NUMBER_PREFIXES[level]:
                    return numbers[str(int(num))], tok_start

        trie = self.tries[level]
        hit = trie.exact(compact, end)
        if hit:
            names, start = hit
            return self._pick(names, accented[start:end]), start
        if not fuzzy:
            return None

        hit = trie.fuzzy(compact, end)
        if hit is None:
            return None
        names, start, typos = hit
        # A typo match must not steal an exact name from a lower level.
        for lower in ("district", "ward")[("province", "district", "ward").index(level):]:
            if lower != level:
                exact_lower = self.tries[lower].exact(compact, end)
                if exact_lower and end - exact_lower[1] >= end - start - typos:
                    return None
        return self._pick(names, accented[start:end]), start

    @staticmethod
    def _pick(names, accented_span):
        """Several names share the same tone-free spelling: keep the one closest to the input's marks."""
        if len(names) == 1:
            return names[0]
        span = set(accented_span)
        return max(names, key=lambda n: len(span & set(n.lower().replace(" ", ""))))

    @staticmethod
    def _token_start(starts, end):
        # Start of the token that contains position end - 1.
        lo, hi = 0, len(starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] < end:
                lo = mid + 1
            else:
                hi = mid
        return starts[lo - 1] if lo else 0

    def _strip_prefixes(self, compact, starts, end):
        """Drop prefix tokens ("tinh", "thanh pho", "h", ...) that precede the matched name."""
        changed = True
        while changed and end > 0:
            changed = False
            for phrase in PREFIXES:
                pos, ok = end, True
                for word in reversed(phrase):
                    st = self._token_start(starts, pos)
                    if compact[st:pos] != word:
                        ok = False
                        break
                    pos = st
                if ok:
                    end, changed = pos, True
                    break
        return end
