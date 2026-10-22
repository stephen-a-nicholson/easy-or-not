# easy-or-not

Are your easy runs actually easy?

Most runners who stop improving are not lazy. They run almost everything at the same medium effort, too hard to recover from and too easy to make them faster. This tool reads your own runs and tells you how much of your time went where, how much of your "easy" running drifted into the middle, and whether you are getting faster at the same heart rate.

It works on FIT files you have exported, or straight from your account with a [Garmin Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api/) key. Everything runs on your machine. Your data and your key never leave it.

```
30 runs, heart-rate bands from your Garmin running zones
  easy below 154 bpm   middle 154-172 bpm   hard 173+ bpm

Where your running time went
  easy     47%  ##############................
  middle   27%  ########......................
  hard     25%  ########......................
  A common target is around 80% easy with the rest mostly hard.

Your easy runs (18 of 30, sessions excluded)
  44% of easy-run time was in the middle band.
    Thu 08 Oct    32 min    68% middle  (treadmill)
    Mon 14 Sep    32 min    65% middle  (outdoor)
    Sun 04 Oct    32 min    56% middle  (outdoor)

Same heart rate, faster? (outdoor easy runs only)
  1.40 -> 1.43 metres per heartbeat (+2.5%).
  Higher means you cover more ground for the same effort.
```

*(Example output from synthetic data.)*

## Install

Python 3.12 or newer.

```bash
uv tool install git+https://github.com/stephen-a-nicholson/easy-or-not
# or: pipx install git+https://github.com/stephen-a-nicholson/easy-or-not
```

## Use it with your Garmin account

1. In Garmin Connect, go to [Settings, Personal API Token](https://connect.garmin.com/app/settings/personalApiToken) and create a key. It is shown once.
2. Save it where Garmin's own client looks for it, so it never appears in your shell history:

   ```bash
   mkdir -p ~/.config/garmin
   pbpaste > ~/.config/garmin/connect-personal-api-key   # macOS; or paste it in with an editor
   chmod 600 ~/.config/garmin/connect-personal-api-key
   ```

3. Run it:

   ```bash
   easy-or-not garmin              # last 8 weeks
   easy-or-not garmin --days 90
   ```

Authentication is handled by Garmin's official [Python client](https://github.com/garmin/connect-personal-api-python), which also reads `GARMIN_PERSONAL_API_KEY` if you prefer an environment variable. Original activity files are cached in `~/.cache/easy-or-not`, so later runs only download new activities. Your heart-rate zones are read from your Garmin settings.

## Use it with exported files

In Garmin Connect on the web, open an activity, click the gear icon and choose **Export Original**. Point the tool at the files or the folder:

```bash
easy-or-not --max-hr 192 files ~/Downloads/runs/
```

Without the API there are no Garmin zones to read, so pass your max heart rate.

## What it measures

**Bands.** Easy, middle and hard come from your heart-rate zones. By default easy is zones 1 and 2, middle is zone 3, hard is zones 4 and 5. Garmin's default zones start zone 3 at 70% of max HR, which is stricter than the roughly 80% easy ceiling used in polarised-training research. If you are on Garmin's defaults and everything looks "middle", try `--easy-up-to 3`. With `--max-hr`, the bands are below 80%, 80 to 90%, and above 90% of max.

**Easy runs.** Any run with less than 10% of its time in the hard band. That is a session-free run, whatever you meant it to be.

**Efficiency.** Metres covered per heartbeat while in the easy band, ignoring the first five minutes while heart rate catches up. The tool compares the median of your first third of outdoor easy runs with your last third. It needs at least six.

**Pauses.** Gaps of more than 10 seconds between samples (traffic lights, a stopped watch) are not counted.

## Limits

- **Treadmill pace is an estimate.** Indoors, the watch works out speed from your wrist, so treadmill runs count towards time in zone but are left out of the efficiency trend.
- **Heart rate is only as good as the sensor.** Wrist HR can lock on to cadence, especially in the first few minutes or in the cold. A chest strap gives cleaner numbers.
- **Unverified against the live API.** The activity type and zone fields follow the shapes Garmin Connect has used for years and match Garmin's official client. If the Personal API returns something different, the tool says it found no runs or no zones rather than guessing. Please open an issue if that happens.
- **It describes, it does not coach.** "44% of your easy running was in the middle" is a fact about your data. What to do about it is up to you.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
uv run pytest -q
uv run ruff check .
```

The tests build real FIT files in memory, so nothing personal is committed. `*.fit`, `*.zip` and key files are git-ignored.

## Licence

MIT. Not affiliated with Garmin.
