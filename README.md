# Smart Grid Flow

Smart elstyrning för Home Assistant, på svenska. Visar värmepump, varmvattenberedare,
elpriser (nu och kommande) och förbrukning per stor förbrukare – och styr värmepumpen
så att komforten hålls till lägsta möjliga kostnad.

> **Status: 0.1.3.** Mjuk och energieffektiv värmepumpsstyrning med rampbegränsning,
> timsynkronisering och dämpning mot onödig pendling.

![Smart Grid Flow – exempelvy](docs/demo/screenshot.png)

*Exempelbild med påhittad data, renderad av det riktiga kortet. Generera om med `python docs/demo/make_sample.py`.*

## Funktioner

- **Mjuk & energieffektiv värmepumpsstyrning:** Skyddar kompressorn och optimerar verkningsgraden (COP):
  - *Rampbegränsning:* Ändrar börvärdet med max 1,0–1,5 °C per timme (inga plötsliga hopp mellan 18 °C och 26 °C).
  - *Timsynkronisering:* Börvärdet uppdateras per heltimme i takt med elpriset och hålls stabilt under timmen.
  - *Anti-cyklingsspärr:* Minst 45 minuter mellan automatiska börvärdesjusteringar så invertern hinner stabilisera sig.
  - *Dämpat sökområde:* Håller börvärdet samlat kring komfortmålet (t.ex. ±1,5–2,0 °C vid 21 °C) för hög värmefaktor.
- **Elpris med alla avgifter:** spotpris (elprisetjustnu.se, elområde SE1–SE4) + elhandlarpåslag
  + moms + nätens överföringsavgift + energiskatt. Standardvärden för **Göteborg Energi Elnät**
  (villa), alla justerbara i konfigurationen.
- **Effekttariff:** följer månadens tre högsta timmedeleffekter (olika dygn) via en huvudmätare
  och håller värmepumpen under tröskeln när det lönar sig.
- **Fyra optimeringslägen:** *Lägsta pris*, *Balanserad*, *Stabil temperatur* samt *Bortaläge*.
- **Termostatkort med tre temperaturer:** Visar *Aktuell innetemperatur* (mätning), *Önskad temperatur*
  (justerbar med `+`/`−`) och *Inställt på pumpen* (faktiskt börvärde på WF-RAC samt plan nästa timme).
- **Bortaläge (Bortaläge / Away mode):** Tvingar värmepumpen till värmeläge och sänker börvärdet till
  underhållsvärme (~12 °C, justerbart) för att minimera energianvändningen.
- **Automatisk säsongsväxling (värme/kyla):** Växlar automatiskt mellan `heat` och `cool` baserat på
  ute- och innetemperatur med inbyggt hysteres- och tidsskydd för att undvika onödig pendling.
- **Självlärande:** efter varje timme uppdateras två modeller (rekursiv minstakvadrat):
  husets värmeförlust/uppvärmning och värmepumpens förbrukning givet börvärde och utetemperatur.
- **Varmvattenberedare:** kör de billigaste timmarna per dygn, med min/max-temperatur och legionellaskydd.
- **Bästa tid att köra:** diagram (med markering för nu) över vilka timmar som är billigast för
  elbilsladdning och dusch. Duschens energi förbrukas när beredaren värmer upp *efteråt*, så för dusch
  visas priset vid uppvärmningstimmen (enligt beredarschemat om styrning är på, annars konfigurerbar fördröjning).
- **Animerat effektflöde:** elnät (köper/säljer), solceller, batteri (laddar/laddar ur, laddnivå),
  värmepump, beredare, elbil och övrig last med stor, tydlig text anpassad för mobiler.
- **Utbyggbart** för solceller, batteri och elbilsladdare (se `core/devices.py`).

## Hur kopplas värmepumpen? (Mitsubishi WF-RAC)

