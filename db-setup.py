import sqlite3
import json
from datetime import datetime

def create_tables(cursor):
    # Create machines table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            active BOOLEAN DEFAULT true,
            pinside_id INTEGER,
            manufacturer VARCHAR(255),
            release_date DATE,
            type VARCHAR(50),
            generation VARCHAR(100),
            release_count VARCHAR(50),
            estimated_value VARCHAR(100),
            cabinet VARCHAR(50),
            display_type VARCHAR(50),
            players INTEGER,
            flippers INTEGER,
            ramps INTEGER,
            multiball INTEGER,
            ipdb VARCHAR(50),
            latest_software VARCHAR(100)
        )
    ''')

    # Create tags table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(50) NOT NULL UNIQUE
        )
    ''')

    # Create machine_tags junction table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS machine_tags (
            machine_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY (machine_id, tag_id),
            FOREIGN KEY (machine_id) REFERENCES machines(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        )
    ''')

    # Create players table with UNIQUE constraint on name
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL UNIQUE,
            custom_name VARCHAR(255),
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0
        )
    ''')

    # Create battles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            winner_id INTEGER,
            loser_id INTEGER,
            battle_time DATETIME NOT NULL,
            FOREIGN KEY (winner_id) REFERENCES players(id),
            FOREIGN KEY (loser_id) REFERENCES players(id)
        )
    ''')

    # Create battle_machines junction table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS battle_machines (
            battle_id INTEGER,
            machine_id INTEGER,
            position INTEGER,
            PRIMARY KEY (battle_id, machine_id),
            FOREIGN KEY (battle_id) REFERENCES battles(id),
            FOREIGN KEY (machine_id) REFERENCES machines(id)
        )
    ''')

    # Create monthly_contests table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monthly_contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month VARCHAR(7) NOT NULL,
            machine_id INTEGER,
            FOREIGN KEY (machine_id) REFERENCES machines(id)
        )
    ''')

    # Create monthly_scores table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monthly_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id INTEGER,
            player_id INTEGER,
            score BIGINT NOT NULL,
            FOREIGN KEY (contest_id) REFERENCES monthly_contests(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

def load_json_data():
    # Load machines
    with open('json/machines.json', 'r') as f:
        machines_data = json.load(f)
    
    # Load player stats
    with open('json/player_stats.json', 'r') as f:
        players_data = json.load(f)
    
    # Load battle history
    with open('json/battle_history.json', 'r') as f:
        battles_data = json.load(f)
    
    # Load monthly contest
    with open('json/monthly_contest.json', 'r') as f:
        monthly_data = json.load(f)
    
    return machines_data, players_data, battles_data, monthly_data

def populate_machines(cursor, machines_data):
    # First, collect all unique tags
    all_tags = set()
    for machine in machines_data['machines']:
        all_tags.update(machine['tags'])
    
    # Insert tags
    for tag in all_tags:
        cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag,))
    
    # Create a tag lookup dictionary
    cursor.execute('SELECT id, name FROM tags')
    tag_lookup = {name: tag_id for tag_id, name in cursor.fetchall()}
    
    # Insert machines and their tags
    for machine in machines_data['machines']:
        details = machine['details']
        cursor.execute('''
            INSERT INTO machines (
                name, active, pinside_id, manufacturer, release_date,
                type, generation, release_count, estimated_value,
                cabinet, display_type, players, flippers, ramps,
                multiball, ipdb, latest_software
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            machine['name'], machine['active'],
            details.get('pinside_id'), details.get('manufacturer'),
            details.get('release_date'), details.get('type'),
            details.get('generation'), details.get('release_count'),
            details.get('estimated_value'), details.get('cabinet'),
            details.get('display_type'), details.get('players'),
            details.get('flippers'), details.get('ramps'),
            details.get('multiball'), details.get('ipdb'),
            details.get('latest_software')
        ))
        
        machine_id = cursor.lastrowid
        
        # Insert machine tags
        for tag in machine['tags']:
            cursor.execute('''
                INSERT INTO machine_tags (machine_id, tag_id)
                VALUES (?, ?)
            ''', (machine_id, tag_lookup[tag]))

def populate_players(cursor, players_data):
    for name, stats in players_data.items():
        try:
            cursor.execute('''
                INSERT INTO players (name, custom_name, wins, losses)
                VALUES (?, ?, ?, ?)
            ''', (
                name,
                stats.get('custom_name'),
                stats.get('wins', 0),
                stats.get('losses', 0)
            ))
        except sqlite3.IntegrityError:
            print(f"Player {name} already exists. Skipping.")

def populate_battles(cursor, battles_data):
    # Create player name to ID lookup
    cursor.execute('SELECT id, name FROM players')
    player_lookup = {name: player_id for player_id, name in cursor.fetchall()}
    
    # Create machine name to ID lookup
    cursor.execute('SELECT id, name FROM machines')
    machine_lookup = {name: machine_id for machine_id, name in cursor.fetchall()}
    
    for battle in battles_data:
        cursor.execute('''
            INSERT INTO battles (winner_id, loser_id, battle_time)
            VALUES (?, ?, ?)
        ''', (
            player_lookup[battle['winner']],
            player_lookup[battle['loser']],
            battle['time']
        ))
        
        battle_id = cursor.lastrowid
        
        # Insert battle machines
        for position, machine in enumerate(battle['machines']):
            cursor.execute('''
                INSERT INTO battle_machines (battle_id, machine_id, position)
                VALUES (?, ?, ?)
            ''', (
                battle_id,
                machine_lookup[machine['name']],
                position
            ))

def populate_monthly_contest(cursor, monthly_data, machines_data):
    # Create machine name to ID lookup if not exists
    cursor.execute('SELECT id, name FROM machines')
    machine_lookup = {name: machine_id for machine_id, name in cursor.fetchall()}
    
    cursor.execute('''
        INSERT INTO monthly_contests (month, machine_id)
        VALUES (?, ?)
    ''', (
        monthly_data['month'],
        machine_lookup[monthly_data['machine_of_the_month']]
    ))
    
    contest_id = cursor.lastrowid
    
    # Create player name to ID lookup
    cursor.execute('SELECT id, name FROM players')
    player_lookup = {name: player_id for player_id, name in cursor.fetchall()}
    
    for score_entry in monthly_data.get('scores', []):
        cursor.execute('''
            INSERT INTO monthly_scores (contest_id, player_id, score)
            VALUES (?, ?, ?)
        ''', (
            contest_id,
            player_lookup[score_entry['player']],
            score_entry['score']
        ))

def main():
    # Connect to SQLite database (creates it if it doesn't exist)
    conn = sqlite3.connect('goblin_battle.db')
    cursor = conn.cursor()
    
    try:
        # Create all tables
        create_tables(cursor)
        
        # Load JSON data
        machines_data, players_data, battles_data, monthly_data = load_json_data()
        
        # Populate tables
        populate_machines(cursor, machines_data)
        populate_players(cursor, players_data)
        populate_battles(cursor, battles_data)
        populate_monthly_contest(cursor, monthly_data, machines_data)
        
        # Commit changes
        conn.commit()
        print("Database successfully created and populated!")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    main()