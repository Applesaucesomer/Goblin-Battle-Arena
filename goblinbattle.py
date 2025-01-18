from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO
import random
import json
import discord
from discord.ext import commands
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional

# Import your THEMES dictionary from the separate themes.py file
from themes import THEMES

# Flask App Setup
app = Flask(__name__)
socketio = SocketIO(app)

# Files for persistent storage
STATS_FILE = 'json/player_stats.json'
BATTLE_HISTORY_FILE = 'json/battle_history.json'
MACHINES_FILE = 'json/machines.json'
MONTHLY_CONTEST_FILE = 'json/monthly_contest.json'

@dataclass
class Battle:
    player1: str
    player2: str
    machines: List[Dict]
    message_id: int
    channel_id: int
    battle_id: str
    resolved: bool = False
    time_started: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @classmethod
    def generate_id(cls):
        return datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(1000, 9999))

# TPG 01/18/25 - Added battle manager class to handle concurrent battles happening at the same time. 
# goblinbattle and themebattle have both been updated to use the new battle manager logic
# Also updated the interaction handler to use the battle manager for looking up and resolving battles
class BattleManager:
    def __init__(self):
        self.active_battles: Dict[int, Battle] = {}  # message_id -> Battle
    
    def create_battle(self, player1: str, player2: str, machines: List[Dict], 
                        message_id: int, channel_id: int) -> Battle:
            battle = Battle(
                player1=player1,
                player2=player2,
                machines=machines,
                message_id=message_id,
                channel_id=channel_id,
                battle_id=Battle.generate_id()
            )
            self.active_battles[message_id] = battle
            return battle
    
    def get_battle(self, message_id: int) -> Optional[Battle]:
        return self.active_battles.get(message_id)
    
    def resolve_battle(self, message_id: int, winner: str, loser: str) -> Optional[Battle]:
        battle = self.active_battles.get(message_id)
        if battle and not battle.resolved:
            battle.resolved = True
            # Remove from active battles
            del self.active_battles[message_id]
            return battle
        return None
    
    def get_all_active_battles(self) -> List[Battle]:
        return list(self.active_battles.values())

