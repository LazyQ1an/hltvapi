// ── v4.1: Complete TypeScript types aligned with backend Pydantic models ──

// ═══════════════════════════ Common / Shared ═══════════════════════════

export interface Team {
  id: number | null;
  name: string;
  logo: string | null;
}

export interface Player {
  id: number | null;
  name: string;
  real_name: string | null;
  photo: string | null;
  country: string | null;
}

export interface Event {
  id: number | null;
  name: string;
  logo: string | null;
}

export interface TeamRecord {
  wins: number;
  losses: number;
  draws: number;
  total_maps: number;
}

export interface PageInfo {
  current_page: number;
  total_pages: number;
  total_items: number | null;
  has_next: boolean;
  has_previous: boolean;
}

// ═══════════════════════════ Match Models ═══════════════════════════

export interface MatchTeam extends Team {
  score: number | null;
  record: TeamRecord | null;
}

export interface MatchOverview {
  id: number;
  team1: MatchTeam;
  team2: MatchTeam;
  event: Event;
  date: string | null;
  format: string | null;
  stage: string | null;
  is_live: boolean;
  is_upcoming: boolean;
  maps: string[];
}

export interface MatchMap {
  name: string;
  team1_score: number;
  team2_score: number;
  winner_team1: boolean | null;
  is_halftime: boolean;
}

export interface PlayerMatchStats {
  player: Player;
  team_is_team1: boolean;
  kills: number;
  deaths: number;
  assists: number;
  kd_diff: number;
  adr: number;
  kast: number | null;
  rating: number;
  headshots: number;
  hs_percentage: number;
  map_stats: Record<string, PlayerMatchStats> | null;
  is_mvp: boolean;
}

export interface MatchDemo {
  name: string;
  url: string | null;
  map_name: string | null;
  gotv: boolean;
  source: string | null;
}

export interface MatchDetail extends MatchOverview {
  detail_maps: MatchMap[];
  players_team1: PlayerMatchStats[];
  players_team2: PlayerMatchStats[];
  demos: MatchDemo[];
  event_id: number | null;
  vod_url: string | null;
  has_economy_data: boolean;
  has_live_betting: boolean;
  winner_team1: boolean | null;
}

// ═══════════════════════════ Team / Ranking Models ═══════════════════

export interface TeamRankingEntry {
  rank: number;
  team_id: number | null;
  name: string;
  logo: string | null;
  points: number;
  change: number | null;
  last_place: number | null;
  weeks_in_top30: number | null;
  country: string | null;
}

export interface TeamRanking {
  date: string | null;
  teams: TeamRankingEntry[];
}

export interface TeamRosterPlayer extends Player {
  join_date: string | null;
  is_current: boolean;
  maps_played: number | null;
}

export interface TeamDetail {
  id: number | null;
  name: string;
  logo: string | null;
  country: string | null;
  region: string | null;
  rank: number | null;
  rank_change: number | null;
  record: TeamRecord;
  earnings: string | null;
  current_lineup: TeamRosterPlayer[];
  recent_matches: MatchOverview[];
  upcoming_matches: MatchOverview[];
}

// ═══════════════════════════ Player Models ═══════════════════════════

export interface TopPlayer {
  rank: number;
  player: {
    id: number | null;
    name: string;
    country: string | null;
  } | null;
  team: Team | null;
  rating: number;
  maps_played: number;
  kills: number;
  deaths: number;
}

export interface TopPlayersResponse {
  players: TopPlayer[];
  period: string;
  start_date: string | null;
  end_date: string | null;
}

export interface PlayerDetailed {
  id: number | null;
  name: string;
  real_name: string | null;
  age: number | null;
  country: string | null;
  photo: string | null;
  twitter: string | null;
  twitch: string | null;
  team: Team | null;
  signature_weapon: string | null;
  total_kills: number;
  total_deaths: number;
  total_assists: number;
  total_maps: number;
  total_rounds: number;
  kd_ratio: number;
  kpr: number;
  dpr: number;
  ap: number;
  impact: number;
  adr: number;
  kast_pct: number;
  hltv_rating: number;
  hltv_rating_vs_top5: number | null;
  hltv_rating_vs_top10: number | null;
  hltv_rating_vs_top20: number | null;
  big_events_maps: number | null;
  big_events_rating: number | null;
  rating: number;
  kills: number;
  deaths: number;
  assists: number;
  kd_diff: number;
  kast: number | null;
  headshots: number;
  hs_percentage: number;
}

// ═══════════════════════════ Event Models ═══════════════════════════

export interface EventOverview {
  id: number;
  name: string;
  location: string | null;
  date_start: string | null;
  date_end: string | null;
  prize_pool: string | null;
  tier: string | null;
  is_ongoing: boolean;
}

export interface EventDetail {
  id: number;
  name: string;
  logo: string | null;
  location: string | null;
  date_start: string | null;
  date_end: string | null;
  prize_pool: string | null;
  tier: string | null;
  teams: Team[];
  streams: { platform: string; url: string }[];
}

// ═══════════════════════════ News Models ═══════════════════════════

export interface NewsArticle {
  id: number | null;
  title: string;
  url: string | null;
  date: string | null;
  category: string | null;
  comments_count: number;
}

// ═══════════════════════════ Search Models ═══════════════════════════

export interface SearchResults {
  players?: { name: string; team?: { name: string } | null; country?: string | null; id?: number | null }[];
  teams?: { name: string; rank?: number | null; id?: number | null }[];
  matches?: { team1?: { name: string } | null; team2?: { name: string } | null; id?: number }[];
  events?: { name: string; id?: number | null }[];
}

// ═══════════════════════════ Monitoring Models ═══════════════════════

export interface MonitoringStatus {
  status: string;
  mode?: string;
  rate_limiter?: {
    domains: Record<string, unknown>;
    hourly_used: number;
    hourly_limit: number;
    daily_used: number;
    daily_limit: number;
  };
  memory?: { percent: number; used_mb: number; total_mb: number };
  cpu_percent?: number;
}

// ═══════════════════════════ API Error Model ═══════════════════════════

export interface ApiError {
  error: string;
  detail?: string;
  status_code?: number;
  retry_after_seconds?: number;
}
