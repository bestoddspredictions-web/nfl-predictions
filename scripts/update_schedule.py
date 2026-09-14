import pandas as pd

df = pd.read_csv('data_files/nfl_games_historical.csv', sep='\t')
df_2025 = df[df['season']==2025]

# Include gametime alongside gameday -- date-only previously meant every
# game_date downstream defaulted to midnight UTC, which displays as the
# PREVIOUS calendar day once converted to US/Eastern for display.
cols = ['week', 'gameday', 'home_team', 'away_team', 'stadium', 'game_type']
has_time = 'gametime' in df_2025.columns
if has_time:
    cols.append('gametime')
schedule = df_2025[cols].copy()

if has_time:
    combined = schedule['gameday'].astype(str) + ' ' + schedule['gametime'].astype(str)
    game_dt = pd.to_datetime(combined, errors='coerce')
    try:
        game_dt = game_dt.dt.tz_localize('US/Eastern', ambiguous='NaT', nonexistent='NaT')
        game_dt = game_dt.dt.tz_convert('UTC')
    except Exception as exc:
        print(f"⚠️  Could not localize kickoff times to US/Eastern ({exc}); falling back to date-only.")
        game_dt = pd.to_datetime(schedule['gameday']).dt.tz_localize('UTC')
    fallback_dt = pd.to_datetime(schedule['gameday']).dt.tz_localize('UTC')
    game_dt = game_dt.fillna(fallback_dt)
    schedule['date'] = game_dt.dt.strftime('%Y-%m-%d %H:%M:%S%z')
else:
    print("⚠️  No 'gametime' column found; game_date will default to midnight UTC per date.")
    schedule['date'] = schedule['gameday']

schedule = schedule[['week', 'date', 'home_team', 'away_team', 'stadium', 'game_type']]
schedule.columns = ['week', 'date', 'home_team', 'away_team', 'venue', 'status']

schedule.to_csv('data_files/nfl_schedule_2025.csv', index=False)
print(f'✅ Saved {len(schedule)} games to nfl_schedule_2025.csv')
print(f'   Including playoff games: {len(schedule[schedule["status"] != "REG"])}')
print(f'   Weeks: {sorted(schedule["week"].unique())}')