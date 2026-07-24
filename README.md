# Bibel API

Et lite, gjenbrukbart REST-API for oppslag av bibelvers på **King James Version (KJV)**
og **Norsk 1930** — side om side. Ingen database: all tekst ligger i JSON-filer, så
API-et kan kjøres standalone eller importeres som et Flask-Blueprint i et annet prosjekt.

Live: <https://bibel-api.bibeltroen.no>

```
GET /api/verse?ref=Joh+3:16
```
```json
{
  "book_en": "John",
  "book_id": 43,
  "book_no": "Johannes",
  "chapter": 3,
  "reference_en": "John 3:16",
  "reference_no": "Johannes 3:16",
  "verse_start": 16,
  "verse_end": 16,
  "verses": [
    {
      "verse": 16,
      "kjv": "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.",
      "nor": "For så har Gud elsket verden at han gav sin Sønn, den enbårne, forat hver den som tror på ham, ikke skal fortapes, men ha evig liv;"
    }
  ]
}
```

*Merk: API-et escaper ikke-ASCII-tegn (`å` → `\u00e5`) i JSON — dette dekodes automatisk av klienten.*

## Endepunkter

| Endepunkt | Beskrivelse |
|-----------|-------------|
| `/api/verse?ref=Joh+3:16` | Slå opp vers (begge oversettelser) |
| `/api/verse?ref=Sal+23&lang=nor` | Kun Norsk 1930 |
| `/api/verse?ref=Rev+21:1&lang=kjv` | Kun KJV |
| `/api/books` | Alle 66 bøker (id + norsk/engelsk navn) |
| `/api/chapters/<book_id>` | Kapitler og versantall i en bok |
| `/api/search?q=beginning&lang=kjv&limit=10` | Fulltekstsøk i bibelteksten |
| `/api/redletter?ref=Matt+5:1-12` | Marker Jesu ord (røde bokstaver) i teksten |

Referanser godtar både norske og engelske boknavn og vanlige forkortelser
(`Joh`, `John`, `1 Mos`, `Gen`, `Sal`, `Ps` …), enkeltvers og versområder (`Sal 23:1-6`).

## Nøkkelfunksjon: versifikasjonsmapping

KJV og Norsk 1930 nummererer ikke alltid versene likt (særlig i Salmenes overskrifter).
API-et oversetter automatisk mellom de to systemene, slik at `ref=Sal+23` gir samme vers
i begge oversettelsene uansett hvilken nummerering du spør med.

## Kjøre lokalt

```bash
pip install -r requirements.txt
gunicorn wsgi:app        # eller: python -c "from bibel_api import create_app; create_app().run()"
```

## Gjenbruk i andre prosjekter

Som Flask-Blueprint:

```python
from bibel_api import create_bible_blueprint
app.register_blueprint(create_bible_blueprint(), url_prefix="/bible")
```

Som rene Python-funksjoner:

```python
from bibel_api import parse_reference, lookup_verses

parsed = parse_reference("Joh 3:16")
result = lookup_verses(43, 3, 16, 16, translation="both")
```

## Data og lisens

- `data/kjv.json` — King James Version (public domain)
- `data/nor1930.json` — Norsk 1930 (fritt tilgjengelig)
- `data/kjv_red_letter.json` — indeks over Jesu ord i KJV

Koden er fri til gjenbruk. Bibeltekstene er gjengitt fra fritt tilgjengelige kilder.
