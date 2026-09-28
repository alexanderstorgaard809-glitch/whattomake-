# Tender Radar

Finder relevante offentlige EU-udbud til IT-bureauer ud fra **rigtige data fra TED** (EU's officielle udbudsdatabase). Den oversætter og opsummerer dem med AI via **OpenRouter** og laver en mail-klar rapport til hvert bureau.

Det er værktøjet til at teste idéen: *"Ville I betale 49 USD om måneden for det her?"*

## Sådan virker det

```
TED API (gratis)  →  1. fetch      Henter alle aktive IT-udbud fra de seneste 30 dage
                  →  2. summarize  AI oversætter og opsummerer hvert udbud på engelsk (én gang, gemmes)
                  →  3. report     Billig AI sorterer alle udbud mod bureauets profil,
                                   stærkere AI læser de mest lovende i fuld tekst og giver endelig score
                  →  output/<bureau>.html  (klar til at kopiere ind i en mail)
```

## Kom i gang (ca. 10 minutter)

**Krav:** Python 3.9 eller nyere. Ingen ekstra pakker.

1. **Lav en OpenRouter-konto** på https://openrouter.ai og indsæt 5 USD i kredit.
2. **Lav en API-nøgle** på https://openrouter.ai/keys.
3. **Gem nøglen:** kopiér `.env.example` til `.env`, og indsæt nøglen.
4. **Kør det hele:**
   ```bash
   cd tender_radar
   python radar.py run
   ```
5. **Åbn rapporten** `output/eksempel-it-bureau.html` i din browser.

## Tilføj de 10 bureauer (trin 3)

Lav en profil for hvert bureau ud fra deres hjemmeside:

```bash
python radar.py profile --name "Bureau ApS" --url https://bureau.dk --countries DNK,SWE,NOR,DEU --languages DAN,ENG
```

Profilen gemmes i `profiles/bureau-aps.json`. Læs den igennem og ret den, hvis AI har misforstået noget. Kør derefter:

```bash
python radar.py report            # rapporter til alle profiler
python radar.py report profiles/bureau-aps.json   # kun ét bureau
```

Opsummeringer af udbud gemmes i `data/summaries.json`, så du kun betaler for hvert udbud én gang. Nye bureauer koster kun matching-trinnet.

Mail-skabelon, tips til at finde bureauer og en tracker til svarene ligger i [`outreach/`](outreach/).

## Valg af AI-model

To modeller, hver til det den er bedst til:

| Trin | Model (OpenRouter-id) | Pris pr. 1 mio. tokens (ind / ud) | Hvorfor |
|---|---|---|---|
| Opsummering + første sortering | `google/gemini-3.1-flash-lite` (reserve: `gemini-2.5-flash-lite`) | 0,25 / 1,50 USD | Tusindvis af udbud på 24 sprog. Skal være billig, hurtig og god til sprog |
| Grundig vurdering af top ~80 | `google/gemini-3.8-flash` (reserve: `gemini-3.7-flash`) | 0,75 / 3,75 USD | Læser hele udbudsteksten og vurderer som en erfaren tilbudsansvarlig |

Den grundige vurdering skelner mellem udviklingsopgaver og køb af færdige produkter. Den har også hårde lofter:
- Udbud, der rammer bureauets "ikke interesseret"-liste, får højst 25 %.
- Køb af færdigt produkt/licens får højst 50 %, med mindre profilen har `"sells_products": true`.
- For store opgaver (værdi, varighed, krav) får højst 55 %.
- Hvis bureauet ikke kan skrive tilbud på udbuddets sprog, får udbuddet højst 40 %.

Priserne er fra OpenRouter i september 2026, så tjek dem på https://openrouter.ai/models. Du kan skifte model med `"models"` og `"rerank_models"` i `config.json`.

**Forventet pris:** Første kørsel koster typisk 1-3 USD for opsummering af et par tusinde udbud. Derefter koster det ca. 0,10-0,30 USD pr. bureau. Skriptet udskriver den faktiske pris efter hver kørsel.

## Indstillinger (`config.json`)

- `cpv_codes`: EU's varekoder for IT-tjenester (72xxxxxx) og software (48xxxxxx). Det er dem, der afgør, hvilke udbud der hentes.
- `days_back`: hvor langt tilbage der hentes (standard 30 dage).
- `scope`: `ACTIVE` henter kun udbud, der stadig er åbne.
- `min_score`: laveste score, der kommer med i rapporten (standard 60).
- `rerank_min_score` / `rerank_max`: hvilke udbud fra første sortering der får en grundig vurdering (standard: score 50+, højst 80).

## Test

```bash
python -m unittest discover tests
```

Testene kører uden internet med opdigtede testdata. Det er kun for at tjekke koden. De rigtige kørsler bruger altid live data fra TED.

## Kendte begrænsninger

- TED indeholder kun udbud over EU's beløbsgrænser. Mindre danske udbud ligger på udbud.dk og findes ikke her endnu.
- AI kan misforstå et udbud, så rapporten linker altid til det originale udbud.
- CPV-koderne rammer ikke alt. Nogle IT-udbud bliver registreret under andre koder.
