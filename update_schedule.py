import nfl_data_py as nfl
import pandas as pd
from os import path
from datetime import datetime

DATA_DIR = 'data_files/'
# Determine season year dynamically based on today's date:
# - If month is Sep(9)-Dec(12): season_year = current year
# - If month is Jan(1)-Aug(8): season_year = current year - 1
# This follows the convention that the season is named after the year it starts.
today = datetime.utcnow().date()
if today.month >= 9:
	season_year = today.year
else:
	season_year = today.year - 1

# Fetch schedule for current season
print(f"Fetching NFL schedule for {season_year} (determined from today's date: {today})...")
schedule = nfl.import_schedules([season_year])
print("Columns in schedule:", schedule.columns.tolist())

# Select and format columns for the schedule file
# Assuming columns: adjust based on actual
stadium_col = 'stadium' if 'stadium' in schedule.columns else 'venue'

# nflverse schedule data reports gameday (date, e.g. '2026-09-14') and
# gametime (local kickoff time, e.g. '20:15') as SEPARATE columns. Previously
# only gameday was kept, so every game_date downstream defaulted to midnight
# UTC -- which, once converted to US/Eastern for display, rolls back to the
# PREVIOUS calendar day and shows a fabricated kickoff time (e.g. a real
# Monday 8:15 PM ET game displaying as "Sunday 8:00 PM ET"). Combining the
# two into a real timestamp fixes this at the source.
time_col = next((c for c in ['gametime', 'game_time', 'kickoff_time'] if c in schedule.columns), None)

cols_to_pull = ['week', 'gameday', 'home_team', 'away_team', stadium_col]
if time_col:
    cols_to_pull.append(time_col)
else:
    print(f"⚠️  No kickoff-time column found in schedule data (columns: "
          f"{schedule.columns.tolist()}); game_date will default to midnight "
          f"UTC for each date, which can display as the wrong calendar day "
          f"once converted to a local timezone downstream.")

schedule_df = schedule[cols_to_pull].copy()

if time_col:
    # nflverse gametime is the LOCAL kickoff time at the venue, reported in US
    # Eastern per nflverse convention (not the home team's own timezone).
    # Combine date + time and localize as US/Eastern, then store as UTC so
    # every downstream consumer works with a single unambiguous instant.
    combined = schedule_df['gameday'].astype(str) + ' ' + schedule_df[time_col].astype(str)
    game_dt = pd.to_datetime(combined, errors='coerce')
    try:
        game_dt = game_dt.dt.tz_localize('US/Eastern', ambiguous='NaT', nonexistent='NaT')
        game_dt = game_dt.dt.tz_convert('UTC')
    except Exception as exc:
        print(f"⚠️  Could not localize kickoff times to US/Eastern ({exc}); "
              f"falling back to date-only (midnight UTC).")
        game_dt = pd.to_datetime(schedule_df['gameday']).dt.tz_localize('UTC')
    # Rows where the time was missing/unparseable still get the date at
    # midnight UTC rather than being dropped entirely.
    fallback_dt = pd.to_datetime(schedule_df['gameday']).dt.tz_localize('UTC')
    game_dt = game_dt.fillna(fallback_dt)
    schedule_df['date'] = game_dt.dt.strftime('%Y-%m-%d %H:%M:%S%z')
else:
    schedule_df['date'] = pd.to_datetime(schedule_df['gameday']).dt.strftime('%Y-%m-%d')

schedule_df['venue'] = schedule_df[stadium_col]
schedule_df['status'] = 'REG'
schedule_df = schedule_df[['week', 'date', 'home_team', 'away_team', 'venue', 'status']]

# Save to CSV
out_path = f"nfl_schedule_{season_year}.csv"
full_path = path.join(DATA_DIR, out_path)
schedule_df.to_csv(full_path, index=False)
print(f"Saved updated schedule to {full_path}")
print(f"Total games: {len(schedule_df)}")