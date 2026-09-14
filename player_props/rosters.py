"""
Current NFL roster / team-assignment data source, with nflreadpy as the
primary provider.

Historical box-score files (player_passing_stats.csv, player_rushing_stats.csv,
player_receiving_stats.csv) only tell us what team a player was on *the last
time they logged a stat*. For any player who has changed teams since their
last logged game (free agency, trade, waiver claim) — which is common in the
off-season and during the season — that historical `team` value is stale.

This module fetches the current-season roster so predict.py can:
  1. Correct the `team` shown for a player to their actual current team.
  2. Drop players from a team's "recent starters" pool if they are no longer
     on that roster (e.g. released, traded away).
  3. Recognize players on their new team even before they've logged a game
     there yet.

If nflreadpy is unavailable, this degrades gracefully to "no roster override"
— predict.py will fall back to the historical team value, same as before this
module existed.
"""
import pandas as pd
from pathlib import Path
from datetime import datetime

try:
    from nflreadpy import load_rosters as nflreadpy_load_rosters
except Exception:
    nflreadpy_load_rosters = None

DATA_DIR = Path(__file__).parent.parent / 'data_files'
ROSTER_CACHE_FILE = DATA_DIR / 'current_rosters.csv'


def _current_season():
    """Mirror the dynamic season-year logic used elsewhere in the pipeline:
    Sept-Dec counts as that year's season; Jan-Aug counts as the prior year's
    season (offseason / early calendar year still belongs to the season that
    started the previous September)."""
    now = datetime.now()
    return now.year if now.month >= 9 else now.year - 1


def _normalize_roster_df(raw):
    """Normalize nflreadpy's roster schema (Polars or pandas) down to just
    the columns we need: player name(s) and current team."""
    if raw is None:
        return None

    # nflreadpy typically returns Polars — convert to pandas if needed.
    if hasattr(raw, "to_pandas"):
        df = raw.to_pandas()
    else:
        df = raw

    if df is None or len(df) == 0:
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    name_col = next((c for c in ['player_name', 'full_name', 'display_name', 'name']
                      if c in df.columns), None)
    team_col = next((c for c in ['team', 'team_abbr', 'recent_team'] if c in df.columns), None)
    id_col = next((c for c in ['gsis_id', 'player_id'] if c in df.columns), None)

    if name_col is None or team_col is None:
        print(f"⚠️ Roster data missing expected columns; found: {list(df.columns)}")
        return None

    keep_cols = [c for c in [name_col, team_col, id_col] if c]
    out = df[keep_cols].copy()
    rename = {name_col: 'player_name', team_col: 'team'}
    if id_col:
        rename[id_col] = 'gsis_id'
    out = out.rename(columns=rename)
    out['team'] = out['team'].astype(str).str.upper().str.strip()
    out = out.dropna(subset=['player_name', 'team'])
    out = out.drop_duplicates(subset=['player_name'], keep='last')
    return out


def get_current_rosters(force_refresh=False):
    """
    Return a DataFrame with columns ['player_name', 'team'] (and 'gsis_id'
    when available) reflecting each player's CURRENT team for the current
    season. Returns None if no roster source is available — callers should
    treat that as "no override, fall back to historical team".
    """
    if not force_refresh and ROSTER_CACHE_FILE.exists():
        try:
            cached = pd.read_csv(ROSTER_CACHE_FILE)
            if not cached.empty:
                return cached
        except Exception:
            pass  # fall through and try to refresh

    if nflreadpy_load_rosters is None:
        print("⚠️ nflreadpy not available; cannot fetch current rosters. "
              "Team assignments will fall back to historical stat data, "
              "which may be stale for recently signed/traded players.")
        return None

    season = _current_season()
    try:
        raw = nflreadpy_load_rosters([season])
    except TypeError:
        # Some nflreadpy versions take a single int rather than a list.
        raw = nflreadpy_load_rosters(season)
    except Exception as exc:
        print(f"⚠️ nflreadpy roster fetch failed: {exc}")
        return None

    normalized = _normalize_roster_df(raw)
    if normalized is None or normalized.empty:
        print("⚠️ nflreadpy returned no usable roster rows.")
        return None

    try:
        normalized.to_csv(ROSTER_CACHE_FILE, index=False)
    except Exception as exc:
        print(f"⚠️ Could not cache roster data: {exc}")

    print(f"📊 Loaded current rosters: {len(normalized)} players ({season} season)")
    return normalized


def build_current_team_lookup(rosters_df):
    """Build a {player_name: current_team} dict for fast lookup. Returns an
    empty dict if rosters_df is None, so callers can use `.get(name, team)`
    without a None-check at every call site."""
    if rosters_df is None or rosters_df.empty:
        return {}
    return dict(zip(rosters_df['player_name'], rosters_df['team']))


def filter_active_on_team(player_names, team, current_team_lookup):
    """
    Given a list of player names historically associated with `team`, drop
    anyone whose CURRENT roster team is different (i.e. they've since left).
    If a player isn't found in current_team_lookup at all (lookup unavailable,
    or player not in this season's roster data for some other reason), they
    are kept — we only ever remove players we can positively confirm have
    moved on, never remove based on absence of data.
    """
    if not current_team_lookup:
        return player_names
    return [
        name for name in player_names
        if current_team_lookup.get(name, team) == team
    ]


def players_added_to_team(team, current_team_lookup, already_known):
    """
    Return current-roster players for `team` who are NOT already present in
    `already_known` (the historical-stats-derived starter list). This lets us
    surface a player under their new team even before they've logged a game
    there — important for someone like a free-agent signing in their first
    active week.
    """
    if not current_team_lookup:
        return []
    already_known_set = set(already_known)
    return [
        name for name, roster_team in current_team_lookup.items()
        if roster_team == team and name not in already_known_set
    ]