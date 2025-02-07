from flask import Blueprint, render_template, request, jsonify
from db_utils import DBHelper

admin_bp = Blueprint('admin', __name__, template_folder='templates/admin')
db = DBHelper()  # Initialize DBHelper

@admin_bp.route('/')
def admin_dashboard():
    """Render the admin page for managing machines."""
    return render_template('machines.html')

@admin_bp.route('/machines', methods=['GET', 'POST'])
def manage_machines():
    """API endpoint for fetching and managing machines."""
    if request.method == 'POST':
        data = request.json
        action = data.get('action')

        if action == 'add':
            name = data.get('name')
            tags = data.get('tags', [])
            active = data.get('active', True)
            with db.get_connection() as conn:
                # Insert machine and get its ID
                cursor = conn.cursor()
                cursor.execute("INSERT INTO machines (name, active) VALUES (?, ?)", (name, active))
                machine_id = cursor.lastrowid
                
                # Handle tags
                for tag in tags:
                    cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                    tag_id = cursor.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
                    cursor.execute("INSERT INTO machine_tags (machine_id, tag_id) VALUES (?, ?)", 
                                (machine_id, tag_id))
                conn.commit()
                return jsonify({"status": "success", "id": machine_id})
                
        elif action == 'update':
            machine_id = data.get('id')
            name = data.get('name')
            active = data.get('active')
            tags = data.get('tags', [])
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # Update machine info
                cursor.execute("UPDATE machines SET name = ?, active = ? WHERE id = ?", 
                            (name, active, machine_id))
                
                # Update tags
                cursor.execute("DELETE FROM machine_tags WHERE machine_id = ?", (machine_id,))
                for tag in tags:
                    cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                    tag_id = cursor.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
                    cursor.execute("INSERT INTO machine_tags (machine_id, tag_id) VALUES (?, ?)", 
                                (machine_id, tag_id))
                conn.commit()
                
        elif action == 'delete':
            machine_id = data.get('id')
            with db.get_connection() as conn:
                # First delete machine_tags entries
                conn.execute("DELETE FROM machine_tags WHERE machine_id = ?", (machine_id,))
                # Then delete the machine
                conn.execute("DELETE FROM machines WHERE id = ?", (machine_id,))
                conn.commit()
                
        return jsonify({"status": "success"})

    # GET: Fetch all machines and their tags
    machines = db.load_all_machines()
    return jsonify(machines)
