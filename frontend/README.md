# Face-match provenance frontend

Next.js App Router frontend for the provenance pipeline. The browser talks only to the FastAPI backend configured by `NEXT_PUBLIC_API_BASE_URL`.

```powershell
npm install
npm run dev
```

Run the backend separately from the repository root:

```powershell
uvicorn backend.main:app --reload
```

Tests mock the typed API client and do not call the backend:

```powershell
npm test
```
