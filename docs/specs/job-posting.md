# Spec: Job Posting (HR Recruitment Screen)

Status: Draft
Owner: HR / Recruitment
Date: 2026-09-25

## 1. Goal

Let recruiters create, edit, publish, and close job posts from one HR screen.

## 2. Scope

**In scope**
- Create a job post (as a draft)
- Edit a job post
- Publish a job post
- Close a job post
- List and view job posts

**Out of scope**
- Candidate application screen
- Candidate screen
- Interview screen
- Real authorization (login, roles, permissions). For now, assume the caller is an allowed recruiter.

## 3. Users

- **Recruiter**: the only user in this spec. Manages job posts.

## 4. Fields

| Field | Type | Required | Rules | Example |
|---|---|---|---|---|
| id | string (UUID) | auto | Set by the system | `3f2a...` |
| title | string | Yes | 3–100 characters | `Senior Claims Analyst` |
| department | string | Yes | Max 100 characters | `Claims Operations` |
| location | string | Yes | Max 100 characters | `Bengaluru, India` |
| employmentType | enum | Yes | `FULL_TIME`, `PART_TIME`, `CONTRACT`, `INTERN` | `FULL_TIME` |
| experience | object | Yes | `minYears` and `maxYears`, whole numbers 0–50, `minYears <= maxYears` | `{ "minYears": 3, "maxYears": 6 }` |
| skills | string[] | Yes | 1–20 items, each 1–50 characters, no duplicates | `["SQL", "Python"]` |
| description | string | Yes | 20–5000 characters | `We are looking for...` |
| openingDate | date (`YYYY-MM-DD`) | Yes | Date the post opens | `2026-10-01` |
| closingDate | date (`YYYY-MM-DD`) | Yes | Must be on or after `openingDate` | `2026-11-01` |
| status | enum | auto | `DRAFT`, `PUBLISHED`, `CLOSED` | `DRAFT` |
| createdAt, updatedAt | datetime (ISO 8601) | auto | Set by the system | |

## 5. Status Lifecycle

```
DRAFT --publish--> PUBLISHED --close--> CLOSED
```

- A new post starts as `DRAFT`.
- `DRAFT` and `PUBLISHED` posts can be edited.
- `PUBLISHED` posts can be closed.
- `CLOSED` is final. A closed post cannot be edited, published, or re-opened.
- A `PUBLISHED` post closes on its own after its `closingDate` passes.

## 6. Screen Requirements

**Job list screen**
- Table with title, department, location, employment type, opening date, closing date, status.
- Filter by status. Search by title.
- Button: "Create Job Post".
- Row actions depend on status (see below).

**Job form screen (create and edit)**
- One input for each field in section 4, except id, status, and timestamps.
- Show a validation message next to each field with an error.
- Buttons: "Save Draft" and "Publish".

**Row / detail actions**

| Status | Actions shown |
|---|---|
| DRAFT | Edit, Publish |
| PUBLISHED | Edit, Close |
| CLOSED | View only |

- "Close" asks for confirmation before it runs.

## 7. API Contract

Base path: `/api/v1/job-postings`. All bodies are JSON.

### 7.1 Create job post
`POST /api/v1/job-postings`

Request:
```json
{
  "title": "Senior Claims Analyst",
  "department": "Claims Operations",
  "location": "Bengaluru, India",
  "employmentType": "FULL_TIME",
  "experience": { "minYears": 3, "maxYears": 6 },
  "skills": ["SQL", "Python"],
  "description": "We are looking for a claims analyst to...",
  "openingDate": "2026-10-01",
  "closingDate": "2026-11-01"
}
```

Response `201 Created`: the full job post (all fields in section 4) with `status: "DRAFT"`.

### 7.2 List job posts
`GET /api/v1/job-postings?status=PUBLISHED&q=analyst&page=1&pageSize=20`

- `status`, `q` (title search), `page`, `pageSize` are all optional. Default `page=1`, `pageSize=20`, max `pageSize=100`.

Response `200 OK`:
```json
{
  "items": [ { "id": "...", "title": "...", "status": "PUBLISHED" } ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

### 7.3 Get one job post
`GET /api/v1/job-postings/{id}`

Response `200 OK`: the full job post. `404` if not found.

### 7.4 Edit job post
`PUT /api/v1/job-postings/{id}`

Request: same body as create (all editable fields).
Response `200 OK`: the updated job post.
Errors: `404` not found, `409` if status is `CLOSED`, `422` validation error.

### 7.5 Publish job post
`POST /api/v1/job-postings/{id}/publish`

No body. Response `200 OK`: the job post with `status: "PUBLISHED"`.
Errors: `404` not found, `409` if status is not `DRAFT`, `422` if a required field is invalid or `closingDate` is in the past.

### 7.6 Close job post
`POST /api/v1/job-postings/{id}/close`

No body. Response `200 OK`: the job post with `status: "CLOSED"`.
Errors: `404` not found, `409` if status is not `PUBLISHED`.

### 7.7 Error format

All errors use this shape:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "details": [
      { "field": "closingDate", "message": "Must be on or after openingDate." }
    ]
  }
}
```

Codes: `VALIDATION_ERROR` (422), `NOT_FOUND` (404), `INVALID_STATUS_TRANSITION` (409).

## 8. Acceptance Criteria (High Level)

1. A recruiter can create a job post with all required fields. It is saved as `DRAFT`.
2. Creating or editing a post with a missing or invalid field is rejected, and the screen shows a message next to that field.
3. `closingDate` earlier than `openingDate` is rejected.
4. A recruiter can edit a `DRAFT` or `PUBLISHED` post and see the changes after saving.
5. A recruiter can publish a `DRAFT` post. Its status becomes `PUBLISHED`.
6. A recruiter can close a `PUBLISHED` post after confirming. Its status becomes `CLOSED`.
7. A `CLOSED` post cannot be edited, published, or re-opened. The API returns `409` and the screen shows it as view only.
8. A `PUBLISHED` post becomes `CLOSED` automatically after its closing date.
9. The list screen shows job posts and can be filtered by status and searched by title.
10. The API returns the status codes and error format defined in section 7.

## 9. Open Questions

- Should salary or number of vacancies be added later? (Not in this version.)
- Should "Close" also allow a reason? (Not in this version.)
- Time zone for opening and closing dates: assumed to be the company's local date.
