"""Load BrowseSafe++ (Perplexity, Oct 2026) and split it into train/test.

The public download is only BrowseSafe++'s train split (29,500 attack/clean
pairs; their test split is kept for their leaderboard). So we cut our own
test set out of it, the same way the authors built theirs:
  * an attacked page and its clean twin always land on the same side
  * the same injection text never appears on both sides (we group pairs by
    their normalised injection text before splitting)
  * the split is fixed by a hash, so every teammate and every model gets the
    same 80% / 20%

Needs:  pip install "browsesafe-pp[eval] @ git+https://github.com/perplexityai/browsesafe-plus-plus.git"
Data:   downloads from Hugging Face on first use (CC BY 4.0), or pass a local folder.
"""

from __future__ import annotations

import hashlib
import json
import re

HIDDEN_PLACEMENTS = {"html_comment", "data_attribute", "hidden_text", "form_hidden_field",
                     "alt_text_and_aria", "structured_data_block", "link_text_href_mismatch"}


def _group_key(pair) -> str:
    frags = json.loads(pair.metadata.get("injection_text_fragments_json") or "[]") or list(pair.malicious.evidence)
    return re.sub(r"\s+", " ", " ".join(frags)).strip().lower() or pair.malicious.metadata.get("entry_id", "")


def side(pair, test_share: float = 0.2) -> str:
    """'train' or 'test' for one pair; stable across machines and runs."""
    h = int(hashlib.sha256(_group_key(pair).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < test_share else "train"


def load(view: str = "markdown", source: str | None = None, n_pairs: int | None = None):
    """Returns (train_pairs, test_pairs). view: 'markdown' (short, good for models) or 'html' (for the scanner)."""
    import browsesafe_pp as bs
    kw = {"split": "train", "view": view}
    if source:
        kw["source"] = source
    if n_pairs:
        kw["n_pairs"] = n_pairs
    pairs = bs.load(**kw).pairs
    train = [p for p in pairs if side(p) == "train"]
    test = [p for p in pairs if side(p) == "test"]
    return train, test


def placement(pair) -> str:
    return pair.metadata.get("injection_strategy") or pair.malicious.metadata.get("injection_strategy") or "unknown"


def is_hidden(pair) -> bool:
    return placement(pair) in HIDDEN_PLACEMENTS


def rows(pairs):
    """Flatten pairs to (text, label) for training: 1 = attacked page, 0 = its clean twin."""
    X, y = [], []
    for p in pairs:
        X += [p.malicious.content, p.benign.content]
        y += [1, 0]
    return X, y


# --- Transformer training rows: windows that actually contain the attack -------------------
# Whole pages are ~1,800 tokens, so a model that reads 512 never sees the attack in most of
# them. These helpers cut a 256-384 token window around the attack, plus the matching piece of
# the clean twin, so the only difference between the two rows is the attack itself.

def _page_key(pair) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", pair.benign.content).strip().lower().encode()).hexdigest()[:16]


def trainval_split(pairs, val_share: float = 0.15):
    """Split (training-side) pairs into train/validation. Pairs that share a clean page or an
    injection text always land on the same side (union-find over both keys); fixed by hash."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        parent[find("p:" + _page_key(p))] = find("a:" + _group_key(p))
    groups = {}
    for p in pairs:
        groups.setdefault(find("p:" + _page_key(p)), []).append(p)
    train, val = [], []
    for members in groups.values():
        canon = min("p:" + _page_key(p) for p in members)
        h = int(hashlib.sha256(("val|" + canon).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        (val if h < val_share else train).extend(members)
    return train, val, max(len(m) for m in groups.values())


def _line_starts(lines):
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    return starts


def locate_attack(pair):
    """Every piece of the attack in pair.malicious.content.

    Returns (primary, mask, how). `primary` are the spans the window is built around: the
    evidence quotes ('evidence', when every quote that isn't also on the clean page appears
    verbatim) or the lines that differ from the clean twin ('diff'). `mask` is every span that
    belongs to the attack by either method, so no attack piece is used as surrounding text.
    how is None when the two pages show no difference (the pair can't be represented)."""
    import difflib
    m, b = pair.malicious.content, pair.benign.content
    ev, missing = [], 0
    for e in {x.strip() for x in pair.malicious.evidence if x.strip()}:
        if e in b:                      # quoted text that is also on the clean page isn't the attack
            continue
        i = m.find(e)
        if i < 0:
            missing += 1
        while i >= 0:
            ev.append((i, i + len(e)))
            i = m.find(e, i + 1)
    ml, bl = m.splitlines(keepends=True), b.splitlines(keepends=True)
    starts = _line_starts(ml)
    ops = difflib.SequenceMatcher(None, ml, bl, autojunk=False).get_opcodes()
    diff = [(starts[i1], starts[i2]) for tag, i1, i2, _, _ in ops if tag in ("replace", "delete") and i2 > i1]
    diff = [(s, e) for s, e in diff if m[s:e].strip()]
    mask = sorted(set(ev + diff))
    if ev and not missing:
        return sorted(ev), mask, "evidence"
    if diff:
        return diff, mask, "diff"
    return [], [], None


def _nearest(hay: str, needle: str, near: int, start: int = 0) -> int:
    best, i = -1, hay.find(needle, start)
    while i >= 0:
        if best < 0 or abs(i - near) < abs(best - near):
            best = i
        i = hay.find(needle, i + 1)
    return best


def _line_mapper(m: str, b: str):
    """Map a character position in the attacked page to the same place in the clean page,
    using a line-by-line comparison of the two pages."""
    import bisect
    import difflib
    ml, bl = m.splitlines(keepends=True), b.splitlines(keepends=True)
    ms, bs = _line_starts(ml), _line_starts(bl)
    ops = difflib.SequenceMatcher(None, ml, bl, autojunk=False).get_opcodes()

    def to_clean(c: int, end: bool = False) -> int:
        li = max(0, bisect.bisect_right(ms, c) - 1)
        for tag, i1, i2, j1, j2 in ops:
            if i1 <= li < i2:
                if tag == "equal":
                    return min(bs[j1 + li - i1] + c - ms[li], len(b))
                return bs[j2] if end else bs[j1]
        return len(b)
    return to_clean


def transformer_windows(pairs, tok, seed: int = 0, clean_chunks: int = 0, lo: int = 256, hi: int = 384):
    """Rows for transformer training/validation from BrowseSafe++ pairs.

    For each pair: one window of lo..hi tokens from the attacked page with the attack at a random
    position inside (label 1), and the same stretch of the clean twin (label 0). The twin is found
    by matching the text right before and after the attack, using only text that isn't part of
    any attack piece ("exact"); if that fails, by a line-by-line comparison of the two pages
    ("fallback"). Plus `clean_chunks` random windows from clean pages (label 0).
    Returns (rows, stats, per_pair) where per_pair maps pair_id -> 'exact' | 'fallback' | reason."""
    import bisect
    import random
    from collections import Counter
    rng = random.Random(seed)
    stats, rows_out, per_pair = Counter(), [], {}
    for p in pairs:
        primary, mask, how = locate_attack(p)
        stats[f"located by {how or 'nothing (identical pages)'}"] += 1
        if not primary:
            per_pair[p.pair_id] = "unrepresented: no visible difference"
            continue
        m, b = p.malicious.content, p.benign.content
        off = tok(m, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
        ends = [e for _, e in off]
        n, L = len(off), rng.randint(lo, hi)
        tok_of = lambda c: min(bisect.bisect_right(ends, c), n - 1)  # noqa: E731
        s, e = primary[0]
        for s2, e2 in primary[1:]:          # widen over later pieces while they still fit
            if tok_of(e2) - tok_of(s) < L - 32:
                e = max(e, e2)
        ts, te = tok_of(s), tok_of(max(s, e - 1)) + 1
        if te - ts > L - 32:
            per_pair[p.pair_id] = "unrepresented: attack longer than a window"
            continue
        a0 = 0 if n <= L else rng.randint(max(0, te - L), min(ts, n - L))
        a1 = min(n, a0 + L)
        ws, we = off[a0][0], off[a1 - 1][1]
        pre, post = m[ws:s], m[e:we]
        # anchors use only text between attack pieces, never the pieces themselves
        pre_from = max([ws] + [me for ms_, me in mask if me <= s])
        post_to = min([we] + [ms_ for ms_, me in mask if ms_ >= e])
        anc_pre, anc_post = m[max(pre_from, s - 200):s], m[e:min(post_to, e + 200)]
        twin, method = None, None
        if (len(anc_pre.strip()) >= 30 or not pre.strip()) and (len(anc_post.strip()) >= 30 or not post.strip()):
            pre_end = _nearest(b, anc_pre, s - len(anc_pre)) + len(anc_pre) if pre.strip() else None
            post_start = _nearest(b, anc_post, pre_end if pre_end is not None else s) if post.strip() else None
            ok_pre = pre_end is None or pre_end >= len(anc_pre)
            ok_post = post_start is None or post_start >= 0
            if ok_pre and ok_post:
                cs = (pre_end - len(pre)) if pre_end is not None else post_start
                ce = (post_start + len(post)) if post_start is not None else pre_end
                if 0 <= cs < ce and (post_start is None or pre_end is None or post_start >= pre_end - 1):
                    twin, method = b[cs:ce], "exact"
        if twin is None:
            to_clean = _line_mapper(m, b)
            cs, ce = to_clean(ws), to_clean(we, end=True)
            if ce > cs and ce - cs <= 2 * (we - ws) + 200:
                twin, method = b[cs:ce], "fallback"
        pieces = [m[x:y].strip() for x, y in mask if len(m[x:y].strip()) >= 15]
        if twin is not None and (len(twin.strip()) < 50 or any(pc in twin for pc in pieces)):
            twin = None
        if twin is None:
            per_pair[p.pair_id] = "unrepresented: clean twin not found"
            continue
        per_pair[p.pair_id] = method
        meta = {"pair_id": p.pair_id, "placement": placement(p),
                "language": str(p.metadata.get("language_payload") or "unknown")}
        rows_out += [{"text": m[ws:we], "label": 1, "kind": "attack", "twin_by": method, **meta},
                     {"text": twin, "label": 0, "kind": "twin", "twin_by": method, **meta}]
    stats.update(Counter(per_pair.values()))
    for p in rng.sample(list(pairs), min(clean_chunks, len(pairs))):
        b = p.benign.content
        off = tok(b, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
        L = rng.randint(lo, hi)
        a0 = rng.randint(0, max(0, len(off) - L))
        chunk = off[a0:a0 + L]
        if chunk:
            rows_out.append({"text": b[chunk[0][0]:chunk[-1][1]], "label": 0, "kind": "clean_chunk",
                             "pair_id": p.pair_id, "placement": placement(p), "language": "n/a"})
            stats["random clean chunks"] += 1
    return rows_out, stats, per_pair


HIDDEN_TEXT_PLACEMENTS = {"html_comment", "form_hidden_field", "data_attribute", "hidden_text", "alt_text_and_aria"}


def hidden_passages(pairs, html_by_id: dict, min_words: int = 5):
    """What the product sends to the model for hidden-text attacks: run parallax/gap/html_gap.py on
    the HTML of both pages. Passages hidden only on the attacked page -> label 1; hidden passages
    on both pages -> label 0. Returns (rows, stats); stats include the finder's hit rate (pairs
    where an attacked-only passage contains a piece of the evidence)."""
    import sys
    from collections import Counter
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from parallax.gap.html_gap import analyze_html
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()  # noqa: E731
    stats, rows_out = Counter(), []
    for p in pairs:
        if placement(p) not in HIDDEN_TEXT_PLACEMENTS:
            continue
        hp = html_by_id.get(p.pair_id)
        stats["hidden-text pairs"] += 1
        if hp is None:
            stats["no HTML view"] += 1
            continue
        mal = {norm(s.text): s.text for s in analyze_html(hp.malicious.content)["hidden"]}
        ben = {norm(s.text) for s in analyze_html(hp.benign.content)["hidden"]}
        only = [t for k, t in mal.items() if k not in ben and len(t.split()) >= min_words]
        both = [t for k, t in mal.items() if k in ben and len(t.split()) >= min_words]
        ev = [norm(x) for x in p.malicious.evidence if len(x.split()) >= 3]
        hit = any(any(e[:60] in norm(t) or norm(t) in e for e in ev) for t in only)
        stats[f"finder hit ({placement(p)})" if hit else f"finder miss ({placement(p)})"] += 1
        meta = {"pair_id": p.pair_id, "placement": placement(p),
                "language": str(p.metadata.get("language_payload") or "unknown")}
        rows_out += [{"text": t[:3000], "label": 1, "kind": "hidden_attack", **meta} for t in only]
        rows_out += [{"text": t[:3000], "label": 0, "kind": "hidden_clean", **meta} for t in both]
    stats["hidden attack passages"] = sum(r["label"] for r in rows_out)
    stats["hidden clean passages"] = sum(1 - r["label"] for r in rows_out)
    return rows_out, stats
