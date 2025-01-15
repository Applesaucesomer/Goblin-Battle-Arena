from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO
import random
import json
import discord
from discord.ext import commands
from datetime import datetime

# Import your THEMES dictionary from the separate themes.py file
from themes import THEMES

# Flask App Setup
app = Flask(__name__)
socketio = SocketIO(app)

# Files for persistent storage
STATS_FILE = 'player_stats.json'
BATTLE_HISTORY_FILE = 'battle_history.json'
MACHINES_FILE = 'machines.json'
MONTHLY_CONTEST_FILE = 'monthly_contest.json'   # ADDED

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

# NEW: Helper functions to handle monthly contest data
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
    # For example: "2025-01"
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
    # Randomly pick machine of the month
    if active_machine_names:
        monthly_data["machine_of_the_month"] = random.choice(active_machine_names)
    else:
        monthly_data["machine_of_the_month"] = "None"
    # Reset or initialize scores
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
    recent_battles = sorted(battle_history[-5:], key=lambda x: x['time'], reverse=True)

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
    battle_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    selected_machines = random.sample(active_machine_names, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    battle_history.append({
        'winner': winner.split('#')[0],
        'loser': loser.split('#')[0],
        'time': battle_time,
        'machines': selected_machine_details
    })
    save_battle_history(battle_history)

    # Remove from ongoing battles
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
    # Player1 is the user who invoked the command
    player1 = ctx.author
    # Player2 is the tagged user
    player2 = opponent

    if player1 == player2:
        await ctx.send("You cannot battle against yourself.")
        return
    
    # Ensure we have at least 3 active machines
    if len(active_machine_names) < 3:
        await ctx.send("There are fewer than 3 active machines available. Cannot start a goblinbattle.")
        return

    # Randomly select 3 machines
    selected_machines = random.sample(active_machine_names, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    # Store battle info for later confirmation
    ctx.bot.battle_data = {
        'player1': player1.display_name,
        'player2': player2.display_name,
        'machines': selected_machine_details
    }

    # Add to ongoing battles
    ongoing_battles.append({
        'player1': player1.display_name,
        'player2': player2.display_name,
        'machines': selected_machine_details
    })

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New battle initiated'})

    # Construct the battle initiation message
    message = f"**BATTLE INITIATED**\n\nMachines:\n"
    for i, machine in enumerate(selected_machine_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"

    message += f"\nClick a button to confirm the winner."

    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=f"{player1.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id="player1_wins"
        )
    )
    view.add_item(
        discord.ui.Button(
            label=f"{player2.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id="player2_wins"
        )
    )

    await ctx.send(message, view=view)

# NEW DISCORD COMMAND: !themebattle <player1> <player2>
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
        # Pick a random theme
        theme_name = random.choice(list(THEMES.keys()))
        theme_filter = THEMES[theme_name]

        # Filter only active machines that match the theme
        filtered = [m for m in machines if m['name'] in active_machine_names and theme_filter(m)]

        # Check if we have enough machines
        if len(filtered) >= 3:
            selected_theme_name = theme_name
            # Randomly pick 3 from the filtered set
            selected_machines_details = random.sample(filtered, 3)
            break

    if not selected_theme_name:
        await ctx.send("Could not find a theme with at least 3 machines after several tries. Please try again.")
        return

    # Store battle info
    ctx.bot.battle_data = {
        'player1': player1.display_name,
        'player2': player2.display_name,
        'machines': selected_machines_details
    }

    # Add to ongoing battles
    ongoing_battles.append({
        'player1': player1.display_name,
        'player2': player2.display_name,
        'machines': selected_machines_details
    })

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New theme battle initiated'})

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
            custom_id="player1_wins"
        )
    )
    view.add_item(
        discord.ui.Button(
            label=f"{player2.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id="player2_wins"
        )
    )

    await ctx.send(message, view=view)
    
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

# NEW DISCORD COMMAND: !monthly <score>
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

# NEW DISCORD COMMAND: !resetmonth
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

@bot.event
async def on_interaction(interaction):
    custom_id = interaction.data.get('custom_id')

    if custom_id in ["player1_wins", "player2_wins"]:
        battle_data = bot.battle_data

        # Check if the battle is already resolved
        if battle_data.get("resolved", False):
            await interaction.response.send_message(
                "This battle has already been resolved.", ephemeral=True
            )
            return

        # Determine winner and loser
        winner = battle_data['player1'] if custom_id == "player1_wins" else battle_data['player2']
        loser = battle_data['player2'] if winner == battle_data['player1'] else battle_data['player1']

        # Update stats
        update_stats(winner, loser)

        # Mark battle as resolved
        battle_data["resolved"] = True

        # Edit the original message to disable buttons
        original_message = await interaction.message.channel.fetch_message(interaction.message.id)
        updated_view = discord.ui.View()
        updated_view.add_item(
            discord.ui.Button(label=f"{battle_data['player1']} Wins", style=discord.ButtonStyle.success, disabled=True)
        )
        updated_view.add_item(
            discord.ui.Button(label=f"{battle_data['player2']} Wins", style=discord.ButtonStyle.success, disabled=True)
        )
        await original_message.edit(view=updated_view)

        # Record battle history
        battle_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        battle_history.append({
            'winner': winner,
            'loser': loser,
            'time': battle_time,
            'machines': battle_data['machines']
        })
        save_battle_history(battle_history)

        # Remove from ongoing battles
        global ongoing_battles
        ongoing_battles = [
            b for b in ongoing_battles 
            if not ((b['player1'] == winner and b['player2'] == loser) or 
                    (b['player1'] == loser and b['player2'] == winner))
        ]

        # Emit refresh event to update all clients
        socketio.emit('refresh', {'message': 'Battle stats updated'})

        # Send a winner confirmation message (no buttons)
        await interaction.response.send_message(
            f"**{winner}** has won the battle! Machines played: {', '.join(m['name'] for m in battle_data['machines'])}. Statistics updated."
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
