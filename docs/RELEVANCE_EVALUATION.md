# Checking the relevance rules against real sessions

The **Evaluate relevance rules** workflow loads entire past sessions, including
every bill text, into a throwaway database. It never touches the live one. Each
session's results go to a branch named `relevance-eval-<assembly>`, holding
`relevance.csv` (one row per bill) and the database itself.

To run it, list the assemblies in `.github/evaluate-request.txt` and push.

## Results for rules version 2026.10.2 (October 2026)

| Session | Bills | Texts read | Listed automatically (before → after) | Review queue (before → after) |
|---|---|---|---|---|
| 2023 (68th) | 1,006 | 3,679 | 23 → 22 | 11 → 6 |
| 2025 (69th) | 1,106 | 3,834 | 13 → 11 | 15 → 9 |

Every bill that news coverage and advocacy trackers identified as LGBTQ+-related
is still listed automatically:

- **2023:** HB 1205, 1249, 1254, 1281, 1297, 1301, 1332, 1333, 1473, 1474, 1489,
  1522 and 1526; SB 2199, 2231, 2260 and 2360; HCR 3010.
- **2025:** HB 1144, 1181, 1217 and 1430; SB 2244, 2264, 2307 and 2392;
  HCR 3013, SCR 4010 and HR 5001.

**False matches removed:**
- "pronounce" was read as "pronoun".
- Lower-case "aids" ("hearing aids", "aids or abets") was read as AIDS.
- HIV mentioned inside medical-marijuana condition lists.
- North Dakota's standard anti-discrimination list ("race, color, religion, sex,
  national origin…"), which appears in many unrelated bills.
- "Termination of parental rights" in family-law bills.

**Newly sent to review** (a person decides):
- Sex-education curriculum: 2023 HB 1265.
- Parental rights over health care and schooling: 2023 SB 2188.
- "Objectionable materials or performance" shown to minors: 2023 SB 2123.
- "Divisive / specified concepts": 2023 SB 2247.
- Harmful-to-minors platform liability: 2025 HB 1593.

**Scoring fix:**
- A rule now counts once per bill. Before, the same rule could count twice when
  it matched different words in different versions ("female" in one, "male" in
  another).
- A rule found in both the title and the summary also counts once.

Known limit: a bill that affects LGBTQ+ people without using any of these words
is still missed. The review queue and reviewer "include" decisions cover those.
