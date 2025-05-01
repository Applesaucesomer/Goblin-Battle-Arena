import os
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO
from admin import admin_bp
import logging
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
logging.basicConfig(filename='/tmp/discord_bot.log', level=logging.DEBUG)

# Flask App Setup
app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading')
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
    players: List[str]  # Now a list of all players instead of just player1/player2
    machines: List[Dict]
    message_id: int
    channel_id: int
    battle_id: str
    resolved: bool = False
    winner: Optional[str] = None
    loser: Optional[str] = None  # Last place player
    time_started: str = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')

    @classmethod
    def generate_id(cls):
        return datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(1000, 9999))

# TPG 01/18/25 - Added battle manager class to handle concurrent battles happening at the same time. 
# goblinbattle and themebattle have both been updated to use the new battle manager logic
# Also updated the interaction handler to use the battle manager for looking up and resolving battles
# TPG 03/21/25 - Updated battle manager to handle full multi-player battles
class BattleManager:
    def __init__(self):
        self.active_battles: Dict[int, Battle] = {}  # message_id -> Battle
    
    def create_battle(self, players: List[str], machines: List[Dict], 
                      message_id: int, channel_id: int) -> Battle:
        battle = Battle(
            players=players,
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
            battle.winner = winner
            battle.loser = loser
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
            "players": battle.players, 
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

@app.route('/test_socket')
def test_socket():
    """Test route to trigger a Socket.IO event"""
    print("Emitting test Socket.IO event")
    socketio.emit('refresh', {'message': 'Test refresh event from server'})
    return "Socket.IO test event emitted. Check your browser console."
    
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
    socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})

    return redirect(url_for('home'))

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.battle_manager = BattleManager()

