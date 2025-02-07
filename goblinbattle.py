import os
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO
from admin import admin_bp
import random
import os
import discord
from discord.ext import commands
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from typing import List, Dict, Optional

# Import your THEMES dictionary from the separate themes.py file
from themes import THEMES
from db_utils import DBHelper

# Flask App Setup
app = Flask(__name__)
socketio = SocketIO(app)
app.register_blueprint(admin_bp, url_prefix='/admin')
# TPG 01/18/25 - Replaced the json files with a new sql-lite database
db = DBHelper('goblin_battle.db')

def get_eastern_time():
    # This automatically handles DST transitions
    return datetime.now(ZoneInfo("America/New_York"))

# Prevent caching
@app.after_request
def add_header(response):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 0 seconds.
    """
    response.headers['X-UA-Compatible'] = 'IE=Edge,chrome=1'
    response.headers['Cache-Control'] = 'public, max-age=0, no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@dataclass
class Battle:
    player1: str
    player2: str
    machines: List[Dict]
    message_id: int
    channel_id: int
    battle_id: str
    resolved: bool = False
    time_started: str = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')

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

def get_current_month():
    return datetime.now().strftime("%Y-%m")

# Helper function to get machine details by name
def get_machine_details(name):
    machines = db.load_machines()
    for machine in machines:
        if machine['name'] == name:
            return db.get_machine_details(name)
    return None

@app.route('/')
def home():
    # Determine leaderboard type from query parameter
    leaderboard_type = request.args.get('leaderboard_type', 'all_time')
    # Load stats based on selected type
    player_stats = db.load_player_stats(leaderboard_type)
    sorted_leaderboard = sorted(player_stats.items(), key=lambda x: x[1]['wins'], reverse=True)
    leaderboard_with_rank = [
        {"rank": idx + 1, "player": player.split('#')[0], "stats": stats}
        for idx, (player, stats) in enumerate(sorted_leaderboard)
    ]

    # Dynamically get ongoing battles and recent battles
    recent_battles = db.load_battle_history()[:30]
    
    for battle in recent_battles:
        time = datetime.fromisoformat(battle['time'])
        battle['time'] = time.strftime('%m/%d/%Y %I:%M %p')

    # Get active battles from Discord bot's battle manager
    ongoing_battles = bot.battle_manager.get_all_active_battles()
    ongoing_battles_list = [
        {
            "player1": battle.player1, 
            "player2": battle.player2, 
            "machine_names": ', '.join([m['name'] for m in battle.machines]) if battle.machines else 'No machines'
        } 
        for battle in ongoing_battles
    ]

    # Get current monthly contest scoreboard
    current_monthly_data = db.get_current_month_data()
    monthly_scores = current_monthly_data.get("scores", [])
    monthly_scores_sorted = sorted(monthly_scores, key=lambda x: x['score'], reverse=True)
    for i, entry in enumerate(monthly_scores_sorted, start=1):
        entry['rank'] = i

    return render_template(
        'index.html',
        leaderboard=leaderboard_with_rank,
        leaderboard_type=leaderboard_type,
        ongoing_battles=ongoing_battles_list,
        battle_history=recent_battles,
        machine_of_the_month=current_monthly_data.get("machine_of_the_month", "None"),
        monthly_scores=monthly_scores_sorted
    )
    
@app.route('/submit_battle', methods=['POST'])
def submit_battle():
    winner = request.form['winner']
    loser = request.form['loser']

    if winner == loser:
        return redirect(url_for('home', error="Players cannot battle against themselves"))

    # Update stats
    db.update_stats(winner, loser)

    # Record battle history
    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    selected_machines = random.sample(active_machines, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    db.save_battle(winner, loser, selected_machine_details, current_time)

    # Emit refresh event
    socketio.emit('refresh', {'message': 'Battle stats updated'})

    return redirect(url_for('home'))

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.battle_manager = BattleManager()

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
    
    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    if len(active_machines) < 3:
        await ctx.send("There are fewer than 3 active machines available. Cannot start a goblinbattle.")
        return

    selected_machines = random.sample(active_machines, 3)
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

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New battle initiated'})
    
def transform_for_theme_filter(machine):
    try:
        # Convert to strings for any potential integer/null values
        return {
            "name": str(machine['name']) if machine['name'] else "",
            "details": {
                "release_date": str(machine['release_date']) if machine['release_date'] else "",
                "ramps": int(machine['ramps']) if machine['ramps'] else 0,
                "multiball": int(machine['multiball']) if machine['multiball'] else 0,
                "display_type": str(machine['display_type']) if machine['display_type'] else "",
                "type": str(machine['type']) if machine['type'] else "",
                "flippers": int(machine['flippers']) if machine['flippers'] else 0,
                "manufacturer": str(machine['manufacturer']) if machine['manufacturer'] else "",
                "generation": str(machine['generation']) if machine['generation'] else "",
                "cabinet": str(machine['cabinet']) if machine['cabinet'] else "",
                "release_count": int(machine['release_count']) if machine['release_count'] else 0
            },
            "tags": machine['tags'] if isinstance(machine['tags'], list) else [],
            "active": bool(machine['active'])
        }
    except (KeyError, TypeError, ValueError) as e:
        print(f"Error transforming machine {machine.get('name', 'Unknown')}: {str(e)}")
        # Return a safe default structure if transformation fails
        return {
            "name": "",
            "details": {
                "release_date": "", "ramps": 0, "multiball": 0,
                "display_type": "", "type": "", "flippers": 0,
                "manufacturer": "", "generation": "", "cabinet": "",
                "release_count": 0
            },
            "tags": [],
            "active": False
        }
    
@bot.command()
async def guestbattle(ctx, *, guest_name: str):
    """
    Usage: !guestbattle GuestName
    This initiates a battle between the command invoker and a guest (non-Discord user).
    """
    player1 = ctx.author
    player2_name = guest_name.strip()  # Remove any extra whitespace

    if player1.display_name.lower() == player2_name.lower():
        await ctx.send("You cannot battle against yourself.")
        return
    
    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    if len(active_machines) < 3:
        await ctx.send("There are fewer than 3 active machines available. Cannot start a battle.")
        return

    selected_machines = random.sample(active_machines, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    # Construct the battle initiation message
    message = f"**GUEST BATTLE INITIATED**\n\nMachines:\n"
    for i, machine in enumerate(selected_machine_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"
    message += f"\nOnly the battle initiator can report the winner."

    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=f"{player1.display_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id=f"player1_wins:{player1.id}:guest"
        )
    )
    view.add_item(
        discord.ui.Button(
            label=f"{player2_name} Wins", 
            style=discord.ButtonStyle.success, 
            custom_id=f"player2_wins:{player1.id}:guest"
        )
    )

    # Send message and get the message object back
    battle_message = await ctx.send(message, view=view)

    # Create battle in the manager
    battle = bot.battle_manager.create_battle(
        player1=player1.display_name,
        player2=player2_name,
        machines=selected_machine_details,
        message_id=battle_message.id,
        channel_id=ctx.channel.id
    )

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New guest battle initiated'})

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

    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    if not active_machines:
        await ctx.send("No active machines are available at the moment.")
        return

    selected_theme_name = None
    selected_machines_details = []
    max_tries = 10

    for _ in range(max_tries):
        theme_name = random.choice(list(THEMES.keys()))
        theme_filter = THEMES[theme_name]
        machines = db.load_machines()
        
        # Transform machines to match theme filter expectations
        transformed_machines = [transform_for_theme_filter(m) for m in machines]
        try:
            filtered = [m for m in transformed_machines if m['name'] in active_machines and theme_filter(m)]
        except (TypeError, KeyError) as e:
            print(f"Error during theme filtering: {str(e)}")
            filtered = []
            
        if len(filtered) >= 3:
            selected_theme_name = theme_name
            # Get the original machine details using the filtered names
            selected_machines_details = [
                next(machine for machine in machines if machine['name'] == filtered_machine['name'])
                for filtered_machine in random.sample(filtered, 3)
            ]
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

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New theme battle initiated'})
    
@bot.command()
async def leaderboard(ctx):
    player_stats = db.load_player_stats()
    sorted_leaderboard = sorted(player_stats.items(), key=lambda x: x[1]['wins'], reverse=True)
    message = "**Leaderboard**\n**Rank - Goblin, Wins/Losses**\n\n"
    for idx, (player, stats) in enumerate(sorted_leaderboard, start=1):
        message += f"{idx} - {player.split('#')[0]}, {stats['wins']}/{stats['losses']}\n"
    await ctx.send(message)

@bot.command()
async def ongoing(ctx):
    active_battles = bot.battle_manager.get_all_active_battles()
    
    if not active_battles:
        await ctx.send("No ongoing battles at the moment.")
        return

    message = "**Ongoing Battles**\n\n"
    for battle in active_battles:
        message += f"{battle.player1} vs {battle.player2}\nOn machines: {', '.join(m['name'] for m in battle.machines)}\n\n"
    await ctx.send(message)

@bot.command()
async def monthly(ctx, score: int):
    """
    Usage: !monthly 100000
    Submits a high score for the current machine of the month.
    """
    if score <= 0:
        await ctx.send("Score must be a positive integer.")
        return

    player_name = ctx.author.display_name
    
    # Get current monthly data
    current_data = db.get_current_month_data()
    
    # Update the score
    current_scores = current_data.get("scores", [])
    current_scores.append({"player": player_name, "score": score})
    
    current_data["scores"] = current_scores
    db.save_monthly_contest(current_data)
    
    await ctx.send(f"High score of {score:,} submitted for {player_name} on **{current_data.get('machine_of_the_month', 'None')}**!")
    
    # Emit refresh event
    socketio.emit('refresh', {'message': 'Monthly scoreboard updated'})

@bot.command()
async def commands(ctx):
    """
    Usage: !commands
    Shows all available commands and their descriptions.
    """
    help_text = """**Available Commands**

