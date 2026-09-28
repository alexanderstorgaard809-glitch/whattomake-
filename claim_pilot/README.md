# Claim Pilot

Hjælper freelancere og små virksomheder med at få betaling fra kunder i **andre EU-lande**:

1. **Upload** fakturaen (PDF eller billede) og evt. mails.
2. AI'en læser dokumenterne. **Koden** beregner lovbestemt rente og **40 € kompensation pr. faktura** (direktiv 2011/7/EU) og viser, om kravet kan bruge **europæisk betalingspåbud** eller **småkravsproceduren**.
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

## Rentesats

`late_payment_rate_percent` i `config.json` er ECB's referencerente pr. 1. januar/1. juli + 8 %-point. Den er sat til 10,4 % for 2. halvår 2026. **Det er en antagelse:** 2,40 % pr. 1. juli 2026, udledt af at ECB hævede til 2,65 % den 16. september 2026. Tjek satsen, og ret den ved hvert halvårsskifte. Nogle lande har højere tillæg. Satsen kan også rettes direkte på siden.

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
