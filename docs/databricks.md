# easy-or-not on Databricks

`easy-or-not databricks deploy` runs the tool on a schedule in your Databricks workspace, lands the results in three Delta tables and creates a Genie space over them. This page lists what the tables hold and the kinds of question Genie can answer. The README has the commands and what they create.

Every table is replaced in full on each run, because the tool always looks at the whole window (the last 8 weeks of runs and 5 weeks of nights). Every column has a comment in the table itself, which is what Genie reads, so the descriptions below are the same ones.

## Tables

### `runs`

One row per run from Garmin, after leaving out walks, fragments under 10 minutes, and time the watch kept recording after the run ended.

| Column | Type | Meaning |
|---|---|---|
| `run_id` | STRING | Garmin activity id |
| `start` | TIMESTAMP | When the run started |
| `treadmill` | BOOLEAN | True for treadmill runs, where wrist pace is an estimate |
| `session` | BOOLEAN | True when at least 10 percent of the run was hard; false when it was meant to be easy |
| `easy_s` | DOUBLE | Seconds in the easy band, zones 1 and 2 |
| `middle_s` | DOUBLE | Seconds in the middle band, zone 3, the grey zone between easy and hard |
| `hard_s` | DOUBLE | Seconds in the hard band, zones 4 and 5 |
| `zone1_s` to `zone5_s` | DOUBLE | Seconds in each heart-rate zone, from your Garmin zones |
| `load` | DOUBLE | Training load, Edwards TRIMP: minutes in each heart-rate zone times the zone number |
| `efficiency` | DOUBLE | Metres per heartbeat in the easy band after a 5 minute warm-up; higher is better. Null when there was too little easy running to measure |

### `days`

One row per calendar day of overnight and resting data from Garmin. Overnight values belong to the morning you woke up. Null means the watch recorded nothing, not zero.

| Column | Type | Meaning |
|---|---|---|
| `day` | DATE | Calendar day |
| `hrv` | INT | Average overnight heart-rate variability, ms |
| `hrv_low` | INT | Bottom of the balanced HRV range Garmin sets for you, ms |
| `hrv_high` | INT | Top of the balanced HRV range Garmin sets for you, ms |
| `hrv_status` | STRING | HRV status as Garmin reports it, such as BALANCED |
| `sleep_s` | INT | Seconds asleep the night before |
| `sleep_score` | INT | Garmin sleep score, 0 to 100; under 60 is poor |
| `resting_hr` | INT | Resting heart rate, bpm |
| `readiness` | STRING | Readiness verdict, the estimate of easy-or-not and not Garmin Training Readiness. Only set on the most recent day |
| `hrv_rating` | STRING | Readiness rating of overnight HRV for this day: ok, watch or low. Only set on the readiness day |
| `resting_hr_rating` | STRING | The same for resting heart rate |
| `sleep_rating` | STRING | The same for sleep |
| `load_rating` | STRING | The same for the load ratio |

The readiness columns are only filled for the day the job ran, because the tool only assesses today. Over time that gives one assessed day per run of the job, so after a few weeks you can ask how often you were told to go easy.

### `weeks`

One row per Monday to Sunday week, including weeks without runs, from the first run in the window to the day the job ran.

| Column | Type | Meaning |
|---|---|---|
| `week_start` | DATE | Monday the week starts on |
| `easy_s` | DOUBLE | Seconds of running in the easy band, zones 1 and 2 |
| `middle_s` | DOUBLE | Seconds of running in the middle band, zone 3 |
| `hard_s` | DOUBLE | Seconds of running in the hard band, zones 4 and 5 |
| `load` | DOUBLE | Training load for the week, Edwards TRIMP, including runs too short for the bands |

The load ratio the tool reports (last 7 days against the average of the last 28) is not stored as a column, since it depends on the day you ask. Genie is told how to work it out from `weeks` and `runs`.

## Example questions for Genie

The space is given the same definitions the README uses, so these work without explanation:

- Which weeks did I train too hard?
- What share of my running time was easy each week?
- Which easy runs drifted most into the middle band?
- Is my efficiency on outdoor easy runs improving?
- On which days was my sleep score under 60?
- Is my resting heart rate higher after weeks with more load?
- How many runs a week do I do, and how long are they on average?
- Show my overnight HRV against my balanced range for the last month.
- What was my load ratio on each day I was told to go easy?

Genie answers with a query you can see, so if an answer looks odd, read the SQL. The most common cause is seconds where you expected minutes.

## Where things live

| What | Where |
|---|---|
| The rendered bundle | `~/.config/easy-or-not/databricks/` on your machine |
| Job, volume and Genie space | `/Workspace/Users/<you>/.bundle/easy-or-not/<target>/` |
| Cached activity files | `/Volumes/<catalog>/<schema>/easy_or_not_cache/` |
| Your Garmin key | secret scope `easy-or-not`, key `garmin-key` |

`easy-or-not databricks destroy` removes everything in the last three rows except the tables and the schema, which it leaves for you to drop.