**Battle Commands**
`!goblinbattle @opponent` - Start a battle against another player with 3 random machines
`!themebattle @opponent` - Start a themed battle with machines matching a random theme
`!guestbattle GuestName` - Start a battle against someone not on Discord. Please encourage the guest to join the Goblins!

**Stats & Info**
`!leaderboard` - Show the current win/loss rankings
`!ongoing` - Display all active battles
`!monthly [score]` - Submit your score for the current Machine of the Month"""

    # Send as ephemeral message (only visible to command invoker)
    await ctx.send(help_text, ephemeral=True)

@bot.command()
async def resetmonth(ctx):
    """
    Usage: !resetmonth
    Only works for user 'applesaucesomer'.
    Resets the monthly leaderboard and picks a new machine of the month.
    """
    if ctx.author.display_name.lower() != 'applesaucesomer':
        await ctx.send("You do not have permission to use this command.")
        return

    current_data = db.get_current_month_data()
    current_data["month"] = get_current_month()
    
    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    if active_machines:
        current_data["machine_of_the_month"] = random.choice(active_machines)
    else:
        current_data["machine_of_the_month"] = "None"
    
    current_data["scores"] = []
    db.save_monthly_contest(current_data)

    await ctx.send(f"Monthly leaderboard reset! New Machine of the Month: **{current_data['machine_of_the_month']}**")
    
    # Emit refresh event
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

    # Update stats in database
    db.update_stats(winner, loser)

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

    # Save battle to database with current time
    completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
    db.save_battle(winner, loser, battle.machines, completion_time)

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
        # Modified to bind to all interfaces and use the PORT environment variable
        port = int(os.environ.get("PORT", 5000))
        socketio.run(
            app,
            host='0.0.0.0',  # Bind to all interfaces
            port=port,
            debug=False,  # Set to False in production
            use_reloader=False,
            allow_unsafe_werkzeug=True,  # Required for production with Werkzeug
        )

    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Run Discord bot
    # Discord Bot Configuration
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # Fetch the token from an environment variable
    if not TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN environment variable is not set")
    bot.run(TOKEN)
