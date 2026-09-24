# Trie-Based Segmentation of Vietnamese Administrative Addresses: Technical Assessment

This assesses the three-Trie design described in the brief. "Implementation note" paragraphs record where the code in `pseudo-code/` departs from that design. They do not affect the verdict on the design.

## 1. Problem framing

The task is span labelling over a closed gazetteer, not open-vocabulary NER. Every output value comes from three finite lists, so the problem is to find which input substrings match gazetteer entries and at which level. An output is correct when each of the three fields equals the canonical gazetteer name after grouping known spelling variants (for example "Hoà"/"Hòa", "01"/"1", "Qui Nhơn"/"Quy Nhơn", which is the grouping `RunTests.py` applies). A field with no reliable match must be empty. A wrong non-empty value is a worse error than an empty one, because downstream systems cannot tell it is wrong.

## 2. Why a Trie fits

Names such as "Tân Bình", "Tân Phú" and "Tân Hòa" share the "tân" path, so building the Trie costs O(N) for N gazetteer characters. A walk from input position *i* costs O(d) for a name of length d, however many names are stored. The walk yields every name starting at *i*, shortest first, so longest-match comes free. Three Tries match the three administrative levels: each hit is labelled by the Trie that produced it, and the levels can be searched in priority order.

The Trie is not the only reasonable structure, and at this gazetteer size it is not clearly the fastest:

- **Hash set of full names.** Exact lookup is O(1) and the build is trivial. To segment, it must hash every span up to d_max, which is O(L·d_max) lookups of O(d) each. It has no way to stop early, so it spends work on spans that cannot match.
- **Aho–Corasick.** It finds every occurrence in one O(L + z) pass, with no restart per start index. The cost is failure links, which add build complexity and more dictionary work per character in pure Python. With L under ~100 the saving is small. It becomes worthwhile if L or the gazetteer grows.
- **Suffix array.** Built over the input, it indexes the wrong side of the problem. Built over the gazetteer, it helps recover partial names but does not help segmentation, and it costs O(N log N) to build.
- **Linear scan.** Testing `name in text` for every name uses C-level search. At roughly 1k names it may well fit the budget (Assumption; cheap to measure), and it is easy to verify. It gives no longest-match structure and scales as O(|G|·L).

The Trie's advantage here is therefore structural: it produces span positions, longest-match comes free, and the walk stops early. Raw speed is not the deciding argument at this scale.

## 3. Algorithm and complexity

**Insert.** Normalize each gazetteer line and insert the canonical form plus its variants (digit forms such as "p1"/"p01", unaccented forms, short forms such as "hcm"). Terminal nodes store the canonical string. Time and node count are O(N_v), where N_v is the character count after expansion. Each node holds a child dictionary whose fan-out is bounded by the alphabet Σ (about 100 symbols: toned Vietnamese letters, digits, a little punctuation) but is sparse in practice.

**Exact walk and longest match.** For each start index *i*, walk until a character has no child and record every terminal hit. That is O(d_max) per start and O(L·d_max) per level, and in practice the cost is far lower because most walks stop after one or two characters. Among the hits, keep the longest match that does not overlap a span already accepted at a higher-priority level.

**Reverse province pass.** Province names are inserted reversed and the input is walked from the right. The first long hit anchors the province at the tail, where it usually appears. The cost is the same O(L·d_max).

**Fuzzy fallback.** This stage is separate from exact search, and its cost is O(S·|G_v|·d²) for S unmatched segments against |G_v| stored variants. It does not grow with L; it grows with the size of the gazetteer.

*Implementation note.*
- The reversed Trie is built in `load_databases` and then discarded (`IndexAnalyzer.py:213-226`). The "reverse pass" is a forward walk with start indices iterated from right to left (`Searcher.py:59-64`).
- `search_max_length` scans every start from *i* to L (`IndexAnalyzer.py:94-111`), and it is called once per start, so the worst case is O(L²·d_max).
- The ranking key is end position first and length second (`Searcher.py:70`), which is not pure longest-match.
- `matched_positions` and `matched_intervals` are never filled, so the overlap check never runs. Overlap is prevented only because accepted spans are overwritten with a comma (`Searcher.py:18`).

## 4. Vietnamese-specific failure modes

- **Prefix ambiguity ("1" vs "10" vs "12", "Hòa" vs "Hòa Bình"): partially handled.** Longest match resolves "p10" against "p1". But normalization removes every space (`Utils.py:50`), so "hòa" is a valid hit inside "hòabình", and a name can match across two unrelated tokens. Longest match hides this in common cases but cannot rule it out.
- **Same name at two levels or in two provinces: fails to disambiguate.** "Hòa Bình" is both a province and a district, and many ward names repeat across provinces. Priority order picks the label, and nothing checks plausibility.
- **Abbreviation and prefix noise (Q., P., TP.): partially handled.** "TP", "Tỉnh", "Huyện" and "Xã" are removed. Digit wards and districts are indexed as "p1"/"q1". Bare "Q"/"P" were deliberately left out of the safe prefix list, because removing them breaks "Quận 5" and "KP5" (`Utils.py:4-13`). The cost is that "Q.Tân Bình" style input relies on the fallback stage.
- **Missing diacritics and one-edit typos: partially handled.** Fully unaccented input matches exactly because unaccented variants are indexed. Mixed tone marks (some syllables toned, some not) and typos miss the exact stage and depend on the fuzzy stage.
- **Province not at the end: partially handled.** The right-to-left scan still finds a province at the start of the string. But if a district or street name elsewhere is also a province string, the rightmost one wins.
- **Empty or partial addresses: partially handled.** Empty input gives empty output, but a leftover street segment can be "corrected" into a ward (distance ≤ 3, cosine > 0.73), filling a field that should be empty.
- **Lexicographically valid but geographically inconsistent: fails.** Nothing checks ward-in-district or district-in-province, and the gazetteer files carry no parent links to check against.

