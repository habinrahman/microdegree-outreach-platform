# Example cURL requests for MicroDegree HR Outreach API

Base URL: `http://127.0.0.1:8010` (or set your backend origin via env; examples assume local dev on :8010)

Optional admin key (if `ADMIN_API_KEY` is set): add header `-H "X-Admin-Key: your-key"`

---

## Student Management

### POST /students – Add new student
```bash
curl -X POST "http://127.0.0.1:8010/students" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Rahul Kumar",
    "gmail_address": "rahul.student@gmail.com",
    "experience_years": 2,
    "skills": "AWS, Docker, Kubernetes",
    "linkedin_url": "https://linkedin.com/in/rahulkumar",
    "gmail_connected": false,
    "status": "active"
  }'
```

### GET /students – List all students
```bash
curl "http://127.0.0.1:8010/students"
```

### PUT /students/{id} – Update student
```bash
curl -X PUT "http://127.0.0.1:8010/students/<STUDENT_UUID>" \
  -H "Content-Type: application/json" \
  -d '{
    "experience_years": 3,
    "status": "active"
  }'
```

### DELETE /students/{id} – Deactivate student
```bash
curl -X DELETE "http://127.0.0.1:8010/students/<STUDENT_UUID>"
```

---

## HR Contact Management

### POST /hr – Add HR manually
```bash
curl -X POST "http://127.0.0.1:8010/hr" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Priya Sharma",
    "company": "TechCorp India",
    "email": "priya.hr@techcorp.com",
    "linkedin_url": "https://linkedin.com/in/priyasharma",
    "designation": "HR Manager",
    "city": "Bangalore",
    "source": "LinkedIn",
    "status": "active"
  }'
```

### GET /hr – List HR contacts
```bash
curl "http://127.0.0.1:8010/hr"
curl "http://127.0.0.1:8010/hr?skip=0&limit=100"
```

### PUT /hr/{id} – Update HR
```bash
curl -X PUT "http://127.0.0.1:8010/hr/<HR_UUID>" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "responded",
    "designation": "Senior HR Manager"
  }'
```

### POST /hr/upload – Upload HR via CSV
CSV columns: `name`, `company`, `email`, `linkedin`, `city`, `source`
```bash
curl -X POST "http://127.0.0.1:8010/hr/upload" \
  -F "file=@hr_contacts.csv"
```

---

## Assignments

### POST /assignments – Assign HRs to a student
Assigns multiple HRs to one student. Rejects HRs already assigned to another student; rejects if student is inactive.
```bash
curl -X POST "http://127.0.0.1:8010/assignments" \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "<STUDENT_UUID>",
    "hr_ids": ["<HR_UUID_1>", "<HR_UUID_2>"]
  }'
```

### GET /assignments – List assignments
```bash
curl "http://127.0.0.1:8010/assignments"
curl "http://127.0.0.1:8010/assignments?student_id=<STUDENT_UUID>"
curl "http://127.0.0.1:8010/assignments?hr_id=<HR_UUID>"
curl "http://127.0.0.1:8010/assignments?status=active"
```

---

## Sample CSV for /hr/upload (hr_contacts.csv)
```csv
name,company,email,linkedin,city,source
Priya Sharma,TechCorp,priya@techcorp.com,https://linkedin.com/in/priya,Bangalore,LinkedIn
Amit Singh,DevOps Inc,amit.hr@devopsinc.com,,Mumbai,Referral
```
