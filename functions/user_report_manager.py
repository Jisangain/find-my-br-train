import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List

class UserReport(BaseModel):
    reported_user_id: str
    reported_by: str
    text: str
    timestamp: Optional[int] = None
    train_id: str
    train_name: Optional[str] = None

# In-memory storage for user reports
USER_REPORTS: List[dict] = []

def register_user_report_endpoints(app: FastAPI):
    """
    Registers the GET and POST endpoints for /report-user
    """
    @app.post("/report-user")
    async def post_user_report(report: UserReport):
        # Default timestamp to current server time if not provided
        report_dict = report.model_dump()
        if report_dict.get("timestamp") is None:
            report_dict["timestamp"] = int(time.time())
        
        # Insert at the beginning of the list to show newest first
        USER_REPORTS.insert(0, report_dict)
        
        print(f"\n🚨 USER REPORT RECEIVED:")
        print(f"   Reported User: {report_dict['reported_user_id']}")
        print(f"   Reported By:   {report_dict['reported_by']}")
        print(f"   Text:          {report_dict['text']}")
        print(f"   Train ID:      {report_dict['train_id']} ({report_dict.get('train_name') or 'Unknown'})")
        print(f"   Time:          {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report_dict['timestamp']))}\n")
        
        return {"status": "success", "message": "User report recorded successfully"}

    @app.get("/report-user", response_class=HTMLResponse)
    async def get_user_reports():
        total_reports = len(USER_REPORTS)
        
        # Build simple HTML with minimal CSS
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Chat User Reports</title>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f9f9f9;
            color: #333;
            line-height: 1.6;
        }}
        h1 {{
            color: #c9302c;
            border-bottom: 2px solid #c9302c;
            padding-bottom: 10px;
        }}
        .stats {{
            background-color: #f0f0f0;
            padding: 10px 15px;
            border-radius: 4px;
            margin-bottom: 20px;
            font-weight: bold;
        }}
        .report-card {{
            background-color: #fff;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .report-header {{
            font-size: 1.1em;
            color: #555;
            margin-bottom: 10px;
            border-bottom: 1px solid #eee;
            padding-bottom: 5px;
        }}
        .report-header strong {{
            color: #c9302c;
        }}
        .report-text {{
            background-color: #fcf8e3;
            border-left: 4px solid #f0ad4e;
            padding: 10px 15px;
            margin: 10px 0;
            font-family: monospace;
            white-space: pre-wrap;
            color: #555;
        }}
        .meta-info {{
            font-size: 0.9em;
            color: #666;
            margin-top: 10px;
        }}
        .meta-item {{
            margin-right: 20px;
            display: inline-block;
        }}
        .no-reports {{
            font-style: italic;
            color: #777;
            padding: 20px;
            background: #fff;
            border: 1px dashed #ccc;
            text-align: center;
        }}
    </style>
</head>
<body>
    <h1>📋 Chat User Reports (In-Memory)</h1>
    
    <div class="stats">
        Total Reports: {total_reports}
    </div>
"""
        
        if not USER_REPORTS:
            html_content += """
    <div class="no-reports">
        No user reports submitted yet.
    </div>
"""
        else:
            for idx, r in enumerate(USER_REPORTS):
                report_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['timestamp']))
                train_info = f"{r['train_id']}"
                if r.get('train_name'):
                    train_info += f" ({r['train_name']})"
                    
                html_content += f"""
    <div class="report-card">
        <div class="report-header">
            Report #{total_reports - idx}: User <strong>{r['reported_user_id']}</strong> was reported by <strong>{r['reported_by']}</strong>
        </div>
        <div class="report-text">{r['text']}</div>
        <div class="meta-info">
            <span class="meta-item"><strong>Train:</strong> {train_info}</span>
            <span class="meta-item"><strong>Time:</strong> {report_time}</span>
        </div>
    </div>
"""
                
        html_content += """
    <hr>
    <div style="text-align: center; font-size: 0.8em; color: #888;">
        <p>This is an in-memory reporting system. Restarting the backend will clear all reports.</p>
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content)
