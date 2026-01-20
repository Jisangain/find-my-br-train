# data_loader.py - Data loading utilities

import json


def load_data():
    """Load data from JSON file"""
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            return data, data['Revision']
    except FileNotFoundError:
        print("Warning: data.json not found, using fallback data")
        return -1, 0
