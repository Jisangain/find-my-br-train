# live.py - Live train viewing and health check endpoints

from fastapi.responses import HTMLResponse
from typing import Dict, Any
import time


async def health_check(current_revision: int, train_positions_confirmed: Dict, train_positions_unconfirmed: Dict):
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "revision": current_revision,
        "active_trains_confirmed": len(train_positions_confirmed),
        "active_trains_unconfirmed": len(train_positions_unconfirmed)
    }


async def view_live_trains(stack, data: Dict[str, Any]):
    """View all live trains that recently received user data"""
    try:
        confirmed_trains = list(stack.confirmed_position.keys()) if stack.confirmed_position else []
        unconfirmed_trains = list(stack.unconfirmed_position.keys()) if stack.unconfirmed_position else []
        
        all_live_trains = list(set(confirmed_trains + unconfirmed_trains))
        
        def get_latest_timestamp(train_id):
            confirmed_timestamp = 0
            unconfirmed_timestamp = 0
            
            if train_id in stack.confirmed_position:
                confirmed_timestamp = stack.confirmed_position[train_id][1]
            if train_id in stack.unconfirmed_position:
                unconfirmed_timestamp = stack.unconfirmed_position[train_id][1]
            
            return max(confirmed_timestamp, unconfirmed_timestamp)
        
        all_live_trains.sort(key=get_latest_timestamp, reverse=True)
        
        tid_to_name = data.get("tid_to_name", {})
        
        total_live_trains = len(all_live_trains)
        confirmed_count = len(confirmed_trains)
        unconfirmed_count = len(unconfirmed_trains)
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Find My BR Train - Live Trains</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>🚂 Find My BR Train - Live Trains</h1>
            
            <h2>📊 Live Statistics</h2>
            <ul>
                <li><strong>Total Live Trains:</strong> {total_live_trains}</li>
                <li><strong>Confirmed Positions:</strong> {confirmed_count}</li>
                <li><strong>Unconfirmed Positions:</strong> {unconfirmed_count}</li>
                <li><strong>Data Age:</strong> Last 10 minutes</li>
            </ul>
            
            <h2>🔴 Live Trains ({total_live_trains} trains)</h2>
        """
        
        if not all_live_trains:
            html_content += "<p><em>No trains are currently live (no recent user data).</em></p>"
        else:
            html_content += "<div>"
            
            for i, train_id in enumerate(all_live_trains):
                train_name = tid_to_name.get(train_id, "Unknown Train")
                
                status = ""
                position_info = ""
                timestamp_info = ""
                
                if train_id in confirmed_trains:
                    status = "✅ Confirmed"
                    if train_id in stack.confirmed_position:
                        position, timestamp = stack.confirmed_position[train_id]
                        position_info = f"Position: {position:.2f}"
                        timestamp_info = f"Updated: {int(time.time() - timestamp)}s ago"
                elif train_id in unconfirmed_trains:
                    status = "⚠️ Unconfirmed"
                    if train_id in stack.unconfirmed_position:
                        position, timestamp = stack.unconfirmed_position[train_id]
                        position_info = f"Position: {position:.2f}"
                        timestamp_info = f"Updated: {int(time.time() - timestamp)}s ago"
                
                html_content += f"""
                <div style="border: 1px solid #ddd; margin: 5px 0; padding: 10px;">
                    <h3>#{i+1}: {train_name} ({train_id})</h3>
                    <p><strong>Status:</strong> {status}</p>
                    <p><strong>{position_info}</strong></p>
                    <p><small>{timestamp_info}</small></p>
                </div>
                """
            
            html_content += "</div>"
        
        html_content += f"""
            <hr>
            <p><small>Last updated: {int(time.time())} | <a href="/live">Refresh</a> | <a href="/health">Health Check</a></small></p>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        return HTMLResponse(content=f"""
        <html>
        <body>
            <h1>Error Loading Live Trains</h1>
            <p>Error: {str(e)}</p>
        </body>
        </html>
        """)