*Implementation note.* The canonical mapping is a flat dictionary (`IndexAnalyzer.py:238`). When two gazetteer lines produce the same unaccented variant, the one inserted last silently wins.

## 5. Autocorrect boundary

Exact search should stay authoritative. Edit-distance search should run only for levels still empty after the exact pass, only on segments no exact hit covered, and ideally only among the children of an already-chosen parent. Correcting across the whole gazetteer invites the main risk: a misspelled input lands on a *different, valid* name. The gazetteer is dense with near-neighbours ("Hòa Lợi"/"Hòa Lộc", "Phường 1"/"Phường 7"), and downstream a wrong valid name looks like a correct one.

The design limits this risk with level priority (provinces are few and distinct), an edit-distance cap of 3, and a cosine threshold (0.73, or 0.85 when digits are present). These rank candidates but do not guarantee correctness: a cap of 3 is large for 5–8-character names, and character-bag cosine ignores order.

Fuzzy search over the whole Trie is no longer O(L). Without pruning, it is a pass over every stored variant per segment. Running it on every segment of every request is what would break the 0.01-second average.

*Implementation note.* The fallback does not use the Trie at all. It scans `trie.all_words` linearly and NFKD-normalizes each candidate on every call (`Autocorrect.py:40-42`). It depends on the third-party `editdistance` package, which violates the standard-library constraint. It also runs in the order province, ward, district (`Searcher.py:24`), not the stated province, district, ward.

## 6. Complexity versus the latency budget

**Exact stage.** Assumptions: L ≈ 60 characters after normalization and d_max ≈ 25. Three levels × 60 starts × a few steps is a few thousand dictionary steps, low milliseconds or below even with the implementation's O(L²) behaviour. This stage is not the risk.

**Fuzzy stage.** Assumptions: |G_v| ≈ 1k stored variants per level (the provided lists hold 61/269/357 unique names before expansion; counted from the files). Segments are about 10 characters. A pure-Python DP edit distance takes 10–50 µs per pair. That gives about 10–50 ms per segment per level. A request with two or three unmatched segments would exceed the 10 ms average, and the worst cases could approach 100 ms. The fuzzy stage is therefore the step most likely to miss the budget. The C-backed `editdistance` package hides this now, but it will not be available under the standard-library rule.

What to measure:
- Per-stage timers.
- The fraction of requests that reach the fuzzy stage.
- The number of candidate comparisons per request.
- p50/p95/max with a standard-library edit distance substituted.

Trie build time is paid once in `Solution.__init__`. It should be reported separately and excluded from per-request figures.

## 7. Evaluation plan

**Test set.** Use `pseudo-code/public.json` (450 labelled triples) plus at least 5,000 held-out public addresses, with triples verified against the gazetteer and deduplicated after normalization. The synthetic `sample_addresses_2500.json` has no district field and deliberately includes out-of-gazetteer names, so it can measure false fills but not three-level accuracy.

**Metrics.**
- Per-field exact match after variant grouping.
- Full-triple exact match.
- False-empty rate: gold value non-empty, output empty.
- False-fill rate: gold value empty or out-of-gazetteer, output non-empty. Without this, thresholds can be tuned to fill everything.
- Latency p50, p95 and max over at least 5,000 calls after a warm-up, timed with `perf_counter_ns` around `process` only.

**Error slices.** Report every metric separately for abbreviations, missing or mixed tones, prefix collisions (digit wards, "Hòa X" families) and geographically inconsistent gold triples.

**Pass bar.**
- Latency: max ≤ 0.1 s and mean ≤ 0.01 s on a machine of the grader's class, standard library only.
- Accuracy: no slice regresses against the baseline measured by this plan. Any absolute accuracy target is the course's to set.

No score is claimed here, because this evaluation has not been run.

## 8. Verdict

Adopt the Trie for exact gazetteer segmentation: it gives labelled spans, longest match and early termination at negligible per-request cost, and no alternative is decisively better at this scale. Add hierarchy constraints once the gazetteer carries parent links or the inconsistency slice shows material errors, restricting district and ward candidates to children of the accepted parent in both stages. Replace the fuzzy stage if its standard-library p95 or max breaks the budget, using a Trie-guided bounded Levenshtein search (a DFS that carries one DP row and prunes when its minimum exceeds k) or an n-gram candidate filter.

Highest-priority risks:
1. There is no hierarchy consistency, so valid but geographically impossible triples are accepted.
2. The fuzzy stage has unbounded cost and depends on a non-standard-library package.
3. Removing spaces during normalization erases word boundaries, which makes prefix collisions and cross-token false matches possible.