# Helper function to load stats
def load_stats():
    try:
        with open(STATS_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Helper function to save stats
def save_stats(stats):
    with open(STATS_FILE, 'w') as file:
        json.dump(stats, file)

# Helper function to load battle history
def load_battle_history():
    try:
        with open(BATTLE_HISTORY_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

# Helper function to save battle history
def save_battle_history(history):
    with open(BATTLE_HISTORY_FILE, 'w') as file:
        json.dump(history, file)

# Helper function to load machines
def load_machines():
    try:
        with open(MACHINES_FILE, 'r') as file:
            return json.load(file)['machines']
    except (FileNotFoundError, json.JSONDecodeError):
        return []

# Helper functions to handle monthly contest data
def load_monthly_contest():
    try:
        with open(MONTHLY_CONTEST_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_monthly_contest(data):
    with open(MONTHLY_CONTEST_FILE, 'w') as file:
        json.dump(data, file)

def get_current_month():
    return datetime.now().strftime("%Y-%m")

# Helper function to get machine details by name
def get_machine_details(name):
    for machine in machines:
        if machine['name'] == name:
            return machine
    return None

# Persistent data loaded at startup
player_stats = load_stats()
battle_history = load_battle_history()
machines = load_machines()
active_machine_names = [machine['name'] for machine in machines if machine.get('active', False)]
ongoing_battles = []

# Load monthly data
monthly_data = load_monthly_contest()

# Check if we need to pick a new machine for a new month
current_month_str = get_current_month()
if monthly_data.get("month") != current_month_str:
    monthly_data["month"] = current_month_str
    if active_machine_names:
        monthly_data["machine_of_the_month"] = random.choice(active_machine_names)
    else:
        monthly_data["machine_of_the_month"] = "None"
    monthly_data["scores"] = []
    save_monthly_contest(monthly_data)

@app.route('/')
def home():
    last_winner = request.args.get('last_winner', '')
    last_loser = request.args.get('last_loser', '')
    sorted_leaderboard = sorted(player_stats.items(), key=lambda x: x[1]['wins'], reverse=True)
    leaderboard_with_rank = [
        {"rank": idx + 1, "player": player.split('#')[0], "stats": stats}
        for idx, (player, stats) in enumerate(sorted_leaderboard)
    ]

    # Process machine names for ongoing battles
    for battle in ongoing_battles:
        battle['machine_names'] = ', '.join(
            m['name'] for m in battle['machines'] if m and 'name' in m
        )
        battle['player1'] = battle['player1'].split('#')[0]
        battle['player2'] = battle['player2'].split('#')[0]

    # Process machine names for recent battles
    for battle in battle_history:
        battle['machine_names'] = ', '.join(
            m['name'] for m in battle['machines'] if m and 'name' in m
        )
        battle['winner'] = battle['winner'].split('#')[0]
        battle['loser'] = battle['loser'].split('#')[0]

    # Sort last 5 battles by time descending
    # TPG 01/18/25 - Bumped the default amount of data send to the browser. By default 5 wouldn't allow you to view more battles. 
    # Setting to somehing more reasonable but not too much to slow down page load.
    recent_battles = sorted(battle_history[-30:], key=lambda x: x['time'], reverse=True)
    # Prepare monthly contest scoreboard
    monthly_scores = monthly_data.get("scores", [])
    monthly_scores_sorted = sorted(monthly_scores, key=lambda x: x['score'], reverse=True)
    for i, entry in enumerate(monthly_scores_sorted, start=1):
        entry['rank'] = i

    return render_template(
        'index.html',
        leaderboard=leaderboard_with_rank,
        last_winner=last_winner.split('#')[0],
        last_loser=last_loser.split('#')[0],
        ongoing_battles=ongoing_battles,
        battle_history=recent_battles,
        machine_of_the_month=monthly_data.get("machine_of_the_month", "None"),
        monthly_scores=monthly_scores_sorted
    )

@app.route('/submit_battle', methods=['POST'])
def submit_battle():
    winner = request.form['winner']
    loser = request.form['loser']

    if winner == loser:
        return redirect(url_for('home', error="Players cannot battle against themselves"))

    # Update stats
    update_stats(winner, loser)

    # Record battle history
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    battle_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    selected_machines = random.sample(active_machine_names, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    battle_history.append({
        'winner': winner.split('#')[0],
        'loser': loser.split('#')[0],
        'time': current_time,
        'machines': selected_machine_details
    })
    save_battle_history(battle_history)

    # Remove only this specific battle from ongoing battles
    global ongoing_battles
    ongoing_battles = [
        b for b in ongoing_battles
        if not ((b['player1'] == winner and b['player2'] == loser) or
                (b['player1'] == loser and b['player2'] == winner))
    ]

    # Emit refresh event to update all clients
    socketio.emit('refresh', {'message': 'Battle stats updated'})

    return redirect(url_for('home', last_winner=winner.split('#')[0], last_loser=loser.split('#')[0]))

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.battle_manager = BattleManager()

def update_stats(winner, loser):
    # Update stats for winner
    if winner not in player_stats:
        player_stats[winner] = {'wins': 0, 'losses': 0}
    player_stats[winner]['wins'] += 1

    # Update stats for loser
    if loser not in player_stats:
        player_stats[loser] = {'wins': 0, 'losses': 0}
    player_stats[loser]['losses'] += 1

    # Save updated stats
    save_stats(player_stats)

@bot.command()
async def goblinbattle(ctx, opponent: discord.Member):
    """
    Usage: !goblinbattle @opponent
    This initiates a battle between the command invoker and the opponent.
    """
    player1 = ctx.author
    player2 = opponent

    if player1 == player2:
        await ctx.send("You cannot battle against yourself.")
        return
    
    if len(active_machine_names) < 3:
        await ctx.send("There are fewer than 3 active machines available. Cannot start a goblinbattle.")
        return

    selected_machines = random.sample(active_machine_names, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    # Construct the battle initiation message
    # TPG 01/18/25 - Changed buttons to store participant ids for validation
    message = f"**BATTLE INITIATED**\n\nMachines:\n"
    for i, machine in enumerate(selected_machine_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"
    message += f"\nOnly battle participants can report the winner."

    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=f"{player1.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id=f"player1_wins:{player1.id}:{player2.id}"
        )
    )
    view.add_item(
        discord.ui.Button(
            label=f"{player2.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id=f"player2_wins:{player1.id}:{player2.id}"
        )
    )

    # Send message and get the message object back
    battle_message = await ctx.send(message, view=view)

    # Create battle in the manager
    battle = bot.battle_manager.create_battle(
        player1=player1.display_name,
        player2=player2.display_name,
        machines=selected_machine_details,
        message_id=battle_message.id,
        channel_id=ctx.channel.id
    )

    # Add to ongoing battles list for web display
    ongoing_battles.append({
        'player1': battle.player1,
        'player2': battle.player2,
        'machines': battle.machines,
        'battle_id': battle.battle_id
    })

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New battle initiated'})

@bot.command()
async def themebattle(ctx, opponent: discord.Member):
    """
    Usage: !themebattle @opponent
    Randomly selects a theme from THEMES, attempts to find 3 machines matching it.
    If fewer than 3 match, it picks a new theme (up to 10 tries),
    then starts a battle between the command invoker and the opponent.
    """
    player1 = ctx.author
    player2 = opponent

    if player1 == player2:
        await ctx.send("You cannot battle against yourself.")
        return

    if not active_machine_names:
        await ctx.send("No active machines are available at the moment.")
        return

    selected_theme_name = None
    selected_machines_details = []
    max_tries = 10

    for _ in range(max_tries):
        theme_name = random.choice(list(THEMES.keys()))
        theme_filter = THEMES[theme_name]
        filtered = [m for m in machines if m['name'] in active_machine_names and theme_filter(m)]

        if len(filtered) >= 3:
            selected_theme_name = theme_name
            selected_machines_details = random.sample(filtered, 3)
            break

    if not selected_theme_name:
        await ctx.send("Could not find a theme with at least 3 machines after several tries. Please try again.")
        return

    # Construct the battle initiation message
    message = f"**THEME BATTLE INITIATED: {selected_theme_name}**\n\nMachines:\n"
    for i, machine in enumerate(selected_machines_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"
    message += f"\nClick a button to confirm the winner."

    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=f"{player1.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id=f"player1_wins:{player1.id}:{player2.id}"
        )
    )
    view.add_item(
        discord.ui.Button(
            label=f"{player2.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id=f"player2_wins:{player1.id}:{player2.id}"
        )
    )

    # Send message and get the message object back
    battle_message = await ctx.send(message, view=view)

    # Create battle in the manager
    battle = bot.battle_manager.create_battle(
        player1=player1.display_name,
        player2=player2.display_name,
        machines=selected_machines_details,
        message_id=battle_message.id,
        channel_id=ctx.channel.id
    )

    # Add to ongoing battles list for web display
    ongoing_battles.append({
        'player1': battle.player1,
        'player2': battle.player2,
        'machines': battle.machines,
        'battle_id': battle.battle_id
    })

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New theme battle initiated'})

@bot.command()
async def leaderboard(ctx):
    sorted_leaderboard = sorted(player_stats.items(), key=lambda x: x[1]['wins'], reverse=True)
    message = "**Leaderboard**\n**Rank - Goblin, Wins/Losses**\n\n"
    for idx, (player, stats) in enumerate(sorted_leaderboard, start=1):
        message += f"{idx} - {player.split('#')[0]}, {stats['wins']}/{stats['losses']}\n"
    await ctx.send(message)

@bot.command()
async def ongoing(ctx):
    if not ongoing_battles:
        await ctx.send("No ongoing battles at the moment.")
        return

    message = "**Ongoing Battles**\n\n"
    for battle in ongoing_battles:
        message += f"{battle['player1']} vs {battle['player2']}\nOn machines: {', '.join(m['name'] for m in battle['machines'])}\n\n"
    await ctx.send(message)

@bot.command()
async def monthly(ctx, score: int):
    """
    Usage: !monthly 100000
    Submits a high score for the current machine of the month.
    """
    global monthly_data
    if score <= 0:
        await ctx.send("Score must be a positive integer.")
        return

    player_name = ctx.author.display_name
    
    # Load the latest monthly data again
    current_data = load_monthly_contest()
    
    # If the month changed since last load, re-pick machine, reset scores
    if current_data.get("month") != get_current_month():
        current_data["month"] = get_current_month()
        if active_machine_names:
            current_data["machine_of_the_month"] = random.choice(active_machine_names)
        else:
            current_data["machine_of_the_month"] = "None"
        current_data["scores"] = []
    
    # Add or update player score
    scores_list = current_data.get("scores", [])
    found = False
    for entry in scores_list:
        if entry["player"] == player_name:
            if score > entry["score"]:
                entry["score"] = score
            found = True
            break
    if not found:
        scores_list.append({"player": player_name, "score": score})
    
    current_data["scores"] = scores_list
    save_monthly_contest(current_data)
    
    # Force the monthly_data in memory to match
    monthly_data = current_data
    
    await ctx.send(f"High score of {score:,} submitted for {player_name} on **{current_data.get('machine_of_the_month', 'None')}**!")
    
    # Emit a Socket.IO refresh so the index page updates
    socketio.emit('refresh', {'message': 'Monthly scoreboard updated'})

@bot.command()
async def resetmonth(ctx):
    """
    Usage: !resetmonth
    Only works for user 'applesaucesomer'.
    Resets the monthly leaderboard and picks a new machine of the month.
    """
    # Check permission
    if ctx.author.display_name.lower() != 'applesaucesomer':
        await ctx.send("You do not have permission to use this command.")
        return

    global monthly_data
    current_data = load_monthly_contest()

    # Force the month to current, pick a new machine, reset scores
    current_data["month"] = get_current_month()
    if active_machine_names:
        current_data["machine_of_the_month"] = random.choice(active_machine_names)
    else:
        current_data["machine_of_the_month"] = "None"
    current_data["scores"] = []

    save_monthly_contest(current_data)
    monthly_data = current_data

    await ctx.send(f"Monthly leaderboard reset! New Machine of the Month: **{current_data['machine_of_the_month']}**")
    
    # Emit a Socket.IO refresh to update the web page immediately
    socketio.emit('refresh', {'message': 'Monthly leaderboard reset'})

#TPG 01/18/25 - Changed logic to check if the person who clicked the button is one of the participants of the battle
@bot.event
async def on_interaction(interaction):
    custom_id = interaction.data.get('custom_id')
    if not custom_id or not custom_id.startswith(('player1_wins:', 'player2_wins:')):
        return

    # Parse the custom_id to get player IDs
    button_type, player1_id, player2_id = custom_id.split(':')
    
    # Check if the user who clicked is one of the players
    if str(interaction.user.id) not in [player1_id, player2_id]:
        await interaction.response.send_message(
            "Only battle participants can report the winner.", 
            ephemeral=True
        )
        return

    message_id = interaction.message.id
    battle = bot.battle_manager.get_battle(message_id)
    
    if not battle:
        await interaction.response.send_message(
            "Could not find this battle. It may have already been resolved.",
            ephemeral=True
        )
        return

    if battle.resolved:
        await interaction.response.send_message(
            "This battle has already been resolved.",
            ephemeral=True
        )
        return

    # Determine winner and loser
    winner = battle.player1 if button_type == "player1_wins" else battle.player2
    loser = battle.player2 if winner == battle.player1 else battle.player1

    # Resolve the battle
    resolved_battle = bot.battle_manager.resolve_battle(message_id, winner, loser)
    if not resolved_battle:
        await interaction.response.send_message(
            "Error resolving battle.",
            ephemeral=True
        )
        return

    # Update stats
    update_stats(winner, loser)

    # Edit the original message to disable buttons
    original_message = await interaction.message.channel.fetch_message(message_id)
    updated_view = discord.ui.View()
    updated_view.add_item(
        discord.ui.Button(label=f"{battle.player1} Wins", style=discord.ButtonStyle.success, disabled=True)
    )
    updated_view.add_item(
        discord.ui.Button(label=f"{battle.player2} Wins", style=discord.ButtonStyle.success, disabled=True)
    )
    await original_message.edit(view=updated_view)

    # Record battle history with actual completion time
    completion_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    battle_history.append({
        'winner': winner,
        'loser': loser,
        'time': completion_time,
        'machines': battle.machines
    })
    save_battle_history(battle_history)

    # Remove only this specific battle from ongoing battles
    global ongoing_battles
    ongoing_battles = [
        b for b in ongoing_battles 
        if b.get('battle_id') != battle.battle_id
    ]

    # Emit refresh event
    socketio.emit('refresh', {'message': 'Battle stats updated'})

    # Send winner confirmation
    await interaction.response.send_message(
        f"**{winner}** has won the battle! Machines played: {', '.join(m['name'] for m in battle.machines)}. Statistics updated."
    )

if __name__ == '__main__':
    from threading import Thread

    # Run Flask app with SocketIO in a separate thread
    def run_flask():
        socketio.run(app, debug=True, use_reloader=False)

    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Run Discord bot
    bot.run('SECRET GOES HERE')