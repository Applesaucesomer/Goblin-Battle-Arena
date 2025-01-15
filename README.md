# Goblin-Battle-Arena

## Overview

**What Does It Do?**

### Flask Web App:
- Displays player leaderboard (wins and losses).
- Shows recent battle history with timestamps and machines used.
- Shows ongoing battles in real-time.
- Displays and updates monthly contest scores and the “Machine of the Month.”

### Discord Bot:
- Provides commands to initiate battles and confirm winners.
- Tracks wins/losses for players (based on their Discord display names).
- Offers themed battles (machine selection is filtered by a chosen theme).
- Allows players to submit high scores for the monthly contest.
- Lets specific admins reset the monthly contest.

### Persistent Storage:
- Player stats are kept in `player_stats.json`.
- Battle history is in `battle_history.json`.
- Machines (each with tags, active/inactive status, etc.) are in `machines.json`.
- The monthly contest is tracked in `monthly_contest.json`.

---

## Discord Bot Commands

Below are the core bot commands (all start with `!` by default unless you change `command_prefix`):

### `!goblinbattle @opponent`
- Initiates a battle between the command invoker and the mentioned opponent.
- Randomly selects 3 active machines from `machines.json`.
- Prompts the Discord channel with buttons to confirm the winner.

### `!themebattle @opponent`
- Similar to `!goblinbattle`, but randomly picks a theme from `themes.py`.
- Filters machines by that theme (requires at least 3 matching, active machines).
- If it can’t find 3 after multiple tries, it aborts.

### `!monthly <score>`
- Records a high score for the current month and the “Machine of the Month.”
- If the user already had a score, it updates only if the new score is higher.
- Stored in `monthly_contest.json`.

### `!resetmonth`
- Restricted to a specific user (named 'applesaucesomer' in this code).
- Resets the monthly leaderboard, picks a new machine of the month, and saves changes in `monthly_contest.json`.

### `!leaderboard`
- Displays the current leaderboard in Discord (ranked by wins).

### `!ongoing`
- Lists all ongoing battles and the machines selected for them.