Integrationen pratar **inte** direkt med värmepumpen – den använder entiteterna från din
befintliga [WF-RAC-integration](https://github.com/blues-sechseck/Mitsubishi-WF-RAC-Integration)
(`mitsubishi_wf_rac`; även `wf_rac` identifieras):

| Behov | WF-RAC-entitet | Används till |
|---|---|---|
| Styrning | `climate.*` | `climate.set_temperature` / `climate.set_hvac_mode` |
| Innetemperatur | `sensor.*` inomhus | Starttillstånd + inlärning |
| Utetemperatur | `sensor.*` utomhus | Inlärning (prognosen kommer från `weather`) |
| Energi | `sensor.*` energi (kWh) | Lär in förbrukning vid givet börvärde; kostnad per dygn |

Vid installation söker konfigurationsflödet upp dessa entiteter automatiskt. Använd helst
sensorn för **total energi** – enhetens egen räknare nollställs vid varje start, och WF-RAC
erbjuder därför en ackumulerad totalsensor. Räknare som minskar ignoreras.

## Installation & Lovelace-resurser

1. HACS → Tre prickar uppe till höger → **Anpassade arkiv** → Lägg till `https://github.com/castmo/Smart-Grid-Flow` (Kategori: *Integration*).
2. Ladda ner / Uppdatera till version **0.1.2** i HACS.
3. Starta om Home Assistant.
4. **Viktigt:** Gå till **Inställningar → Enheter & tjänster → Lägg till integration → Sök "Smart Grid Flow"**.
   *(Kortet laddas automatiskt in när integrationen har lagts till).*
5. Om du får felmeddelandet `Custom element doesn't exist: smart-grid-flow-card` i Lovelace:
   - Gå till **Inställningar → Instrumentpaneler (Dashboards) → Resurser** (eller tre punkter uppe i högra hörnet på instrumentpanelen → Hantera resurser).
   - Kontrollera att resursen finns:
     - URL: `/smart_grid_flow/smart-grid-flow-card.js` (eller `/local/smart_grid_flow/smart-grid-flow-card.js`)
     - Resurstyp: *JavaScript-modul*.
   - Rensa webbläsarens cache eller gör en hård omladdning (Shift+F5 i webbläsaren, eller dra neråt i HA Companion-appen).
6. Lägg till kortet i dashboarden:
   ```yaml
   type: custom:smart-grid-flow-card
   ```
7. Slå på **Styr värmepump** när planen ser rimlig ut.

## Inställningar

- **Huvudmätare** (valfri): effekt (W/kW) eller energi (kWh) för hela huset – krävs för effekttariffen.
- **Väderentitet** (valfri men rekommenderad): används för timprognos via `weather.get_forecasts`.
- **Fler förbrukare:** valfria energisensorer (t.ex. elbilsladdare) visas i kortet.

### Avgifter – verifiera!
Standardvärden (2026, inkl. moms): överföring 23 öre/kWh, energiskatt 45 öre/kWh,
effektavgift 49 kr/kW och månad, fast avgift 205 kr/mån. Hämtade från Göteborg Energis
prislista via en websökning – **kontrollera mot din faktura** och ändra under
*Konfigurera*. Elhandlarpåslaget är satt till 5 öre/kWh och beror på ditt avtal.

## Så fungerar optimeringen

```
kostnad/timme = elpris · kWh  +  komfortstraff  +  effektstraff
```
- Komfortstraffet beror på läget (Lägsta pris tillåter mer variation, Stabil temperatur straffar
  avvikelse från önskad temperatur hårt).
- Effektstraffet läggs på när timmens effekt skulle överstiga månadens 3:e högsta topp.
- Modellens säkerhet (0–100 %) växer med inlärda timmar; full efter ca 7 dygn. Innan dess
  används rimliga startvärden – kör gärna *Balanserad* de första dagarna.

## Utveckling

```bash
pip install pytest && python -m pytest -q tests
```
Kärnlogiken i `custom_components/smart_grid_flow/core/` har inga Home Assistant-beroenden.

## Licens
MIT
