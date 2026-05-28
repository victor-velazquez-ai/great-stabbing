# Incident Extraction Prompt

**Version:** v1 (2026-05-27)
**Used by:** manual Claude Desktop / Claude Code session, or `extraction/extract.py --mode=api`.
**Input:** `extraction/_inbox/candidate_articles_YYYY-MM.jsonl` (one article per line).
**Output:** `extraction/_outbox/extracted_incidents_YYYY-MM.jsonl` (one incident per line).

---

## Instructions for Claude

You are extracting structured records of **violent bodily-harm crimes** from European news articles. You will be given a JSONL file of candidate articles. For each article, decide whether it describes a specific real-world incident, and if so, output one structured record.

### Skip the article (no record) if it is:
- An opinion / editorial / analysis piece.
- A statistics / data story (e.g. "knife crime up 12% this year").
- A revisit of an old incident (court case, anniversary, retrospective).
- About a different country than the article's source country.
- About a fictional event (book, film, TV review).
- A general crime trend overview without a specific incident.

### Extract a record if it describes a specific incident of:
- Stabbing (knife or any sharp object — "sharp object" → `weapon: knife`).
- Shooting (firearm).
- Vehicle-ramming attack (deliberate, not traffic accident).
- Fatal beating (any blunt instrument or fists, with serious injury or death).
- Attempted homicide of the above types.

### Output schema (one JSON object per line)

```json
{
  "extracted": true,
  "skip_reason": null,
  "incident": {
    "date_incident": "2026-04-12 or null",
    "date_reported": "2026-04-13",
    "country": "DE",
    "city": "Mannheim",
    "weapon": "knife",
    "victim_count": 2,
    "victim_fatal": 1,
    "victim_sex_summary": "male",
    "victim_age_summary": "adult",
    "suspect_count": 1,
    "suspect_description_verbatim": "ein 27-jähriger Mann syrischer Staatsangehörigkeit",
    "suspect_origin_as_reported": "Syria",
    "sources": [
      {
        "url": "https://...",
        "outlet": "Mannheimer Morgen",
        "published_at": "2026-04-13T08:00:00Z",
        "quote_snippet": "...verbatim sentence from article..."
      }
    ]
  }
}
```

If extracting nothing:

```json
{ "extracted": false, "skip_reason": "opinion piece about crime trends", "incident": null }
```

### Rules — strict

1. **`suspect_description_verbatim` MUST be a direct quote from the article.** If the article does not describe the suspect, set to `null`. Do not paraphrase. Do not translate.

2. **`suspect_origin_as_reported` ONLY if the article explicitly states** the suspect's nationality, country of origin, residence permit status, or asylum status. Do NOT infer from names. Do NOT infer from physical descriptions. Do NOT infer from neighbourhood. If the article only says "a 27-year-old man", leave this `null`.

3. **`weapon`**: use the most specific category. If ambiguous ("sharp object", "blade"), use `knife`. If unclear, use `unknown`. Never guess.

4. **`victim_fatal`**: count only confirmed dead. "In critical condition" or "fighting for life" → not fatal yet, don't count.

5. **`date_incident`**: if the article uses a relative reference like "yesterday" or "Sunday night" relative to its publication date, compute the absolute date. If it says "this week" or similar without a specific day, leave `null`.

6. **`location_precision`**:
   - `exact` only if a specific address, intersection, or building is given.
   - `city` if a town/city is named.
   - `region` if only a Land/region/province is given.

7. **Verbatim quote in `sources[].quote_snippet`**: the single sentence from the article that establishes the incident (date + place + what happened). Keep it short, original-language.

8. **Output is one JSON object per article**, on its own line. No prose between objects. No markdown fences in the output file.

---

## Workflow for manual run

In Claude Desktop or Claude Code, with this repo open:

1. Read `extraction/_inbox/candidate_articles_YYYY-MM.jsonl`.
2. Apply this prompt's rules to each article in turn (batch internally if it helps).
3. Write the result to `extraction/_outbox/extracted_incidents_YYYY-MM.jsonl`.
4. Stamp the `extractor_version` as `manual-claude@prompt-v1`.
5. Run `python extraction/pipeline.py finalize YYYY-MM` to dedupe, geocode, score, and upsert to `data/parquet/incidents.parquet`.
6. Commit the inbox/outbox files + updated Parquet.
