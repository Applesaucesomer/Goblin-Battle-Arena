import sqlite3
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple

class DBHelper:
    def __init__(self, db_path: str = 'goblin_battle.db'):
        # Ensure the path is absolute
        self.db_path = os.path.join(os.path.dirname(__file__), db_path)

    def get_connection(self):
        return sqlite3.connect(self.db_path)


    def load_machines(self) -> List[Dict]:
        """Load all active machines with their tags and IDs"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.id, m.name, GROUP_CONCAT(t.name) as tags, m.active, m.pinside_id, m.manufacturer,
                    m.release_date, m.type, m.generation, m.release_count, m.estimated_value, 
                    m.cabinet, m.display_type, m.players, m.flippers, m.ramps, m.multiball, 
                    m.ipdb, m.latest_software
                FROM machines m
                LEFT JOIN machine_tags mt ON m.id = mt.machine_id
                LEFT JOIN tags t ON mt.tag_id = t.id
                WHERE m.active = true
                GROUP BY m.id
            ''')

            columns = [desc[0] for desc in cursor.description]
            machines = []
            for row in cursor.fetchall():
                machine_dict = dict(zip(columns, row))
                # Split tags and remove any empty strings
                machine_dict['tags'] = [tag.strip() for tag in machine_dict['tags'].split(',') if tag.strip()] if machine_dict['tags'] else []
                machines.append(machine_dict)
            return machines
        
    #Routine specfically for admin of machines    
    def load_all_machines(self) -> List[Dict]:
        """Load all machines (active and inactive) with their tags and IDs"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.id, m.name, GROUP_CONCAT(t.name) as tags, m.active, m.pinside_id, m.manufacturer,
                    m.release_date, m.type, m.generation, m.release_count, m.estimated_value, 
                    m.cabinet, m.display_type, m.players, m.flippers, m.ramps, m.multiball, 
                    m.ipdb, m.latest_software
                FROM machines m
                LEFT JOIN machine_tags mt ON m.id = mt.machine_id
                LEFT JOIN tags t ON mt.tag_id = t.id
                GROUP BY m.id
                ORDER BY m.name ASC
            ''')

            columns = [desc[0] for desc in cursor.description]
            machines = []
            for row in cursor.fetchall():
                machine_dict = dict(zip(columns, row))
                # Split tags and remove any empty strings
                machine_dict['tags'] = [tag.strip() for tag in machine_dict['tags'].split(',') if tag.strip()] if machine_dict['tags'] else []
                machines.append(machine_dict)
            return machines

    def get_machine_details(self, name: str) -> Optional[Dict]:
        """Get details for a specific machine by name"""
        machines = self.load_machines()
        for machine in machines:
            if machine['name'] == name:
                return machine
        return None

    def load_player_stats(self, time_filter: str = 'all_time') -> Dict:
        """
        Load player statistics with flexible time filtering
        
        Args:
        time_filter (str): 
        - 'all_time': Calculate stats from all battles
        - 'current_month': Calculate stats only for the current month
        
        Returns:
        Dict of player statistics
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Prepare base query with time filtering
            if time_filter == 'current_month':
                current_month = datetime.now().strftime("%Y-%m")
                query = '''
                    SELECT 
                        p.name, 
                        p.custom_name,
                        COUNT(CASE WHEN b.winner_id = p.id THEN 1 END) as total_wins,
                        COUNT(CASE WHEN b.loser_id = p.id THEN 1 END) as total_losses
                    FROM players p
                    LEFT JOIN battles b ON (
                        (b.winner_id = p.id OR b.loser_id = p.id) AND 
                        strftime('%Y-%m', b.battle_time) = ?
                    )
                    GROUP BY p.id, p.name, p.custom_name
                    ORDER BY total_wins DESC
                '''
                params = (current_month,)
            else:  # all_time
                query = '''
                    SELECT 
                        p.name, 
                        p.custom_name,
                        COUNT(CASE WHEN b.winner_id = p.id THEN 1 END) as total_wins,
                        COUNT(CASE WHEN b.loser_id = p.id THEN 1 END) as total_losses
                    FROM players p
                    LEFT JOIN battles b ON (b.winner_id = p.id OR b.loser_id = p.id)
                    GROUP BY p.id, p.name, p.custom_name
                    ORDER BY total_wins DESC
                '''
                params = ()
            
            cursor.execute(query, params)
            
            stats = {}
            for row in cursor.fetchall():
                name, custom_name, total_wins, total_losses = row
                stats[name] = {
                    'wins': total_wins,
                    'losses': total_losses
                }
                if custom_name:
                    stats[name]['custom_name'] = custom_name
            
            return stats

    def update_stats(self, winner: str, loser: str):
        """Update player statistics after a battle"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Ensure players exist, creating them if they don't
            for player in [winner, loser]:
                cursor.execute('''
                    INSERT OR IGNORE INTO players (name, wins, losses)
                    VALUES (?, 0, 0)
                ''', (player,))
            
            # Update winner stats
            cursor.execute('''
                UPDATE players
                SET wins = wins + 1
                WHERE name = ?
            ''', (winner,))
            
            # Update loser stats
            cursor.execute('''
                UPDATE players
                SET losses = losses + 1
                WHERE name = ?
            ''', (loser,))
            
            conn.commit()

    def load_battle_history(self) -> List[Dict]:
        """Load battle history with machine details"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    b.id,
                    w.name as winner,
                    l.name as loser,
                    b.battle_time,
                    GROUP_CONCAT(m.name) as machine_names,
                    GROUP_CONCAT(m.id) as machine_ids
                FROM battles b
                JOIN players w ON b.winner_id = w.id
                JOIN players l ON b.loser_id = l.id
                JOIN battle_machines bm ON b.id = bm.battle_id
                JOIN machines m ON bm.machine_id = m.id
                GROUP BY b.id
                ORDER BY b.battle_time DESC
            ''')
            
            battles = []
            for row in cursor.fetchall():
                battle_id, winner, loser, time, machine_names, machine_ids = row
                
                # Get full machine details
                machines = []
                for machine_id in machine_ids.split(','):
                    cursor.execute('SELECT * FROM machines WHERE id = ?', (machine_id,))
                    machine_data = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))
                    
                    # Get tags for this machine
                    cursor.execute('''
                        SELECT t.name 
                        FROM tags t 
                        JOIN machine_tags mt ON t.id = mt.tag_id 
                        WHERE mt.machine_id = ?
                    ''', (machine_id,))
                    tags = [tag[0] for tag in cursor.fetchall()]
                    
                    machines.append({
                        'id': machine_data['id'],
                        'name': machine_data['name'],
                        'tags': tags,
                        'active': bool(machine_data['active']),
                        'details': {
                            'manufacturer': machine_data['manufacturer'],
                            'release_date': machine_data['release_date'],
                            'type': machine_data['type'],
                            'generation': machine_data['generation'],
                            'release_count': machine_data['release_count'],
                            'estimated_value': machine_data['estimated_value'],
                            'cabinet': machine_data['cabinet'],
                            'display_type': machine_data['display_type'],
                            'players': machine_data['players'],
                            'flippers': machine_data['flippers'],
                            'ramps': machine_data['ramps'],
                            'multiball': machine_data['multiball'],
                            'ipdb': machine_data['ipdb'],
                            'latest_software': machine_data['latest_software']
                        }
                    })
                
                battles.append({
                    'winner': winner,
                    'loser': loser,
                    'time': time,
                    'machines': machines,
                    'machine_names': machine_names
                })
            
            return battles

    def get_or_create_player_id(self, cursor, player_name: str) -> int:
        """
        Check if a player exists in the database. If not, insert a new player.
        Returns the player's ID.
        """
        cursor.execute('SELECT id FROM players WHERE name = ?', (player_name,))
        result = cursor.fetchone()

        if result:
            return result[0]  # Player exists, return ID
        else:
            cursor.execute('INSERT INTO players (name, wins, losses) VALUES (?, 0, 0)', (player_name,))
            return cursor.lastrowid

    def save_battle(self, winner: str, loser: str, machines: List[Dict], time: str = None):
        """
        Save a battle result and update player statistics.
        """
        time = time or datetime.now(ZoneInfo("America/New_York")).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()

            winner_id = self.get_or_create_player_id(cursor, winner)
            loser_id = self.get_or_create_player_id(cursor, loser)

            # Check if this battle already exists
            cursor.execute('''
                SELECT id FROM battles 
                WHERE winner_id = ? AND loser_id = ? AND battle_time = ?
            ''', (winner_id, loser_id, time))
            
            existing_battle = cursor.fetchone()
            if existing_battle:
                # Battle already exists, don't try to save it again
                return existing_battle[0]

            cursor.execute('''
                INSERT INTO battles (winner_id, loser_id, battle_time)
                VALUES (?, ?, ?)
            ''', (winner_id, loser_id, time))

            battle_id = cursor.lastrowid

            # Use a set to track machine IDs we've already added
            added_machines = set()
            
            for position, machine in enumerate(machines, 1):
                # Ensure we have the machine id, try to extract it
                machine_id = machine.get('id')
                if not machine_id:
                    # Try to find the machine ID by name if 'id' is not provided
                    cursor.execute('SELECT id FROM machines WHERE name = ?', (machine['name'],))
                    result = cursor.fetchone()
                    if not result:
                        raise ValueError(f"Could not find machine ID for {machine['name']}")
                    machine_id = result[0]
                
                # Skip if we've already added this machine to this battle
                if machine_id in added_machines:
                    continue
                    
                cursor.execute('''
                    INSERT INTO battle_machines (battle_id, machine_id, position)
                    VALUES (?, ?, ?)
                ''', (battle_id, machine_id, position))
                
                added_machines.add(machine_id)

            conn.commit()
            return battle_id

    def get_current_month_data(self) -> Dict:
        """Get current month's contest data with detailed debugging"""
        current_month = datetime.now().strftime("%Y-%m")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # First, verify the monthly contests
            cursor.execute('''
                SELECT id, month, machine_id 
                FROM monthly_contests 
                WHERE month = ?
                ORDER BY id DESC 
                LIMIT 1
            ''', (current_month,))
            contest_row = cursor.fetchone()
            
            if not contest_row:
                print("No monthly contest found")
                return {"month": current_month, "machine_of_the_month": "None", "scores": []}
            
            contest_id, contest_month, machine_id = contest_row
            
            # Get machine name
            cursor.execute('SELECT name FROM machines WHERE id = ?', (machine_id,))
            machine_name = cursor.fetchone()[0]
            
            # Fetch all scores for this contest with detailed information
            cursor.execute('''
                SELECT 
                    p.name AS player_name, 
                    ms.score, 
                    ms.contest_id,
                    p.id AS player_id
                FROM monthly_scores ms
                JOIN players p ON ms.player_id = p.id
                WHERE ms.contest_id = ?
                ORDER BY ms.score DESC
            ''', (contest_id,))
            
            raw_scores = cursor.fetchall()
            
            # Process scores
            scores = []
            for raw_score in raw_scores:
                player_name, score, contest_id, player_id = raw_score
                scores.append({
                    "player": player_name,
                    "score": score
                })
            
            # Debug print
            print(f"Current Month: {contest_month}")
            print(f"Machine of the Month: {machine_name}")
            print(f"Total Scores Found: {len(scores)}")
            for score in scores:
                print(f"Player: {score['player']}, Score: {score['score']}")
            
            return {
                "month": contest_month,
                "machine_of_the_month": machine_name,
                "scores": scores
            }

    def save_monthly_contest(self, data: Dict):
        """Save or update monthly contest data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get machine ID
            cursor.execute('SELECT id FROM machines WHERE name = ?', (data['machine_of_the_month'],))
            machine_result = cursor.fetchone()
            if not machine_result:
                raise ValueError(f"Machine '{data['machine_of_the_month']}' does not exist.")
            machine_id = machine_result[0]
            
            # Check if an entry for the month and machine already exists
            cursor.execute('SELECT id FROM monthly_contests WHERE month = ? AND machine_id = ?', (data['month'], machine_id))
            contest_result = cursor.fetchone()

            if contest_result:
                # Entry exists, use its ID
                contest_id = contest_result[0]
            else:
                # Insert a new contest entry
                cursor.execute('''
                    INSERT INTO monthly_contests (month, machine_id)
                    VALUES (?, ?)
                ''', (data['month'], machine_id))
                contest_id = cursor.lastrowid
            
            # Update or insert scores
            for score_entry in data.get('scores', []):
                # Find the player ID
                cursor.execute('SELECT id FROM players WHERE name = ?', (score_entry['player'],))
                player_result = cursor.fetchone()
                
                if not player_result:
                    # Create player if not exists
                    cursor.execute('INSERT INTO players (name, wins, losses) VALUES (?, 0, 0)', (score_entry['player'],))
                    player_id = cursor.lastrowid
                else:
                    player_id = player_result[0]
                
                # Check if a score already exists for this player and contest
                cursor.execute('''
                    SELECT id FROM monthly_scores 
                    WHERE contest_id = ? AND player_id = ?
                ''', (contest_id, player_id))
                existing_score = cursor.fetchone()
                
                if existing_score:
                    # Update existing score if new score is higher
                    cursor.execute('''
                        UPDATE monthly_scores 
                        SET score = CASE 
                            WHEN ? > score THEN ? 
                            ELSE score 
                        END
                        WHERE contest_id = ? AND player_id = ?
                    ''', (score_entry['score'], score_entry['score'], contest_id, player_id))
                else:
                    # Insert new score if no existing score
                    cursor.execute('''
                        INSERT INTO monthly_scores (contest_id, player_id, score)
                        VALUES (?, ?, ?)
                    ''', (contest_id, player_id, score_entry['score']))
                
                # Debug print
                print(f"Saving score for {score_entry['player']}: {score_entry['score']}")
            
            conn.commit()