@bot.command()
async def goblinbattle(ctx, *opponents: discord.Member):
    """
    Usage: !goblinbattle @opponent1 @opponent2 @opponent3
    This initiates a battle between the command invoker and up to 3 opponents.
    """
    if not opponents:
        await ctx.send("You need to specify at least one opponent. Usage: `!goblinbattle @player1 [@player2] [@player3]`")
        return
    
    # Limit to maximum 4 players total (initiator + 3 opponents)
    if len(opponents) > 3:
        await ctx.send("Maximum 4 players allowed (including you). Please limit to 3 opponents.")
        return
    
    # Create players list with initiator first
    players = [ctx.author]
    player_ids = [ctx.author.id]
    player_names = [ctx.author.display_name]
    
    # Add opponents, checking for duplicates
    for opponent in opponents:
        if opponent.id in player_ids:
            await ctx.send(f"{opponent.display_name} is already in this battle.")
            continue
        if opponent == ctx.author:
            await ctx.send("You cannot battle against yourself.")
            continue
        
        players.append(opponent)
        player_ids.append(opponent.id)
        player_names.append(opponent.display_name)
    
    if len(players) < 2:
        await ctx.send("You need at least one valid opponent to start a battle.")
        return
    
    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    if len(active_machines) < 3:
        await ctx.send("There are fewer than 3 active machines available. Cannot start a goblinbattle.")
        return

    selected_machines = random.sample(active_machines, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    # Construct the battle initiation message
    message = f"**BATTLE INITIATED ({len(players)} PLAYERS)**\n\nMachines:\n"
    for i, machine in enumerate(selected_machine_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"
    
    message += f"\nPlayers:\n"
    for i, player in enumerate(player_names, 1):
        message += f"{i}. {player}\n"
    
    message += f"\nOnly battle participants can report the winner."

    # Create a view with buttons for each possible winner
    view = discord.ui.View()
    
    # Create buttons for all players and last place
    for i, player in enumerate(players):
        # Winner button
        view.add_item(
            discord.ui.Button(
                label=f"{player.display_name} WINS", 
                style=discord.ButtonStyle.success, 
                custom_id=f"winner:{player.id}:{','.join(str(p.id) for p in players)}"
            )
        )
    
    # Add separate row of buttons for losers (last place)
    for i, player in enumerate(players):
        view.add_item(
            discord.ui.Button(
                label=f"{player.display_name} LAST PLACE", 
                style=discord.ButtonStyle.danger, 
                custom_id=f"loser:{player.id}:{','.join(str(p.id) for p in players)}"
            )
        )

    # Send message and get the message object back
    battle_message = await ctx.send(message, view=view)

    # Create battle in the manager
    battle = bot.battle_manager.create_battle(
        players=player_names,
        machines=selected_machine_details,
        message_id=battle_message.id,
        channel_id=ctx.channel.id
    )

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New battle initiated with ' + str(len(player_names)) + ' players'})
    
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
async def guestbattle(ctx, *args):
    """
    Usage: !guestbattle @discordUser1 @discordUser2 GuestName1 GuestName2
    This initiates a battle with a mix of Discord users and guests (non-Discord users).
    At least one guest (non-Discord user) is required.
    """
    if not args:
        await ctx.send("You need to specify at least one guest. Usage: `!guestbattle @discordUser1 GuestName1 GuestName2`")
        return
    
    # Initialize lists for Discord users and guests
    discord_users = []
    discord_ids = [ctx.author.id]  # Include the command initiator
    guest_names = []
    
    # Starting with the command initiator
    all_players = [ctx.author.display_name]
    
    # Parse arguments to identify Discord mentions vs guest names
    for arg in args:
        # Check if this is a Discord mention
        if arg.startswith('<@') and arg.endswith('>'):
            # Extract user ID from mention
            try:
                user_id = int(arg.strip('<@!>'))
                user = await bot.fetch_user(user_id)
                
                if user.id in discord_ids:
                    await ctx.send(f"{user.display_name} is already in this battle.")
                    continue
                
                if user == ctx.author:
                    await ctx.send("You're already included in the battle as the initiator.")
                    continue
                
                discord_users.append(user)
                discord_ids.append(user.id)
                all_players.append(user.display_name)
            except:
                # If it looks like a mention but can't be parsed, treat as guest name
                guest_name = arg
                if guest_name.lower() in [name.lower() for name in all_players]:
                    await ctx.send(f"Duplicate player name: {guest_name}")
                    continue
                
                guest_names.append(guest_name)
                all_players.append(guest_name)
        else:
            # This is a guest name
            guest_name = arg
            if guest_name.lower() in [name.lower() for name in all_players]:
                await ctx.send(f"Duplicate player name: {guest_name}")
                continue
            
            guest_names.append(guest_name)
            all_players.append(guest_name)
    
    # Ensure we have at least one guest
    if not guest_names:
        await ctx.send("You must include at least one guest (non-Discord user) in a guest battle.")
        return
    
    # Limit to maximum 4 players total
    if len(all_players) > 4:
        await ctx.send("Maximum 4 players allowed (including you). Please reduce the number of participants.")
        return
    
    # We need at least 2 players total
    if len(all_players) < 2:
        await ctx.send("You need at least one opponent to start a battle.")
        return
    
    active_machines = [m['name'] for m in db.load_machines() if m.get('active', False)]
    if len(active_machines) < 3:
        await ctx.send("There are fewer than 3 active machines available. Cannot start a battle.")
        return

    selected_machines = random.sample(active_machines, 3)
    selected_machine_details = [get_machine_details(name) for name in selected_machines]

    # Construct the battle initiation message
    message = f"**GUEST BATTLE INITIATED ({len(all_players)} PLAYERS)**\n\nMachines:\n"
    for i, machine in enumerate(selected_machine_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"
    
    message += f"\nPlayers:\n"
    for i, player in enumerate(all_players, 1):
        # Mark Discord users vs guests
        is_discord = player == ctx.author.display_name or player in [user.display_name for user in discord_users]
        player_type = "(Discord)" if is_discord else "(Guest)"
        message += f"{i}. {player} {player_type}\n"
    
    message += f"\nOnly the battle initiator can report the result."

    # Create a view with buttons for each player
    view = discord.ui.View()
    
    # Winner buttons
    for player_name in all_players:
        view.add_item(
            discord.ui.Button(
                label=f"{player_name} WINS", 
                style=discord.ButtonStyle.success, 
                custom_id=f"guest_winner:{ctx.author.id}:{player_name}"
            )
        )
    
    # Loser buttons (last place)
    for player_name in all_players:
        view.add_item(
            discord.ui.Button(
                label=f"{player_name} LAST PLACE", 
                style=discord.ButtonStyle.danger, 
                custom_id=f"guest_loser:{ctx.author.id}:{player_name}"
            )
        )

    # Send message and get the message object back
    battle_message = await ctx.send(message, view=view)

    # Create battle in the manager
    battle = bot.battle_manager.create_battle(
        players=all_players,
        machines=selected_machine_details,
        message_id=battle_message.id,
        channel_id=ctx.channel.id
    )

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New guest battle initiated with ' + str(len(all_players)) + ' players'})

@bot.command()
async def themebattle(ctx, *opponents: discord.Member):
    """
    Usage: !themebattle @opponent1 @opponent2 @opponent3
    Randomly selects a theme from THEMES, attempts to find 3 machines matching it.
    If fewer than 3 match, it picks a new theme (up to 10 tries),
    then starts a battle between the command invoker and up to 3 opponents.
    """
    if not opponents:
        await ctx.send("You need to specify at least one opponent. Usage: `!themebattle @player1 [@player2] [@player3]`")
        return
    
    # Limit to maximum 4 players total (initiator + 3 opponents)
    if len(opponents) > 3:
        await ctx.send("Maximum 4 players allowed (including you). Please limit to 3 opponents.")
        return
    
    # Create players list with initiator first
    players = [ctx.author]
    player_ids = [ctx.author.id]
    player_names = [ctx.author.display_name]
    
    # Add opponents, checking for duplicates
    for opponent in opponents:
        if opponent.id in player_ids:
            await ctx.send(f"{opponent.display_name} is already in this battle.")
            continue
        if opponent == ctx.author:
            await ctx.send("You cannot battle against yourself.")
            continue
        
        players.append(opponent)
        player_ids.append(opponent.id)
        player_names.append(opponent.display_name)
    
    if len(players) < 2:
        await ctx.send("You need at least one valid opponent to start a battle.")
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
    message = f"**THEME BATTLE INITIATED: {selected_theme_name} ({len(players)} PLAYERS)**\n\nMachines:\n"
    for i, machine in enumerate(selected_machines_details, 1):
        message += f"{i}. {machine['name']} ({', '.join(machine['tags'])})\n"
    
    message += f"\nPlayers:\n"
    for i, player in enumerate(player_names, 1):
        message += f"{i}. {player}\n"
    
    message += f"\nOnly battle participants can report the winner."

    # Create a view with buttons for winners and losers
    view = discord.ui.View()
    
    # Create buttons for all players as potential winners
    for i, player in enumerate(players):
        view.add_item(
            discord.ui.Button(
                label=f"{player.display_name} WINS", 
                style=discord.ButtonStyle.success, 
                custom_id=f"winner:{player.id}:{','.join(str(p.id) for p in players)}"
            )
        )
    
    # Add separate row of buttons for losers (last place)
    for i, player in enumerate(players):
        view.add_item(
            discord.ui.Button(
                label=f"{player.display_name} LAST PLACE", 
                style=discord.ButtonStyle.danger, 
                custom_id=f"loser:{player.id}:{','.join(str(p.id) for p in players)}"
            )
        )

    # Send message and get the message object back
    battle_message = await ctx.send(message, view=view)

    # Create battle in the manager
    battle = bot.battle_manager.create_battle(
        players=player_names,
        machines=selected_machines_details,
        message_id=battle_message.id,
        channel_id=ctx.channel.id
    )

    # Emit refresh event
    socketio.emit('refresh', {'message': 'New theme battle initiated with ' + str(len(player_names)) + ' players'})

    
@bot.command()
async def leaderboard(ctx, type_filter="monthly"):
    """
    Usage: !leaderboard [all]
    Shows the leaderboard with win/loss stats.
    Defaults to current month, use 'all' to see all-time stats.
    """
    # Determine which leaderboard to show
    if type_filter.lower() in ["all", "alltime", "all-time", "all_time"]:
        time_filter = "all_time"
        title = "All-Time Leaderboard"
    else:
        time_filter = "current_month"
        title = "Current Month Leaderboard"
    
    # Get player stats
    player_stats = db.load_player_stats(time_filter)
    sorted_leaderboard = sorted(player_stats.items(), key=lambda x: x[1]['wins'], reverse=True)
    
    if not sorted_leaderboard:
        await ctx.send(f"No players found for the {title.lower()}.")
        return
    
    # Format the leaderboard message
    message = f"**{title}**\n**Rank - Goblin, Wins/Losses**\n\n"
    for idx, (player, stats) in enumerate(sorted_leaderboard, start=1):
        message += f"{idx} - {player.split('#')[0]}, {stats['wins']}/{stats['losses']}\n"
        
        # Discord has a 2000 character limit per message, so break into chunks if needed
        if len(message) > 1800 and idx < len(sorted_leaderboard):
            await ctx.send(message)
            message = ""  # Reset for next chunk
    
    # Send remaining message
    if message:
        await ctx.send(message)

@bot.command()
async def monthly(ctx, *, score_input=None):
    """
    Usage: !monthly [score]
    If score is provided, submits a high score for the current machine of the month.
    If no score is provided, shows the current monthly leaderboard.
    """
    # Get current monthly data
    current_data = db.get_current_month_data()
    machine_name = current_data.get("machine_of_the_month", "None")
    
    # If no score provided, just show the monthly leaderboard
    if score_input is None:
        scores = current_data.get("scores", [])
        
        if not scores:
            await ctx.send(f"**Current Machine of the Month: {machine_name}**\n\nNo high scores submitted yet!")
            return
        
        # Sort scores from highest to lowest
        sorted_scores = sorted(scores, key=lambda x: x["score"], reverse=True)
        
        # Format the leaderboard message
        message = f"**Current Machine of the Month: {machine_name}**\n\n**Rank - Player, Score**\n"
        for i, entry in enumerate(sorted_scores, 1):
            message += f"{i}. {entry['player']} - {entry['score']:,}\n"
        
        await ctx.send(message)
        return
    
    # Process the score input - remove commas and convert to int
    try:
        # Remove all commas and convert to integer
        score_str = score_input.replace(',', '')
        score = int(score_str)
    except ValueError:
        await ctx.send("Invalid score format. Please provide a number (commas allowed).")
        return
    
    # Validate the score
    if score <= 0:
        await ctx.send("Score must be a positive number.")
        return

    player_name = ctx.author.display_name
    
    # Update the score
    current_scores = current_data.get("scores", [])
    current_scores.append({"player": player_name, "score": score})
    
    current_data["scores"] = current_scores
    db.save_monthly_contest(current_data)
    
    await ctx.send(f"High score of {score:,} submitted for {player_name} on **{machine_name}**!")
    
    # Emit refresh event
    socketio.emit('refresh', {'message': 'Monthly scoreboard updated for ' + player_name})

@bot.command()
async def commands(ctx):
    """
    Usage: !commands
    Shows all available commands and their descriptions.
    """
    help_text = """**Available Commands**

**Battle Commands**
`!goblinbattle @opponent1 [@opponent2] [@opponent3]` - Start a battle with up to 4 players using random machines
`!themebattle @opponent1 [@opponent2] [@opponent3]` - Start a themed battle with up to 4 players
`!guestbattle [GuestName] [@discordUser] [GuestName2]` - Start a battle with a mix of Discord users and guests

**Stats & Info**
`!leaderboard [all]` - Show the win/loss rankings (defaults to current month, use 'all' for all-time)
`!ongoing` - Display all active battles
`!monthly [score]` - View monthly leaderboard or submit your score for the current Machine of the Month"""

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
    socketio.emit('refresh', {'message': 'Monthly leaderboard reset with new machine: ' + current_data['machine_of_the_month']})
    
#TPG 01/18/25 - Changed logic to check if the person who clicked the button is one of the participants of the battle
#TPG 03/21/25 - Large refactor to handle battles up to 4 players
@bot.event
async def on_interaction(interaction):
    custom_id = interaction.data.get('custom_id')
    if not custom_id:
        return
    
    # Handle multiplayer battle winner/loser selections
    if custom_id.startswith(('winner:', 'loser:')):
        action_type, player_id, all_players_str = custom_id.split(':', 2)
        all_player_ids = all_players_str.split(',')
        
        # Check if the user who clicked is one of the players
        if str(interaction.user.id) not in all_player_ids:
            await interaction.response.send_message(
                "Only battle participants can report the result.", 
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

        # Find player name from ID
        selected_player = None
        for member in interaction.message.mentions:
            if str(member.id) == player_id:
                selected_player = member.display_name
                break
                
        # If we couldn't find it in mentions, try to get it from battle players
        if not selected_player and len(battle.players) > int(all_player_ids.index(player_id)):
            selected_player = battle.players[all_player_ids.index(player_id)]
        
        if not selected_player:
            await interaction.response.send_message(
                "Error identifying player.",
                ephemeral=True
            )
            return
        
        # For 2-player battles, automatically set the other player as winner/loser
        if len(battle.players) == 2:
            other_player = battle.players[1] if battle.players[0] == selected_player else battle.players[0]
            
            if action_type == "winner":
                winner = selected_player
                loser = other_player
                
                # Resolve the battle right away for 2-player battles
                resolved_battle = bot.battle_manager.resolve_battle(message_id, winner, loser)
                if not resolved_battle:
                    await interaction.response.send_message(
                        "Error resolving battle.",
                        ephemeral=True
                    )
                    return
                
                # Update stats in database - only winner gets +1 win, only loser gets +1 loss
                db.update_stats(winner, loser)
                
                # Edit the original message to disable buttons
                original_message = await interaction.message.channel.fetch_message(message_id)
                updated_view = discord.ui.View()
                for player_name in battle.players:
                    status = "WINNER" if player_name == winner else "LAST PLACE" if player_name == loser else ""
                    label = f"{player_name} {status}".strip()
                    style = discord.ButtonStyle.success if player_name == winner else discord.ButtonStyle.danger if player_name == loser else discord.ButtonStyle.secondary
                    updated_view.add_item(
                        discord.ui.Button(label=label, style=style, disabled=True)
                    )
                await original_message.edit(view=updated_view)
                
                # Save battle to database with current time
                completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
                battle_id = db.save_battle(winner, loser, battle.machines, completion_time)
                db.add_battle_players(battle_id, battle.players, winner, loser)
                
                # Emit refresh event
                socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})
                
                # Send confirmation
                await interaction.response.send_message(
                    f"**{winner}** has won the battle against **{loser}**!\nMachines played: {', '.join(m['name'] for m in battle.machines)}.\nStats updated."
                )
                return
            
            elif action_type == "loser":
                loser = selected_player
                winner = other_player
                
                # Resolve the battle right away for 2-player battles
                resolved_battle = bot.battle_manager.resolve_battle(message_id, winner, loser)
                if not resolved_battle:
                    await interaction.response.send_message(
                        "Error resolving battle.",
                        ephemeral=True
                    )
                    return
                
                # Update stats in database - only winner gets +1 win, only loser gets +1 loss
                db.update_stats(winner, loser)
                
                # Edit the original message to disable buttons
                original_message = await interaction.message.channel.fetch_message(message_id)
                updated_view = discord.ui.View()
                for player_name in battle.players:
                    status = "WINNER" if player_name == winner else "LAST PLACE" if player_name == loser else ""
                    label = f"{player_name} {status}".strip()
                    style = discord.ButtonStyle.success if player_name == winner else discord.ButtonStyle.danger if player_name == loser else discord.ButtonStyle.secondary
                    updated_view.add_item(
                        discord.ui.Button(label=label, style=style, disabled=True)
                    )
                await original_message.edit(view=updated_view)
                
                # Save battle to database with current time
                completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
                battle_id = db.save_battle(winner, loser, battle.machines, completion_time)
                db.add_battle_players(battle_id, battle.players, winner, loser)
                
                # Emit refresh event
                socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})
                
                # Send confirmation
                await interaction.response.send_message(
                    f"**{loser}** got last place, so **{winner}** has won the battle!\nMachines played: {', '.join(m['name'] for m in battle.machines)}.\nStats updated."
                )
                return
        
        # For battles with more than 2 players, continue with the existing logic
        if action_type == "winner":
            winner = selected_player
            # Ask for loser in followup message
            await interaction.response.send_message(
                f"{winner} has been recorded as the winner! Please also click who got last place.",
                ephemeral=False
            )
            # We don't resolve the battle yet, waiting for loser selection
            battle.winner = winner
            return
        
        elif action_type == "loser":
            loser = selected_player
            
            # If we already have a winner, we can resolve the battle
            if battle.winner:
                winner = battle.winner
                
                # Resolve the battle
                resolved_battle = bot.battle_manager.resolve_battle(message_id, winner, loser)
                if not resolved_battle:
                    await interaction.response.send_message(
                        "Error resolving battle.",
                        ephemeral=True
                    )
                    return
                
                # Update stats in database - only winner gets +1 win, only loser gets +1 loss
                db.update_stats(winner, loser)
                
                # Edit the original message to disable buttons
                original_message = await interaction.message.channel.fetch_message(message_id)
                updated_view = discord.ui.View()
                for player_name in battle.players:
                    status = "WINNER" if player_name == winner else "LAST PLACE" if player_name == loser else ""
                    label = f"{player_name} {status}".strip()
                    style = discord.ButtonStyle.success if player_name == winner else discord.ButtonStyle.danger if player_name == loser else discord.ButtonStyle.secondary
                    updated_view.add_item(
                        discord.ui.Button(label=label, style=style, disabled=True)
                    )
                await original_message.edit(view=updated_view)
                
                # Save battle to database with current time
                completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
                battle_id = db.save_battle(winner, loser, battle.machines, completion_time)
                db.add_battle_players(battle_id, battle.players, winner, loser)
                
                # Emit refresh event
                socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})
                
                # Send confirmation
                await interaction.response.send_message(
                    f"**{winner}** has won the battle, and **{loser}** got last place!\nMachines played: {', '.join(m['name'] for m in battle.machines)}.\nStats updated."
                )
            else:
                # We have the loser but no winner yet
                battle.loser = loser
                await interaction.response.send_message(
                    f"{loser} has been recorded as last place! Please also click who won.",
                    ephemeral=False
                )
    
    # Handle guest battle winner/loser selections with similar improvements for 2-player battles
    elif custom_id.startswith(('guest_winner:', 'guest_loser:')):
        action_type, initiator_id, player_name = custom_id.split(':', 2)
        
        # For guest battles, only the initiator can report results
        if str(interaction.user.id) != initiator_id:
            await interaction.response.send_message(
                "Only the battle initiator can report the result for guest battles.", 
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
          
        # For 2-player guest battles, automatically set the other player
        if len(battle.players) == 2:
            other_player = battle.players[1] if battle.players[0] == player_name else battle.players[0]
            
            if action_type == "guest_winner":
                winner = player_name
                loser = other_player
                
                # Resolve the battle right away for 2-player battles
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
                for player_name in battle.players:
                    status = "WINNER" if player_name == winner else "LAST PLACE" if player_name == loser else ""
                    label = f"{player_name} {status}".strip()
                    style = discord.ButtonStyle.success if player_name == winner else discord.ButtonStyle.danger if player_name == loser else discord.ButtonStyle.secondary
                    updated_view.add_item(
                        discord.ui.Button(label=label, style=style, disabled=True)
                    )
                await original_message.edit(view=updated_view)
                
                # Save battle to database with current time
                completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
                battle_id = db.save_battle(winner, loser, battle.machines, completion_time)
                db.add_battle_players(battle_id, battle.players, winner, loser)
                
                # Emit refresh event
                socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})
                
                # Send confirmation
                await interaction.response.send_message(
                    f"**{winner}** has won the battle against **{loser}**!\nMachines played: {', '.join(m['name'] for m in battle.machines)}.\nStats updated."
                )
                return
            
            elif action_type == "guest_loser":
                loser = player_name
                winner = other_player
                
                # Resolve the battle right away for 2-player battles
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
                for player_name in battle.players:
                    status = "WINNER" if player_name == winner else "LAST PLACE" if player_name == loser else ""
                    label = f"{player_name} {status}".strip()
                    style = discord.ButtonStyle.success if player_name == winner else discord.ButtonStyle.danger if player_name == loser else discord.ButtonStyle.secondary
                    updated_view.add_item(
                        discord.ui.Button(label=label, style=style, disabled=True)
                    )
                await original_message.edit(view=updated_view)
                
                # Save battle to database with current time
                completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
                battle_id = db.save_battle(winner, loser, battle.machines, completion_time)
                db.add_battle_players(battle_id, battle.players, winner, loser)
                
                # Emit refresh event
                socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})
                
                # Send confirmation
                await interaction.response.send_message(
                    f"**{loser}** got last place, so **{winner}** has won the battle!\nMachines played: {', '.join(m['name'] for m in battle.machines)}.\nStats updated."
                )
                return
            
        # For battles with more than 2 players, continue with existing logic
        if action_type == "guest_winner":
            winner = player_name
            battle.winner = winner
            await interaction.response.send_message(
                f"{winner} has been recorded as the winner! Please also click who got last place.",
                ephemeral=False
            )
            return
            
        elif action_type == "guest_loser":
            loser = player_name
            battle.loser = loser
            
            # If we already have a winner, we can resolve the battle
            if battle.winner:
                winner = battle.winner
                
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
                for player_name in battle.players:
                    status = "WINNER" if player_name == winner else "LAST PLACE" if player_name == loser else ""
                    label = f"{player_name} {status}".strip()
                    style = discord.ButtonStyle.success if player_name == winner else discord.ButtonStyle.danger if player_name == loser else discord.ButtonStyle.secondary
                    updated_view.add_item(
                        discord.ui.Button(label=label, style=style, disabled=True)
                    )
                await original_message.edit(view=updated_view)
                
                # Save battle to database with current time
                completion_time = get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')
                battle_id = db.save_battle(winner, loser, battle.machines, completion_time)
                db.add_battle_players(battle_id, battle.players, winner, loser)
                
                # Emit refresh event
                socketio.emit('refresh', {'message': 'Battle stats updated: ' + winner + ' won against ' + loser})
                
                # Send confirmation
                await interaction.response.send_message(
                    f"**{winner}** has won the battle, and **{loser}** got last place!\nMachines played: {', '.join(m['name'] for m in battle.machines)}.\nStats updated."
                )
            else:
                # We have the loser but no winner yet
                await interaction.response.send_message(
                    f"{loser} has been recorded as last place! Please also click who won.",
                    ephemeral=False
                )
                
                
if __name__ == '__main__':
    from threading import Thread
    
    db.ensure_current_month_game()
    logging.info("Starting Flask thread")

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
    logging.info("Starting Discord bot")
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # Fetch the token from an environment variable
    if not TOKEN:
        logging.error("DISCORD_BOT_TOKEN not set")
        raise ValueError("DISCORD_BOT_TOKEN environment variable is not set")
    try:
        logging.info("Running bot with token starting with: " + TOKEN[:5] + "...")
        bot.run(TOKEN)
    except Exception as e:
        logging.error(f"Discord bot error: {str(e)}")
