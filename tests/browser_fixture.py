"""Local-only UI fixtures. No pipeline imports, provider calls, or chain writes.

Run: python -m uvicorn tests.browser_fixture:app --host 127.0.0.1 --port 8765
Use a filename containing auto, human, or error to select the upload scenario.
"""
import asyncio
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ChitraPramaan MOCK browser API")
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3001'], allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
FINGERPRINT = 'a' * 64
CID = 'bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku'
CANDIDATES = [
    {'index': 3, 'url': 'https://www.instagram.com/p/fixture-source-one/', 'title': 'Portrait study — source photograph', 'thumbnail_url': '', 'source': 'Instagram · QA fixture', 'score': .573},
    {'index': 8, 'url': 'https://www.reddit.com/r/portraits/comments/fixture-source-two-with-a-long-normalized-source-identifier/', 'title': 'A second possible visual match', 'thumbnail_url': '', 'source': 'Reddit · QA fixture', 'score': .481},
]

@app.post('/api/sessions', status_code=201)
async def create(photo: UploadFile):
    name = photo.filename or ''
    await photo.close()
    await asyncio.sleep(2)
    if 'error' in name:
        raise HTTPException(422, 'No face was detected. Try a clear photo with one visible face.')
    auto = 'auto' in name
    candidates = [{**CANDIDATES[0], 'score': .913}, CANDIDATES[1]] if auto else CANDIDATES
    return {'session_id': 'auto-fixture' if auto else 'human-fixture', 'status': 'auto_selected' if auto else 'review_required', 'selection_method': 'auto' if auto else None, 'selected_candidate': candidates[0] if auto else None, 'candidates': candidates}

@app.post('/api/sessions/{session_id}/confirm')
async def confirm(session_id: str, payload: dict | None = None):
    await asyncio.sleep(2)
    selected_index = (payload or {}).get('candidate_index')
    recommended = session_id == 'auto-fixture' and selected_index == CANDIDATES[0]['index']
    score = .913 if recommended else next((item['score'] for item in CANDIDATES if item['index'] == selected_index), .481)
    return {'session_id': session_id, 'fingerprint': FINGERPRINT, 'selection_method': 'auto' if recommended else 'human', 'score': score, 'cid': CID, 'tx_hash': '0x' + 'b'*64, 'explorer_link': 'https://sepolia.etherscan.io/tx/0x' + 'b'*64}

@app.get('/api/verify/{fingerprint}')
async def verify(fingerprint: str):
    await asyncio.sleep(1)
    if fingerprint == 'e'*64:
        raise HTTPException(502, 'The IPFS gateway is unavailable. Try again later.')
    exists = fingerprint != 'd'*64
    passed = fingerprint == FINGERPRINT
    return {'passed': passed, 'fingerprint': fingerprint, 'fetched_fingerprint': FINGERPRINT if exists else None, 'on_chain_record': {'exists': exists, 'submitter': '0x' + 'c'*40 if exists else '', 'timestamp': 1788566400 if exists else 0, 'uri': CID if exists else ''}, 'message': 'On-chain lookup and fetched IPFS fingerprint match.' if passed else 'Fetched IPFS fingerprint does not match the on-chain lookup key.' if exists else 'No on-chain record exists for this fingerprint.'}
