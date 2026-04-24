#!/bin/bash

echo "Starting Backend..."

cd ~/placement-outreach-system/backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 &

echo "Starting Frontend..."

cd ~/placement-outreach-system/frontend/dashboard
npm start
