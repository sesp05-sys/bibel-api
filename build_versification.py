#!/usr/bin/env python3
"""Bygg rene versifikasjons-tabeller for bibel-api (redesign).

Artefakter (fra KJV-nummerert nor1930.json + wordproject-titler i /tmp/wp_psalms):
  1. nor1930.json           – KJV-nummerert, DE-DUPLISERT (fikser korrupte vers)
  2. nor1930_native.json    – REN NORSK i NO 1930-nummerering (med overskrifter)
  3. versification_map.json – materialisert NO<->KJV-mapping
  4. psalm_titles.json      – rene salme-overskrifter (v1 [+v2]) — commit-bar artefakt

Idempotent. Ord-basert fuzzy de-dup håndterer alle doblingsmønstre.
"""
import json, re, sys, os, copy, glob, html

HINT = re.compile(r'\((\d+):(\d+)\)')
LEAD = re.compile(r'^\s*\((\d+):(\d+)\)\s*')
TWO_VERSE = {51, 52, 54, 60}

# To KJV-vers utgjør ETT norsk vers (motsatt vei av MERGES under). Teksten
# skjøtes, og BEGGE KJV-adressene peker på det samme norske verset.
# Verifisert mot Bibelselskapet (bibel.no, Bokmål 1930):
#   Dan 10  har 21 vers, der v18 rommer KJV 10:18+10:19
#   Apg  4  har 36 vers, der v36 rommer KJV 4:36+4:37
#   2 Kor 13 har 13 vers, der v12 rommer KJV 13:12+13:13
JOINS = {
    ("27O",10,18): (10,18),
    ("44N",4,36):  (4,36),
    ("47N",13,12): (13,12),
}

# Adresser som verken hint eller nabo kan røpe — kapittel 10 i Daniel trekker
# til seg KJV 11:1 som sitt siste vers. Uten dette står KJV 11:1 på 11:1 og
# hele Daniel 11 blir liggende ett hakk feil, uten at noe varsler om det.
ADRESSER = {
    ("27O",11,1): (10,21),
}

# Hele kapitler som ligger forskjøvet uten at ET ENESTE hint røper det — den
# feilklassen kollisjonsvakten IKKE ser, siden ingenting overlapper. Når Dan 10
# tar KJV 11:1, må resten av Dan 11 rykke ett hakk ned: KJV 11:2 blir 11:1, og
# kapitlet får 44 vers mot KJVs 45.
KAP_SKIFT = {
    ("27O",11): -1,
}

# Vers-sammenslåinger: KJV (book,ch,v) -> [(no_ch,no_v) for A, for B]
MERGES = {
    ("09O",20,42): [(20,42),(20,43)],
    ("11O",22,43): [(22,43),(22,44)],
    ("43N",1,38):  [(1,38),(1,39)],
    ("64N",1,14):  [(1,14),(1,15)],
    ("66N",13,1):  [(12,18),(13,1)],
}

def wkey(w):        # ord uten tegnsetting, lowercase
    return re.sub(r'[^0-9a-zæøåäöü]+', '', w.lower())
def nwords(s):
    return [x for x in (wkey(w) for w in s.split()) if x]

def dedup(text):
    """(ren_kjv_tekst, hint_addr|None). Fjerner dobling; behold ekte merge."""
    m = HINT.search(text)
    if not m:
        return text, None
    a, b = int(m.group(1)), int(m.group(2))
    if LEAD.match(text):
        return text, (a, b)
    prefix = text[:m.start()].strip()
    tail   = text[m.end():].strip()
    pw, tw = nwords(prefix), nwords(tail)
    if pw == tw:                                   # enkel dobling  X (k) X
        clean = f"({a}:{b}) {tail}"
    elif len(pw) > len(tw) and pw[-len(tw):] == tw:  # merge  A B (k) B
        head = ' '.join(prefix.split()[:len(pw)-len(tw)])
        clean = f"{head} ({a}:{b}) {tail}"
    elif len(tw) > len(pw) and tw[-len(pw):] == pw:  # reversert  X (k) EKSTRA X
        clean = f"({a}:{b}) {prefix}"
    else:                                          # ekte merge uten dobling (Joh 1:38)
        clean = f"{prefix} ({a}:{b}) {tail}"
    return clean, (a, b)

def strip_hints(t):
    return re.sub(r'\s*\(\d+:\d+\)\s*', ' ', t).strip()

