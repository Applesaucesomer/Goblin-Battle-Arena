# themes.py

"""
This file holds a dictionary of pinball "themes" keyed by their display name,
with each value as a lambda function that tests whether a given machine
matches that theme's criteria.

Example usage in your main application:
    from themes import THEMES
    
    selected_theme_name = random.choice(list(THEMES.keys()))
    selected_filter = THEMES[selected_theme_name]
    matching_machines = [m for m in machines if selected_filter(m)]
"""

THEMES = {
    "70s Battle": lambda m:
        1970 <= int(m["details"]["release_date"][-4:]) <= 1979,

    "Games with No Ramps": lambda m:
        m["details"]["ramps"] == 0,

    "80s Classics": lambda m:
        1980 <= int(m["details"]["release_date"][-4:]) <= 1989,

    "90s Favorites": lambda m:
        1990 <= int(m["details"]["release_date"][-4:]) <= 1999,

    "Zero Multiball Madness": lambda m:
        m["details"]["multiball"] == 0,

    "Six-Ball Mayhem (Multiball = 6)": lambda m:
        m["details"]["multiball"] == 6,

    "Dot Matrix Heroes": lambda m:
        m["details"]["display_type"] == "Dot Matrix",

    "LCD Display Crew": lambda m:
        "LCD" in m["details"]["display_type"],

    "Music & Rock": lambda m:
        "music" in m["tags"] or "rock" in m["tags"],

    "Horror & Monsters": lambda m:
        "horror" in m["tags"] or "monsters" in m["tags"],

    "Treasure & Adventure": lambda m:
        "adventure" in m["tags"],

    "Fantasy Realms": lambda m:
        "fantasy" in m["tags"],

    "Movie Licensed": lambda m:
        "movie" in m["tags"] and "licensed" in m["tags"],

    "Motor Sports": lambda m:
        "racing" in m["tags"],

    "Solid State Throwbacks": lambda m:
        m["details"]["type"] == "Solid state"
        and int(m["details"]["release_date"][-4:]) < 2000,

    "EM Nostalgia": lambda m:
        m["details"]["type"] == "Electro-mechanical",

    "Futuristic Sci-Fi": lambda m:
        "sci-fi" in m["tags"],

    "Four-Flipper Frenzy": lambda m:
        m["details"]["flippers"] == 4,

    "Ramps Galore (3 or More)": lambda m:
        m["details"]["ramps"] >= 3,

    "Alphanumeric Retro": lambda m:
        m["details"]["display_type"] == "Alphanumeric",

    "Three-Flipper Club": lambda m:
        m["details"]["flippers"] == 3,

    "Active Sci-Fi Adventures": lambda m:
        m["active"] and "sci-fi" in m["tags"],

    "Food Frenzy": lambda m:
        any(tag in ["food", "BBQ", "festival"] for tag in m["tags"]),

    "Outdoor Sports": lambda m:
        any(tag in ["outdoor", "sports"] for tag in m["tags"]),

    "Bally Originals": lambda m:
        "Bally" in m["details"]["manufacturer"],

    "American Pinball All-Stars": lambda m:
        m["details"]["manufacturer"] == "American Pinball",

    "Gottlieb Gems": lambda m:
        "Gottlieb" in m["details"]["manufacturer"],

    "Williams System 11 Showcase": lambda m:
        "Williams System 11" in m["details"]["generation"],

    "TV Series Ties": lambda m:
        "television" in m["tags"],

    "Small Release Runs (≤ 500 units)": lambda m:
        isinstance(m["details"]["release_count"], int)
        and m["details"]["release_count"] <= 500,

    "Digital Old-School (Display = \"Digital\")": lambda m:
        m["details"]["display_type"] == "Digital",

    "Mechanical Reels Throwback": lambda m:
        m["details"]["display_type"] == "Mechanical Reels",

    "5-Ball (or More) Multiball": lambda m:
        m["details"]["multiball"] >= 5,

    "Sky High Adventures": lambda m:
        any(tag in ["aviation", "skydiving", "hang gliding"] for tag in m["tags"]),

    "Space Explorers": lambda m:
        "space" in m["tags"],

    "Flipper Overload (4 or More)": lambda m:
        m["details"]["flippers"] >= 4,

    "Movie Marathon": lambda m:
        "movie" in m["tags"],

    "Under 2,000 Release Count": lambda m:
        isinstance(m["details"]["release_count"], int)
        and m["details"]["release_count"] < 2000,

    "Widebodies": lambda m:
        "Wide" in m["details"]["cabinet"],

    "BBQ & Brew": lambda m:
        any(tag in ["BBQ", "food", "beer", "festival"] for tag in m["tags"]),

    "Swords & Sorcery": lambda m:
        any(tag in ["fantasy", "Norse mythology", "mythology"] for tag in m["tags"]),

    "Comedy & Humor": lambda m:
        "comedy" in m["tags"],

    "Mythology Matters": lambda m:
        "mythology" in m["tags"],

    "Pinball Giants (Over 10,000 Made)": lambda m:
        isinstance(m["details"]["release_count"], int)
        and m["details"]["release_count"] > 10000,

    "Still Rolling Off the Line (In Production)": lambda m:
        m["details"]["release_count"] == "In production",

    "Solid State Stern": lambda m:
        "Stern" in m["details"]["manufacturer"]
        and m["details"]["type"] == "Solid state",

    "Late 90s Hits (1995–1999)": lambda m:
        1995 <= int(m["details"]["release_date"][-4:]) <= 1999,

    "Sports Galore": lambda m:
        "sports" in m["tags"],

    "Less Than 3 Flippers": lambda m:
        m["details"]["flippers"] < 3
}
