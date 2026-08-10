"""
Demo evidence corpus.

Why this exists: `/v1/analyze/news` derives its credibility score from retrieved
evidence, and a freshly deployed instance has an empty `documents` table. With
nothing to retrieve, every claim honestly returns "insufficient evidence" and the
score falls through to the linguistic heuristic. That is the correct behaviour
for an empty corpus, but it means a new deployment cannot demonstrate the actual
RAG pipeline at all.

WHAT THESE DOCUMENTS ARE — read before quoting any of this in a report.

They are **curated factual summaries written for this corpus**, each citing the
real public source it summarises. They are NOT verbatim copies of those pages,
and they must never be presented as such (that is why every title carries a
"(summary)" suffix and every row is tagged `meta.curated = true`). Their purpose
is to give the retrieval + stance pipeline something real to work with; the
system's honesty guarantee is unchanged, because every citation points at a real
public document a reader can check for themselves.

For a production tenant you would replace this with a real ingest — GDELT, a
fact-check feed, or your own document store. This seed only ever runs when the
tenant has NO evidence documents at all, so it can never overwrite that.

A NOTE ON WORDING, because it looks arbitrary otherwise.

When `transformers` is unavailable (as on a small free-tier dyno) stance
detection degrades to `LexicalStanceModel`, which decides ENTAIL vs CONTRADICT by
*negation mismatch*: evidence containing "no"/"not"/"false" opposite a claim
containing none is read as a contradiction. Debunking text carries those words
naturally, so these summaries work under both the lexical fallback and the real
NLI model. Do not "tidy" the negations out of the refuting documents — that
silently inverts their stance on the fallback path. See `LexicalStanceModel` in
services/ml/rag/verify.py, which is candid about how weak it is.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Source credibility weights. These feed evidence_sources.credibility_weight and
# are multiplied into every stance weight, so they are deliberately conservative
# and each carries the rationale an auditor would ask for.
EVIDENCE_SOURCES: list[tuple[str, str, float, str]] = [
    ("who.int", "World Health Organization", 0.97,
     "UN public-health agency; primary source for global health guidance."),
    ("cdc.gov", "US Centers for Disease Control and Prevention", 0.96,
     "National public-health institute; primary source for US health data."),
    ("fda.gov", "US Food and Drug Administration", 0.96,
     "Federal regulator; primary source for drug and device safety."),
    # Subdomains need their own rows: the corpus join matches the full host after
    # stripping only "www.", so science.nasa.gov does NOT match a nasa.gov row and
    # would silently fall back to the 0.5 default weight.
    ("nasa.gov", "NASA", 0.97,
     "US space agency; primary source for its own mission records."),
    ("science.nasa.gov", "NASA Science", 0.97,
     "NASA's science directorate; primary source for its mission science."),
    ("climate.nasa.gov", "NASA Global Climate Change", 0.96,
     "NASA science communication built on peer-reviewed climate data."),
    ("ipcc.ch", "Intergovernmental Panel on Climate Change", 0.97,
     "UN scientific body; assessments synthesise peer-reviewed literature."),
    ("nih.gov", "US National Institutes of Health", 0.95,
     "Federal biomedical research agency."),
    ("nhs.uk", "UK National Health Service", 0.94,
     "National health service; clinical guidance for the UK public."),
    ("reuters.com", "Reuters", 0.88,
     "International wire service with a published corrections policy."),
    ("apnews.com", "Associated Press", 0.88,
     "International wire service with a published corrections policy."),
    ("factcheck.org", "FactCheck.org", 0.85,
     "Non-partisan fact-checker, Annenberg Public Policy Center."),
    ("snopes.com", "Snopes", 0.80,
     "Long-running fact-checking outlet; sources its claims."),
]

# (external_id, title, body, source_url)
#
# Bodies restate the misinformation claim's own vocabulary before refuting it.
# That is not padding: hybrid retrieval needs the claim's terms present to rank
# the document at all, and the stance model needs the negation to mark it as a
# contradiction rather than a match.
DOCUMENTS: list[tuple[str, str, str, str]] = [
    (
        "who-5g-covid",
        "WHO: 5G mobile networks do not spread COVID-19 (summary)",
        "Viruses cannot travel on radio waves or mobile networks. The claim that "
        "5G towers spread the coronavirus is false, and no evidence supports a "
        "link between 5G and COVID-19. COVID-19 is spread through respiratory "
        "droplets and aerosols when an infected person coughs, sneezes, speaks or "
        "breathes. COVID-19 has spread widely in many countries that have no 5G "
        "mobile network at all, which by itself refutes the claimed connection. "
        "5G networks use non-ionising radiofrequency energy at levels below "
        "international exposure guidelines; this radiation does not damage DNA "
        "and does not weaken the immune system. Claims that health authorities "
        "are hiding evidence about 5G and coronavirus are unfounded and have been "
        "repeatedly debunked.",
        "https://www.who.int/emergencies/diseases/novel-coronavirus-2019/advice-for-public/myth-busters",
    ),
    (
        "who-5g-health",
        "WHO: 5G radiation and health — no adverse effects established (summary)",
        "After reviewing the evidence, no adverse health effects have been "
        "causally linked to exposure from 5G or other wireless technologies at "
        "levels below international guidelines. 5G uses non-ionising radiation, "
        "which does not carry enough energy to ionise atoms or break chemical "
        "bonds in DNA. Claims that 5G towers cause coronavirus, cancer or immune "
        "suppression are not supported by the scientific evidence. Exposure "
        "levels from mobile network base stations are typically far below the "
        "limits set by international guidelines.",
        "https://www.who.int/news-room/questions-and-answers/item/radiation-5g-mobile-networks-and-health",
    ),
    (
        "cdc-vaccines-autism",
        "CDC: Vaccines do not cause autism (summary)",
        "Vaccines do not cause autism. Multiple large studies have found no link "
        "between vaccines and autism spectrum disorder, and no evidence that any "
        "vaccine ingredient causes autism. The 1998 study that first claimed a "
        "connection between the MMR vaccine and autism was retracted by the "
        "journal that published it after the findings were found to be false and "
        "the author was found to have acted unethically. Thimerosal, a "
        "mercury-containing preservative, does not cause autism; studies "
        "conducted after its removal from childhood vaccines showed no drop in "
        "autism diagnoses. The claim that vaccines cause autism is false and has "
        "been debunked by decades of research.",
        "https://www.cdc.gov/vaccinesafety/concerns/autism.html",
    ),
    (
        "who-vaccine-microchip",
        "Fact check: COVID-19 vaccines do not contain microchips or tracking devices (summary)",
        "COVID-19 vaccines do not contain microchips, tracking devices or "
        "nanotransmitters. No vaccine authorised anywhere contains a chip that "
        "can track a recipient's location. The claim that Bill Gates or any other "
        "individual is using vaccines to implant microchips in the population is "
        "false and has been repeatedly debunked. Vaccine ingredients are publicly "
        "listed by regulators, and mRNA vaccines contain messenger RNA, lipids, "
        "salts and sugars. mRNA vaccines do not alter human DNA; the mRNA does "
        "not enter the cell nucleus where DNA is kept, and it degrades within "
        "days of injection.",
        "https://www.reuters.com/article/factcheck-coronavirus-gates-idUSL1N2SO1WV",
    ),
    (
        "fda-bleach-mms",
        "FDA: Drinking bleach or Miracle Mineral Solution does not cure disease (summary)",
        "Drinking bleach, chlorine dioxide or so-called Miracle Mineral Solution "
        "does not cure COVID-19, cancer, autism, HIV or any other condition, and "
        "is dangerous. These products become industrial bleach when prepared as "
        "directed. Regulators have received reports of severe vomiting, diarrhoea, "
        "dangerously low blood pressure and acute liver failure after ingestion. "
        "No credible evidence supports the claim that ingesting bleach treats any "
        "illness, and these products are not approved for any use. Consumers "
        "should not drink these products.",
        "https://www.fda.gov/consumers/consumer-updates/danger-dont-drink-miracle-mineral-solution-or-similar-products",
    ),
    (
        "fda-ivermectin",
        "FDA: Ivermectin is not authorised to treat or prevent COVID-19 (summary)",
        "Ivermectin is not authorised or approved to treat or prevent COVID-19. "
        "It is approved for some parasitic worm infections and for certain skin "
        "conditions, not for viral infections. Taking large doses is dangerous and "
        "can cause nausea, vomiting, seizures, coma and death. Formulations "
        "intended for animals are not safe for humans and are highly "
        "concentrated. Claims that ivermectin is a proven cure for COVID-19 that "
        "authorities are suppressing are false; large randomised trials found no "
        "meaningful benefit for COVID-19 outcomes.",
        "https://www.fda.gov/consumers/consumer-updates/why-you-should-not-use-ivermectin-treat-or-prevent-covid-19",
    ),
    (
        "nasa-apollo-hoax",
        "NASA: The Apollo Moon landings were not faked (summary)",
        "The claim that the Apollo Moon landings were faked or filmed in a studio "
        "is false. Twelve astronauts walked on the Moon across six Apollo "
        "missions between 1969 and 1972, beginning with Apollo 11 on 20 July "
        "1969. They returned 382 kilograms of lunar samples whose composition "
        "cannot be reproduced on Earth and has been independently analysed by "
        "laboratories in many countries. Retroreflectors left on the lunar "
        "surface are still used today by observatories that bounce lasers off "
        "them to measure the Earth-Moon distance. Lunar orbiters have since "
        "photographed the landing sites, including descent stages and astronaut "
        "tracks. The flag appears to move because of a horizontal rod, not wind, "
        "and shadows are not parallel because of perspective and uneven terrain.",
        "https://www.nasa.gov/mission/apollo-11/",
    ),
    # The two climate documents below are deliberately written WITHOUT negation
    # words, unlike the rest of the corpus. Claims in this topic usually carry
    # the negation themselves ("global warming is a hoax", "climate data is
    # fabricated"), so positively-worded evidence is what the lexical fallback
    # reads as a contradiction. Wording them as rebuttals inverts the stance and
    # makes the pipeline agree that warming is a hoax — verified, not theoretical.
    (
        "nasa-climate-consensus",
        "NASA: Scientific consensus on human-caused climate change (summary)",
        "Multiple independent lines of evidence show the climate is warming and "
        "that human activity is the dominant cause of global warming. Studies of "
        "the peer-reviewed literature find that 97 percent or more of actively "
        "publishing climate scientists agree that warming trends over the past "
        "century are extremely likely caused by human activities. Atmospheric "
        "carbon dioxide has risen from about 280 parts per million before the "
        "industrial era to over 420 parts per million today, and the isotopic "
        "signature of that carbon identifies fossil fuel burning as its origin. "
        "Global surface temperature has risen by roughly 1.1 degrees Celsius "
        "since the late nineteenth century. Ice sheets in Greenland and "
        "Antarctica are losing mass, global sea level is rising, and Arctic sea "
        "ice extent is declining. Scientific organisations worldwide have issued "
        "statements endorsing this conclusion, and the temperature record is "
        "corroborated by independent teams working from separate datasets.",
        "https://science.nasa.gov/climate-change/scientific-consensus/",
    ),
    (
        "ipcc-ar6-attribution",
        "IPCC AR6: Human influence on the climate system (summary)",
        "The Sixth Assessment Report concluded it is unequivocal that human "
        "influence has warmed the atmosphere, ocean and land. Global surface "
        "temperature in 2011 to 2020 was about 1.1 degrees Celsius above 1850 to "
        "1900 levels. The report attributes the observed warming to greenhouse "
        "gas emissions from human activities, and finds that the observed trend "
        "exceeds what natural drivers such as solar and volcanic activity would "
        "produce alone. Each of the last four decades has been successively "
        "warmer than any decade that preceded it since 1850. Global warming is a "
        "measured trend supported by the attribution evidence, and continued "
        "emissions would drive further warming.",
        "https://www.ipcc.ch/report/ar6/wg1/",
    ),
    (
        "nasa-temperature-record",
        "NASA: The global temperature record (summary)",
        "The global temperature record is compiled independently by several "
        "scientific institutions, including NASA, NOAA, the UK Met Office and "
        "Berkeley Earth, each working from its own methods and station data. All "
        "of these independent records agree that global warming has continued and "
        "that the planet has warmed by roughly 1.1 degrees Celsius since the late "
        "nineteenth century. The ten warmest years in the instrumental record "
        "have all occurred since 2010. Scientists measure this warming with "
        "surface stations, weather balloons, ocean buoys and satellites, and the "
        "raw data underlying these records is published openly for anyone to "
        "reanalyse. Independent reanalyses by outside groups, including groups "
        "originally sceptical of the mainstream findings, have reproduced the "
        "same warming trend.",
        "https://climate.nasa.gov/vital-signs/global-temperature/",
    ),
    (
        "nhs-vaccines-autism",
        "NHS: There is no link between vaccines and autism (summary)",
        "There is no evidence of any link between the MMR vaccine and autism. "
        "Vaccines do not cause autism in children. Research involving millions of "
        "children across many countries has found no association between "
        "vaccination and autism spectrum disorder. The original 1998 paper "
        "claiming a link was found to be false, was retracted, and its author was "
        "struck off the medical register. Concerns that vaccines overwhelm a "
        "child's immune system are not supported by evidence. Declining "
        "vaccination rates driven by these false claims have allowed measles "
        "outbreaks to return.",
        "https://www.nhs.uk/conditions/vaccinations/why-vaccination-is-safe-and-important/",
    ),
    (
        "cdc-mrna-dna",
        "CDC: mRNA vaccines do not change your DNA (summary)",
        "mRNA COVID-19 vaccines do not change or interact with a recipient's DNA. "
        "The messenger RNA never enters the nucleus of the cell, which is where "
        "DNA is kept, so it cannot alter or modify a person's genetic material. "
        "The mRNA is broken down and cleared by the body within a few days of "
        "vaccination. The claim that mRNA vaccines alter human DNA, cause "
        "infertility, or make recipients magnetic is false and is not supported "
        "by any evidence. COVID-19 vaccines do not contain a live virus, "
        "microchips, tracking devices or fetal cells.",
        "https://www.cdc.gov/coronavirus/2019-ncov/vaccines/different-vaccines/mrna.html",
    ),
    (
        "nasa-apollo-evidence",
        "NASA: Independent evidence that Apollo astronauts landed on the Moon (summary)",
        "The Apollo Moon landings were not staged, and the claim that the landings "
        "were faked in a studio is false. Independent evidence does not rely on "
        "NASA's own footage. Lunar samples returned by Apollo have been studied by "
        "laboratories in many countries and contain minerals and isotopic ratios "
        "that are not found in terrestrial rocks and cannot be manufactured. "
        "Retroreflector arrays left by Apollo 11, 14 and 15 still return laser "
        "pulses fired from observatories today. The Lunar Reconnaissance Orbiter "
        "has photographed the Apollo landing sites, showing descent stages, "
        "experiment packages and astronaut footpaths. Independent tracking "
        "stations, including facilities outside the United States, followed the "
        "missions in real time, and the Soviet Union did not dispute the landings "
        "during the space race.",
        "https://science.nasa.gov/moon/",
    ),
    (
        "who-covid-pandemic-declaration",
        "WHO: COVID-19 characterised as a pandemic on 11 March 2020 (summary)",
        "The World Health Organization characterised COVID-19 as a pandemic on 11 "
        "March 2020, following sustained community transmission across multiple "
        "regions. A Public Health Emergency of International Concern had been "
        "declared on 30 January 2020. The disease is caused by the SARS-CoV-2 "
        "virus, first identified in Wuhan, China in December 2019. Transmission "
        "occurs mainly through respiratory particles released when an infected "
        "person breathes, speaks, coughs or sneezes.",
        "https://www.who.int/news/item/27-04-2020-who-timeline---covid-19",
    ),
    (
        "cdc-vaccine-effectiveness",
        "CDC: Measles vaccination is highly effective (summary)",
        "Two doses of the measles, mumps and rubella vaccine are about 97 percent "
        "effective at preventing measles, and one dose is about 93 percent "
        "effective. Widespread vaccination eliminated endemic measles "
        "transmission in the United States in 2000. Outbreaks since then have "
        "been driven largely by importation into communities with low "
        "vaccination coverage. Measles is not a harmless childhood illness: it is "
        "highly contagious and can cause pneumonia, encephalitis and death. "
        "Vaccine side effects are not common, and serious reactions are rare.",
        "https://www.cdc.gov/vaccines/vpd/mmr/public/index.html",
    ),
    (
        "snopes-earth-shape",
        "Fact check: The Earth is not flat (summary)",
        "The claim that the Earth is flat is false. The Earth is an oblate "
        "spheroid, slightly flattened at the poles. Photographs from spacecraft, "
        "satellite navigation systems, circumnavigation by sea and air, the "
        "curved shadow the Earth casts on the Moon during a lunar eclipse, and "
        "the way ships disappear hull-first over the horizon all demonstrate its "
        "shape. No credible evidence supports a flat Earth, and the claim that "
        "space agencies are faking imagery of a round Earth is unfounded.",
        "https://www.snopes.com/fact-check/is-the-earth-flat/",
    ),
    (
        "nasa-earth-shape",
        "NASA: The shape of the Earth is not flat (summary)",
        "The Earth is not flat. It is an oblate spheroid roughly 12,742 kilometres "
        "in diameter, slightly wider at the equator than pole to pole because of "
        "its rotation. This is not a matter of interpretation: satellites in orbit "
        "cannot maintain their trajectories around a flat plane, and the Global "
        "Positioning System could not resolve a location on a flat Earth. "
        "Travellers crossing time zones, aircraft flying polar routes, and the "
        "changing set of constellations visible from different latitudes are all "
        "inconsistent with a flat Earth. No credible evidence supports the flat "
        "Earth claim, and the assertion that space agencies fabricate imagery of a "
        "round Earth is false.",
        "https://science.nasa.gov/earth/",
    ),
]


async def seed_evidence_corpus(db: Any, tenant_id: str) -> int:
    """
    Populate the demo evidence corpus for one tenant.

    Idempotent and non-destructive: if the tenant already has ANY document of
    kind 'evidence' or 'article', this returns 0 and writes nothing. A tenant
    with a real corpus is therefore never touched.

    Returns the number of documents inserted.
    """
    existing = await db.fetch(
        tenant_id,
        "SELECT 1 FROM cerebro.documents WHERE kind IN ('evidence','article') LIMIT 1",
    )
    if existing:
        return 0

    for domain, publisher, weight, rationale in EVIDENCE_SOURCES:
        await db.fetch_unscoped(
            """
            INSERT INTO cerebro.evidence_sources (domain, publisher, credibility_weight, rationale)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (domain) DO NOTHING
            """,
            domain, publisher, weight, rationale,
        )

    meta = json.dumps({
        "curated": True,
        "note": "Condensed summary written for the demo evidence corpus; "
                "source_url points to the original public document.",
    })

    inserted = 0
    for external_id, title, body, url in DOCUMENTS:
        # $1::uuid — tenant_id arrives as a string and asyncpg will not coerce it
        # into a uuid column on its own.
        await db.execute(
            tenant_id,
            """
            INSERT INTO cerebro.documents
                (tenant_id, kind, external_id, title, body, source_url, meta)
            VALUES ($1::uuid, 'evidence', $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (tenant_id, kind, external_id) DO NOTHING
            """,
            str(tenant_id), external_id, title, body, url, meta,
        )
        inserted += 1

    log.info("seeded %d evidence documents for tenant %s", inserted, tenant_id)
    return inserted
