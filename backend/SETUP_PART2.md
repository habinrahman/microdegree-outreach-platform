# Part 2 Setup: Campaign Engine

Follow these steps to run the email campaign flow.

---

## 1. Set environment variables

In project root `.env` (or `backend/.env` if you run from there), set:

```env
# Gmail OAuth – create credentials at https://console.cloud.google.com/
# APIs: Gmail API, Google Drive API. OAuth consent: add gmail.send, drive.readonly.
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret

# Optional: default is 20
DAILY_INITIAL_EMAIL_LIMIT=20
```

If using SQLite (default), you can leave `DATABASE_URL` unset or set:

```env
DATABASE_URL=sqlite:///./microdegree_outreach.db
```

---

## 2. Start the backend

From `backend/`:

```bash
uvicorn app.main:app --reload --port 8010
```

The scheduler runs every minute and sends due campaigns between 9:30 AM–5:30 PM IST.

---

## 3. Create a student and set Gmail + resume

**Create student:**

```bash
curl -X POST "http://127.0.0.1:8010/students" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Rahul Kumar",
    "gmail_address": "rahul.student@gmail.com",
    "experience_years": 2,
    "skills": "AWS, Docker, Kubernetes",
    "status": "active"
  }'
```

Save the returned `id` (e.g. `STUDENT_ID`).

**Set Gmail refresh token and Drive resume (after your OAuth flow):**

```bash
curl -X PUT "http://127.0.0.1:8010/students/STUDENT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "gmail_refresh_token": "YOUR_REFRESH_TOKEN_FROM_OAUTH",
    "resume_drive_file_id": "GOOGLE_DRIVE_FILE_ID",
    "gmail_connected": true
  }'
```

---

## 4. Add HR contacts and assign to student

**Add HR (or use CSV upload):**

```bash
curl -X POST "http://127.0.0.1:8010/hr" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Priya Sharma",
    "company": "TechCorp",
    "email": "priya@techcorp.com",
    "status": "active"
  }'
```

**Assign HRs to student (this creates 4 campaigns per HR: initial + 3 follow-ups):**

```bash
curl -X POST "http://127.0.0.1:8010/assignments" \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "STUDENT_ID",
    "hr_ids": ["HR_ID_1", "HR_ID_2"]
  }'
```

---

## 5. Check campaigns

List scheduled campaigns:

```bash
curl "http://127.0.0.1:8010/campaigns?status=scheduled"
curl "http://127.0.0.1:8010/campaigns?student_id=STUDENT_ID"
```

---

## 6. Record HR reply (stops follow-ups)

When an HR responds, record it so remaining follow-ups are cancelled:

```bash
curl -X POST "http://127.0.0.1:8010/responses" \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "STUDENT_ID",
    "hr_id": "HR_ID",
    "response_date": "2025-03-20",
    "response_type": "positive",
    "notes": "Interview scheduled"
  }'
```

---

## Summary

| Step | Action |
|------|--------|
| 1 | Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, optional `DAILY_INITIAL_EMAIL_LIMIT` in `.env` |
| 2 | Run `uvicorn main:app --reload` from `backend/` |
| 3 | Create student → PUT student with `gmail_refresh_token` and `resume_drive_file_id` |
| 4 | POST /assignments with `student_id` and `hr_ids` → 4 campaigns per HR created |
| 5 | Scheduler sends due campaigns every minute (IST 9:30–5:30) |
| 6 | POST /responses when HR replies → remaining follow-ups cancelled |