def extract_titles(wp_dir):
    """Les rå dimver fra wordproject-HTML → {ch: {"1":..., optionally "2":...}}."""
    titles = {}
    for f in glob.glob(f"{wp_dir}/*.htm"):
        ch = int(os.path.basename(f)[:-4])
        raw = open(f, encoding="utf-8", errors="replace").read()
        m = re.search(r'class="dimver">(.*?)</span>', raw, re.S)
        if not m:
            continue
        t = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.S)
        t = re.sub(r'<[^>]+>', '', t)
        t = re.sub(r'\s+', ' ', html.unescape(t)).strip()
        clean, hint = dedup(t)                     # dedup evt. dobling i tittel
        if ch in TWO_VERSE and HINT.search(clean):
            parts = HINT.split(clean, 1)           # [v1, ch, v, v2]
            titles[ch] = {"1": parts[0].strip(), "2": strip_hints(parts[-1])}
        else:
            titles[ch] = {"1": strip_hints(clean)}
    return titles

def build(src_nor, wp_dir, outdir):
    nor = json.load(open(src_nor, encoding="utf-8"))
    bible = nor["bible"]
    titles = extract_titles(wp_dir)

    deduped = copy.deepcopy(nor)
    native_bible, fwd = {}, {}
    stats = {"deduped":0, "merges":0, "titles":0, "native_verses":0, "interpolert":0, "joins":0}
    # Hvem gjør krav på hvilken native-adresse. Tilordningene under overskriver
    # bare hverandre (og dict-inverteringen av fwd mister duplikater), så uten
    # denne bokføringen forsvinner et vers sporløst når to KJV-vers lander på
    # samme adresse. Rapporteres av verify().
    krav = {}
    def ta(book, na_ch, na_v, kjv_ch, kjv_v):
        krav.setdefault((book, f"{na_ch}:{na_v}"), []).append(f"{kjv_ch}:{kjv_v}")

    # kjv_to_no bygges nå EKSPLISITT. Den ble tidligere laget ved å invertere
    # fwd, og da forsvant den ene halvparten av hver sammenslåing: to KJV-vers
    # kan peke på samme norske vers, men et invertert 1:1-oppslag beholder bare
    # den siste. Retningen native→kjv er fortsatt 1:1 (første KJV-vers).
    rev = {}
    for book, chapters in bible.items():
        native_bible.setdefault(book, {}); fwd.setdefault(book, {}); rev.setdefault(book, {})
        slukt = set()          # vers som er skjøtet inn i et JOINS-vers
        for ch_str, verses in chapters.items():
            kjv_ch = int(ch_str)
            for v_str, text in verses.items():
                kjv_v = int(v_str)
                if (kjv_ch, kjv_v) in slukt:
                    continue          # alt skjøtet inn i forrige vers (JOINS)
                # Neste vers' hint forteller hvor DETTE verset hører hjemme:
                # står 6:2 på (5:21), er 6:1 nødvendigvis 5:20. Kilden mangler
                # hintet på det første verset i et forskjøvet parti, og uten
                # dette havnet det på sin egen KJV-adresse — oppå et annet vers.
                nabo = LEAD.match(verses.get(str(kjv_v + 1), "") or "")
                arvet = None
                if nabo:
                    na, nb = int(nabo.group(1)), int(nabo.group(2))
                    # SAMMENSLÅING: naboens adresse er allerede min egen — de to
                    # KJV-versene deler ett native-vers. Da skal jeg IKKE flyttes
                    # ett hakk ned (det ville dyttet kollisjonen over på verset
                    # foran); MERGES-tabellen er riktig sted. Vakten fanger den.
                    if not (na == kjv_ch and nb == kjv_v) and nb > 1:
                        arvet = (na, nb - 1)
                    elif nb == 1 and kjv_v == 1 and na == kjv_ch:
                        # Naboen er vers 1 i sitt kapittel ⇒ jeg hører til
                        # SLUTTEN av forrige kapittel. 1930 har f.eks. 39 vers i
                        # 1. Mos 42 der KJV har 38, og det 39. er det KJV kaller
                        # 43:1 (verifisert mot Bibelselskapet).
                        forrige = native_bible[book].get(str(na - 1))
                        if forrige:
                            arvet = (na - 1, max(int(x) for x in forrige) + 1)
                    # Aldri interpoler oppå noe som alt er tatt
                    if arvet and (book, f"{arvet[0]}:{arvet[1]}") in krav:
                        arvet = None
                clean, hint_addr = dedup(text)
                if clean != text:
                    deduped["bible"][book][ch_str][v_str] = clean
                    stats["deduped"] += 1
                key = (book, kjv_ch, kjv_v)
                if key in JOINS:
                    # To KJV-vers, ett norsk: skjøt tekstene og la BEGGE
                    # KJV-adressene peke hit i kjv_to_no.
                    na_ch, na_v = JOINS[key]
                    neste = dedup(verses.get(str(kjv_v + 1), "") or "")[0]
                    tekst = (strip_hints(clean) + " " + strip_hints(neste)).strip()
                    native_bible[book].setdefault(str(na_ch),{})[str(na_v)] = tekst
                    fwd[book][f"{na_ch}:{na_v}"] = f"{kjv_ch}:{kjv_v}"
                    rev[book][f"{kjv_ch}:{kjv_v}"] = f"{na_ch}:{na_v}"
                    rev[book][f"{kjv_ch}:{kjv_v + 1}"] = f"{na_ch}:{na_v}"
                    ta(book, na_ch, na_v, kjv_ch, kjv_v)
                    slukt.add((kjv_ch, kjv_v + 1))
                    stats["joins"] += 1; stats["native_verses"] += 1
                elif key in ADRESSER:
                    no_ch, no_v = ADRESSER[key]
                    native_bible[book].setdefault(str(no_ch),{})[str(no_v)] = strip_hints(clean)
                    fwd[book][f"{no_ch}:{no_v}"] = f"{kjv_ch}:{kjv_v}"
                    rev[book][f"{kjv_ch}:{kjv_v}"] = f"{no_ch}:{no_v}"
                    ta(book, no_ch, no_v, kjv_ch, kjv_v)
                    stats["native_verses"] += 1
                elif key in MERGES:
                    (na_ch,na_v),(nb_ch,nb_v) = MERGES[key]
                    parts = HINT.split(clean, 1)
                    A, B = strip_hints(parts[0]), strip_hints(parts[-1])
                    native_bible[book].setdefault(str(na_ch),{})[str(na_v)] = A
                    native_bible[book].setdefault(str(nb_ch),{})[str(nb_v)] = B
                    fwd[book][f"{na_ch}:{na_v}"] = f"{kjv_ch}:{kjv_v}"
                    fwd[book][f"{nb_ch}:{nb_v}"] = f"{kjv_ch}:{kjv_v}"
                    rev[book][f"{kjv_ch}:{kjv_v}"] = f"{na_ch}:{na_v}"
                    ta(book, na_ch, na_v, kjv_ch, kjv_v)
                    ta(book, nb_ch, nb_v, kjv_ch, kjv_v)
                    stats["merges"] += 1; stats["native_verses"] += 2
                elif hint_addr:
                    no_ch, no_v = hint_addr
                    native_bible[book].setdefault(str(no_ch),{})[str(no_v)] = strip_hints(clean)
                    fwd[book][f"{no_ch}:{no_v}"] = f"{kjv_ch}:{kjv_v}"
                    rev[book][f"{kjv_ch}:{kjv_v}"] = f"{no_ch}:{no_v}"
                    ta(book, no_ch, no_v, kjv_ch, kjv_v)
                    stats["native_verses"] += 1
                else:
                    # Uten hint: arv adressen fra naboen når den finnes, ellers
                    # er native == KJV (det normale i uforskjøvede partier).
                    if arvet:
                        no_ch, no_v = arvet
                        stats["interpolert"] += 1
                    else:
                        no_ch, no_v = kjv_ch, kjv_v + KAP_SKIFT.get((book, kjv_ch), 0)
                    native_bible[book].setdefault(str(no_ch),{})[str(no_v)] = strip_hints(clean)
                    fwd[book][f"{no_ch}:{no_v}"] = f"{kjv_ch}:{kjv_v}"
                    rev[book][f"{kjv_ch}:{kjv_v}"] = f"{no_ch}:{no_v}"
                    ta(book, no_ch, no_v, kjv_ch, kjv_v)
                    stats["native_verses"] += 1

    # salme-overskrifter som native NO vers 1 (+ 2)
    for ch, parts in titles.items():
        native_bible["19O"].setdefault(str(ch), {})
        native_bible["19O"][str(ch)]["1"] = parts["1"]
        if "2" in parts:
            native_bible["19O"][str(ch)]["2"] = parts["2"]
        stats["titles"] += 1


    os.makedirs(outdir, exist_ok=True)
    json.dump(deduped, open(f"{outdir}/nor1930.json","w",encoding="utf-8"), ensure_ascii=False)
    json.dump({"books":nor.get("books"),"names":nor.get("names"),"bible":native_bible},
              open(f"{outdir}/nor1930_native.json","w",encoding="utf-8"), ensure_ascii=False)
    json.dump({"no_to_kjv":fwd,"kjv_to_no":rev},
              open(f"{outdir}/versification_map.json","w",encoding="utf-8"), ensure_ascii=False)
    json.dump({str(k):v for k,v in sorted(titles.items())},
              open(f"{outdir}/psalm_titles.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
    return stats, deduped, native_bible, krav

def verify(src_nor, deduped, native_bible, krav=None):
    nor = json.load(open(src_nor, encoding="utf-8"))["bible"]
    names = json.load(open(src_nor, encoding="utf-8")).get("names", {})
    problems = []
    # 0) KOLLISJON: to KJV-vers på samme native-adresse. Den sist tilordnede
    #    vinner, og den andre finnes verken i native-fila eller i kartet.
    for (b, adr), kjv in sorted((krav or {}).items()):
        if len(kjv) > 1:
            problems.append(f"KOLLISJON {names.get(b, b)} native {adr} ← KJV "
                            f"{', '.join(kjv)} (kun {kjv[-1]} overlever)")
    # 1) ingen dobling/midt-hint igjen i native
    for b,chs in native_bible.items():
        for c,vs in chs.items():
            for v,t in vs.items():
                if HINT.search(t):
                    problems.append(f"native {b} {c}:{v} har hint igjen: {t[:50]}")
    # 1b) HULL: manglende versnummer i et native-kapittel. Fanger den klassen
    #     vakten over ikke ser — et kapittel som ligger forskjøvet uten at noe
    #     overlapper (Dan 11 manglet vers 1 til KAP_SKIFT kom på plass).
    for b, chs in native_bible.items():
        for c, vs in chs.items():
            n = [int(x) for x in vs]
            mangler = [i for i in range(1, max(n) + 1) if i not in n]
            if mangler:
                problems.append(f"HULL {names.get(b, b)} {c}: mangler vers {mangler}")
    # 2) per affected salme: native antall == KJV antall + forskyvning
    ps_native = native_bible["19O"]; ps_kjv = nor["19O"]
    for ch in [int(x) for x in open("/tmp/psalm_chapters.txt").read().split()]:
        kjvn = len(ps_kjv[str(ch)])
        natn = len(ps_native[str(ch)])
        shift = natn - kjvn
        if shift not in (1,2):
            problems.append(f"Sal {ch}: native={natn} kjv={kjvn} (forskyvning {shift})")
    # 3) ingen KJV-vers med rest-dobling (utover de 5 merges)
    for b,chs in deduped["bible"].items():
        for c,vs in chs.items():
            for v,t in vs.items():
                if HINT.search(t) and not LEAD.match(t) and (b,int(c),int(v)) not in MERGES:
                    problems.append(f"KJV {b} {c}:{v} fortsatt midt-hint: {t[:60]}")
    return problems

if __name__ == "__main__":
    src = "/opt/bibel-api/data/nor1930.json"
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bibel_build"
    stats, deduped, native, krav = build(src, "/tmp/wp_psalms", outdir)
    print("Bygget →", outdir)
    for k,v in stats.items(): print(f"  {k}: {v}")
    print("\n=== VERIFISERING ===")
    probs = verify(src, deduped, native, krav)
    if not probs:
        print("  ✅ INGEN problemer: ingen hint i native, alle salmer stemmer, ingen rest-dobling")
    else:
        print(f"  ⚠️ {len(probs)} problem(er):")
        for p in probs[:30]: print("   -", p)
    print("\n=== STIKKPRØVER (native) ===")
    nb = native["19O"]
    for ch,vv in [(3,(1,2,3)),(18,(1,2,3)),(36,(1,2)),(51,(1,2,3)),(23,(1,2))]:
        for v in vv:
            print(f"  Sal {ch}:{v} = {nb[str(ch)].get(str(v),'—')[:66]!r}")
