# Claim Pilot

Hjælper freelancere og små virksomheder med at få betaling fra kunder i **EU og Storbritannien**:

1. **Upload** fakturaen (PDF eller billede) og evt. mails.
2. AI'en læser dokumenterne. **Koden** beregner lovbestemt rente og fast kompensation pr. faktura og viser de næste skridt:
   - **EU** (direktiv 2011/7/EU): 40 € pr. faktura, europæisk betalingspåbud og småkravsprocedure.
   - **UK** (Late Payment of Commercial Debts (Interest) Act 1998): £40/£70/£100 pr. faktura, "letter before claim", Money Claim Online og small claims track. Pre-Action Protocol (30 dage) når kunden er en enkeltmandsvirksomhed eller privatperson.

   Reglerne vælges efter **dit** land (leverandørens lov gælder normalt for tjenesteydelser), og retsvejen efter **kundens** land.
3. AI'en skriver et **formelt rykkerbrev på kundens sprog** plus en engelsk version.

Brugerfladen er på engelsk, fordi produktet er til hele EU.

## Start (Windows)

Krav: Python 3.9 eller nyere. Ingen ekstra pakker.

1. Kopiér din `.env` (med `OPENROUTER_API_KEY`) ind i mappen `claim_pilot`.
2. Åbn en terminal i mappen `claim_pilot`, og kør:
   ```
   python app.py
   ```
3. Browseren åbner selv http://localhost:8000. Stop med **Ctrl + C** i terminalen.

## AI-model

`google/gemini-3.8-flash` (reserve: `gemini-3.7-flash`) via OpenRouter. Den kan læse PDF'er og billeder direkte og skriver godt på alle EU-sprog. En sag koster typisk under 0,02 USD. Prisen vises nederst på siden. Du kan skifte model i `config.json`.

**AI'en regner aldrig beløb.** Renter, kompensation og procedurevalg beregnes i `claims.py` og sendes færdige ind i brevet.

## Rentesatser (`config.json` → `rates`)

- **EU:** ECB's referencerente + 8 %-point. Sat til 10,4 % for 2. halvår 2026. Det er en antagelse: 2,40 % pr. 1. juli 2026, udledt af at ECB hævede til 2,65 % den 16. september 2026. Nogle lande har højere tillæg.
- **UK:** Bank of England base rate + 8 %-point. Base rate pr. 31/12 gælder for fakturaer, der forfalder i januar-juni, og pr. 30/6 for juli-december. Begge var 3,75 % i 2026, så satsen er 11,75 %. Tilføj en ny linje i `base_rates` hvert halvår.

Satsen kan også rettes direkte på siden.

## Test

```
python -m unittest discover tests
```

## Næste skridt (ikke bygget endnu)

- Udfyldte EU-formularer (betalingspåbud formular A / småkravsprocedure formular A) på domstolens sprog.
- Find den rigtige domstol og retsafgift pr. land.
- Hosting som rigtig webside med betaling.

## Vigtigt

Claim Pilot er et selvhjælpsværktøj og ikke juridisk rådgivning. Før der tages betaling fra kunder, skal en jurist vurdere reglerne for juridisk bistand i de lande, der sælges til.

## Testsager

I `examples/` ligger to opdigtede testsager:

| Sag | Filer | Hvad den tester |
|---|---|---|
| Spansk designer → tysk firma, 3.650 € | `invoice_ES_to_DE.pdf` + `emails_ES_to_DE.txt` | Kunden er tavs. Både betalingspåbud og småkravsprocedure kan bruges. Brevet skrives på tysk |
| Britisk freelancer → britisk restaurantkæde, £2.030 | `invoice_UK_to_UK.pdf` + `emails_UK_to_UK.txt` | UK-regler: 11,75 % rente, £70 kompensation, "letter before claim" og Money Claim Online |
| Hollandsk udvikler → fransk firma, 7.800 € | `invoice_NL_to_FR.pdf` + `emails_NL_to_FR.txt` | Kunden klager over en fejl, så AI'en skal opdage en tvist. Over 5.000 €, så kun betalingspåbud. Brevet skrives på fransk |
