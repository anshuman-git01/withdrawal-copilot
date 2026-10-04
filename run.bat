@echo off
REM Windows: double-click or run "run.bat"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env copy .env.example .env
uvicorn app.main:app --reload --port 8000
